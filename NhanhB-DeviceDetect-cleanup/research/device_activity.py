"""Ten-second estimates from closed ESP32 activity intervals and heartbeat evidence."""

from collections import deque
from dataclasses import dataclass
from hmac import digest
from uuid import uuid4

from backend.app.storage import utc


WINDOW_US = 10_000_000
MIN_COVERAGE_US = 8_000_000
MAX_HEARTBEAT_S = 2.5
MAX_INVALID_FRACTION = 0.10
MAX_UNATTRIBUTED_FRACTION = 0.50
COUNTER_MASK = (1 << 32) - 1
FRAME_KINDS = ('management', 'control', 'data')


def frame_analysis(device):
    """Describe counts already attributed to this device in one Q1 window."""
    seconds = device.get('observation_time_s') if device.get('data_valid') else None
    total = device.get('observed_frames') if seconds else None
    kinds = (device.get('frame_types') or {}) if seconds else {}
    counts = {kind: kinds.get(kind) for kind in FRAME_KINDS}
    counts.update({direction: device.get(f'{direction}_frames') if seconds else None for direction in ('tx', 'rx')})
    return {kind: dict(count=count, frames_per_s=count / seconds if count is not None else None,
                       fraction=count / total if count is not None and total and kind in FRAME_KINDS else None)
            for kind, count in counts.items()}


def mac_digest(secret, mac, channel):
    return digest(secret, f'device-activity:v1:{channel}:{mac.lower()}'.encode('ascii'), 'sha256').hex()


def register_device(store, name, mac, channel):
    device = dict(id=uuid4().hex, name=name, channel=channel, consent_at=utc())
    key = mac_digest(store.activity_key(), mac, channel)
    return device if store.register_device(device, key, mac) else None


def sanitize_packet(packet, bindings, secret):
    if packet['type'] != 'activity_sample':
        return packet
    mac = packet['source_mac']
    device_id = bindings.get(mac_digest(secret, mac, packet['channel'])) if mac and bindings else None
    if device_id:
        return {key: value for key, value in packet.items() if key != 'source_mac'} | {'device_id': device_id}
    # Keep serial sequence/clock continuity even for data discarded by minimization.
    return {key: packet[key] for key in ('v', 'node', 'boot_id', 'channel', 'seq', 'ts_us', 'registry_revision')
            if key in packet} | {'type': 'ignored_sample'}


@dataclass(frozen=True)
class Interval:
    start_us: int
    end_us: int
    channel: int
    frame_count: int
    samples: tuple
    issues: frozenset


class ActivityMonitor:
    def __init__(self, devices=()):
        self.devices = {row['id']: row.copy() for row in devices}
        self.reset()

    def reset(self, boot_id=None):
        self.boot_id = boot_id
        self.channel = None
        self.seq = None
        self.status = None
        self.registry_pending = False
        self.status_at = None
        self.origin_us = None
        self.session_start_us = 0
        self.session_at = None
        self.last_window_end = 0
        self.next_end = None
        self.completed = []
        self.latest = None
        self.pending = {}
        self.issues = set()
        self.intervals = deque(maxlen=64)
        # The firmware reports a count, not the MAC manifest. A matched frame attests
        # to membership for this board boot and connection only.
        self.last_seen = {}

    def feed(self, packet, received_at):
        self.completed.clear()
        boot_id = packet['boot_id']
        if boot_id != self.boot_id:
            self.restart(boot_id, received_at)
        kind = packet['type']
        if kind == 'status' and self.status is not None and (
            packet['ts_us'] < self.status['ts_us']
            or packet['ts_us'] - self.status['ts_us'] > max(
                WINDOW_US, (received_at - self.status_at + MAX_HEARTBEAT_S) * 1_000_000)
            or packet['registered_devices'] != self.status['registered_devices']
            or packet.get('registry_revision') != self.status.get('registry_revision')
        ):
            self.restart(boot_id, received_at)
        seq = packet['seq']
        if self.seq is not None and seq != ((self.seq + 1) & COUNTER_MASK):
            self.issues.add('sequence_gap')
        self.seq = seq

        if kind in ('activity_sample', 'ignored_sample') and self.status is not None and (
            packet.get('registry_revision') != self.status.get('registry_revision')
        ):
            self.issues.add('registry_revision_mismatch')
            return None
        if self.channel is not None and self.channel != packet['channel']:
            self.issues.add('channel_changed')
        if kind in ('status', 'channel'):
            self.channel = packet['channel']
        if kind == 'status':
            return self.close_interval(packet, received_at)
        elif kind == 'activity_sample' and self.status is not None:
            device = self.devices.get(packet['device_id'])
            key = packet['device_id'], packet['frame_kind']
            if not device or device['channel'] != packet['channel'] or key in self.pending:
                self.issues.add('unexpected_sample')
            else:
                self.pending[key] = packet

    def restart(self, boot_id, received_at):
        completed = self.completed
        session_at, last_end = self.session_at, self.last_window_end
        self.reset(boot_id)
        self.session_at, self.last_window_end = session_at, last_end
        self.completed = completed
        if session_at is not None:
            self.close_missing(round((received_at - session_at) * 1_000_000))

    def close_missing(self, elapsed_us):
        while self.last_window_end + WINDOW_US <= elapsed_us:
            start = self.last_window_end
            self.last_window_end += WINDOW_US
            self.latest = dict(boot_id=self.boot_id, channel=None, window_start_us=start,
                               window_end_us=self.last_window_end, window_s=10,
                               channel_frames_per_s=None, issues=['capture_epoch_changed'],
                               devices=[self.unavailable(device, {'capture_epoch_changed'})
                                        for device in self.devices.values()])
            self.completed.append(self.latest)

    def control(self, kind, stamp, *, devices=None):
        self.completed.clear()
        if kind in ('serial_connected', 'serial_disconnected'):
            self.restart(None, stamp)
        elif kind in ('registry_pending', 'registry_applied'):
            self.restart(self.boot_id, stamp)
            self.registry_pending = kind == 'registry_pending'
            if devices is not None:
                self.devices = {row['id']: row.copy() for row in devices}
        elif kind == 'invalid_line':
            self.issues.add('invalid_line')
        elif kind == 'session_stopped' and (
            self.status_at is None or stamp - self.status_at > MAX_HEARTBEAT_S
        ) and self.session_at is not None:
            self.close_missing(round((stamp - self.session_at) * 1_000_000))

    def close_interval(self, status, received_at):
        previous = self.status
        end = status['ts_us']
        interval = None
        if previous is None:
            self.origin_us = end
            if self.session_at is None:
                self.session_at = received_at
            self.session_start_us = max(self.last_window_end, round((received_at - self.session_at) * 1_000_000))
            self.close_missing(self.session_start_us)
            self.next_end = end + WINDOW_US - self.session_start_us % WINDOW_US
        else:
            start = previous['ts_us']
            if end == start:
                # A repeated heartbeat cannot renew coverage or commit pending counts.
                self.issues.add('repeated_heartbeat')
                return
            issues = self.issues.copy()
            if end - start > MAX_HEARTBEAT_S * 1_000_000 or received_at - self.status_at > MAX_HEARTBEAT_S:
                issues.add('heartbeat_gap')
            if previous['channel'] != status['channel']:
                issues.add('channel_changed')

            def delta(field):
                return (status[field] - previous[field]) & COUNTER_MASK

            callbacks = delta('rx_callbacks')
            invalid, off_channel = delta('invalid_frames'), delta('off_channel_frames')
            if invalid > MAX_INVALID_FRACTION * callbacks or delta('serial_errors') or off_channel:
                issues.add('capture_errors')
            if delta('unattributed_frames') > MAX_UNATTRIBUTED_FRACTION * callbacks:
                issues.add('excess_unattributed_frames')
            samples = tuple(self.pending.values())
            if any(sample['ts_us'] != start or sample['duration_us'] != end - start for sample in samples):
                issues.add('misaligned_sample')
            if samples and max(sample['n_frames'] for sample in samples) > callbacks:
                issues.add('inconsistent_counters')
            interval = Interval(start, end, status['channel'], max(0, callbacks - invalid - off_channel),
                                samples, frozenset(issues))
            self.intervals.append(interval)
        self.status, self.status_at = status, received_at
        self.pending.clear()
        self.issues.clear()
        if interval:
            can_remember = not interval.issues and status['registered_devices'] > 0
            crosses_cut = end > self.next_end
            if can_remember and not crosses_cut:
                self.remember(interval)
            while self.next_end <= end:
                self.latest = self.window(self.next_end - WINDOW_US, self.next_end)
                self.completed.append(self.latest)
                self.last_window_end = self.latest['window_end_us']
                self.next_end += WINDOW_US
            if can_remember and crosses_cut:
                self.remember(interval)
        return interval

    def session_tick(self, tick):
        return self.session_start_us + tick - self.origin_us

    def remember(self, interval):
        for sample in interval.samples:
            self.last_seen[sample['device_id']] = (self.session_tick(interval.end_us), interval.channel)

    def window(self, start, end):
        overlap = [row for row in self.intervals if row.end_us > start and row.start_us < end]
        intervals = [row for row in overlap if row.start_us >= start and row.end_us <= end]
        issues = {issue for row in overlap for issue in row.issues}
        if start < self.origin_us:
            issues.add('capture_epoch_changed')
        radio = [row for row in intervals if not (row.issues - {'excess_unattributed_frames'})]
        covered = sum(row.end_us - row.start_us for row in radio)
        traffic = (sum(row.frame_count for row in radio) * 1_000_000 / covered
                   if covered >= MIN_COVERAGE_US and not (issues - {'excess_unattributed_frames'}) else None)
        channel = overlap[-1].channel if overlap else None
        return dict(boot_id=self.boot_id, channel=channel, registry_revision=self.status.get('registry_revision'),
                    window_start_us=self.session_tick(start),
                    window_end_us=self.session_tick(end), window_s=10, channel_frames_per_s=traffic,
                    issues=sorted(issues),
                    devices=[self.device_stats(device, intervals, overlap, channel, issues)
                             for device in self.devices.values()])

    def snapshot(self, now, connection):
        if connection == 'finished' and self.latest:
            return self.latest | dict(connection=connection)
        issues = set()
        if connection not in ('connected', 'finished'):
            issues.add('sniffer_disconnected')
        if self.registry_pending:
            issues.add('registry_not_synced')
        if self.status is None:
            issues.add('awaiting_activity_heartbeat')
        elif connection != 'finished' and now - self.status_at > MAX_HEARTBEAT_S:
            issues.add('heartbeat_stale')
        elif self.latest is None:
            issues.add('warming_up')
        if self.latest is not None and self.channel != self.latest['channel']:
            issues.add('channel_changed')
        if self.latest and not issues:
            return self.latest | dict(connection=connection)
        result = self.latest or dict(boot_id=self.boot_id, channel=self.channel, window_start_us=None,
                                     window_end_us=None, window_s=10, devices=[])
        rows = {row['id']: row for row in result['devices']}
        return result | dict(connection=connection, channel=self.channel, channel_frames_per_s=None,
                             issues=sorted(issues),
                             devices=[self.unavailable(device, issues, rows.get(device['id']))
                                      for device in self.devices.values()])

    def unavailable(self, device, issues, row=None):
        last_seen, last_channel = self.last_seen.get(device['id'], (None, None))
        reasons = set(issues) | set((row or {}).get('reasons', []))
        if self.channel is not None and device['channel'] != self.channel:
            reasons.add('wrong_channel')
        if last_seen is None:
            reasons.add('firmware_binding_unverified')
        return dict(device, state='UNKNOWN', data_valid=False, reasons=sorted(reasons),
                    observation_time_s=(row or {}).get('observation_time_s'),
                    channel_coverage=(row or {}).get('channel_coverage'),
                    observed_frames=None, observed_bytes=None, frames_per_s=None, bytes_per_s=None,
                    frame_types=None, tx_frames=None, rx_frames=None, block_ack_frames=None, rssi_max_dbm=None, last_seen_us=last_seen,
                    last_observed_channel=last_channel)

    def device_stats(self, device, intervals, overlap, channel, issues):
        issues = issues.copy()
        if channel is not None and channel != device['channel']:
            issues.add('wrong_channel')
        if device['id'] not in self.last_seen:
            issues.add('firmware_binding_unverified')
        eligible = [row for row in intervals if row.channel == device['channel'] and not row.issues]
        covered = sum(row.end_us - row.start_us for row in eligible)
        if covered < MIN_COVERAGE_US:
            issues.add('insufficient_coverage')
        result = self.unavailable(device, issues)
        if any(not row.issues for row in intervals):
            result.update(observation_time_s=covered / 1_000_000, channel_coverage=covered / WINDOW_US)
        if issues:
            return result

        frames = dict.fromkeys(FRAME_KINDS, 0)
        byte_count = 0
        rssis = []
        directions = {'tx_frames': 0, 'rx_frames': 0, 'block_ack_frames': 0}
        has_direction = {field: True for field in directions}
        for interval in eligible:
            for sample in interval.samples:
                if sample['device_id'] == device['id']:
                    frames[sample['frame_kind']] += sample['n_frames']
                    byte_count += sample['n_bytes']
                    rssis.append(sample['rssi_max_dbm'])
                    for field in directions:
                        value = sample.get(field)
                        if value is None:
                            has_direction[field] = False
                        else:
                            directions[field] += value
        count = sum(frames.values())
        if not count and any(row not in intervals and any(sample['device_id'] == device['id'] for sample in row.samples)
                             for row in overlap):
            result['reasons'] = ['activity_crosses_window_boundary']
            return result
        result.update(state='OBSERVED_ACTIVE' if count else 'NO_OBSERVED_ACTIVITY', data_valid=True,
                      observed_frames=count, observed_bytes=byte_count,
                      frames_per_s=count / result['observation_time_s'],
                      bytes_per_s=byte_count / result['observation_time_s'],
                      frame_types=frames, rssi_max_dbm=max(rssis, default=None))
        if count:
            result.update({field: value if has_direction[field] else None for field, value in directions.items()})
        return result
