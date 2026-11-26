"""Radio-quality advisory. Inputs and outputs are independent of human sensing and alerts."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field

from research.csi_ingestion import Channel, Record
from research.csi_quality import Fraction, Positive, QualityRules, csi_impairments


class ReliabilityRules(QualityRules):
    max_source_age_s: Positive = 15.0
    corroborating_loss_fraction: Fraction = 0.05
    min_registered_frames_per_s: Positive = 10.0

    @property
    def config_version(self):
        return 'radio-rules-v1-' + sha256(self.model_dump_json().encode()).hexdigest()[:12]


class CsiQualityWindow(Record):
    channel: Channel
    coverage: Fraction
    receive_hz: float | None
    packet_loss: Fraction | None
    interarrival_p95_us: float | None
    rssi_median_dbm: float | None
    rssi_variance_db2: float | None
    noise_floor_dbm: float | None
    n_filtered_hz: float | None


class DeviceActivityWindow(Record):
    channel: Channel
    start_us: int
    end_us: int
    active_devices: int
    frames_per_s: float
    bytes_per_s: float


class ChannelActivityWindow(Record):
    channel: Channel
    start_us: int
    end_us: int
    frames_per_s: float
    indicator: Literal['LOW', 'ELEVATED']


@dataclass(frozen=True)
class SourceHealth:
    availability: Literal['available', 'disconnected', 'missing']
    clock_aligned: bool = False
    age_s: float | None = None
    issue: str | None = None

    def freshness(self, limit):
        if self.availability != 'available':
            return self.availability
        if not self.clock_aligned:
            return 'desynchronized'
        if self.age_s is None:
            return 'unknown'
        return 'stale' if self.age_s > limit else 'fresh'


def assess(csi: CsiQualityWindow | None, device: DeviceActivityWindow | None,
           channel: ChannelActivityWindow | None, rx: SourceHealth, sniffer: SourceHealth,
           *, start_us, end_us, event_utc, rules: ReliabilityRules, use_context=True,
           receiver_id=None, channel_coverage=None, quality_state=None, quality_reasons=None):
    rx_status = rx.freshness(rules.max_source_age_s)
    snf_status = sniffer.freshness(rules.max_source_age_s)
    reasons, sources = [], []
    same_window = channel is not None and (channel.start_us, channel.end_us) == (start_us, end_us)
    mismatch = sniffer.issue == 'sniffer_other_channel' or (csi and channel and channel.channel != csi.channel)
    alignment = ('MISMATCH' if mismatch else 'MATCHED'
                 if csi and same_window and sniffer.clock_aligned else 'UNKNOWN')
    channel_ready = (alignment == 'MATCHED' and rx_status == snf_status == 'fresh'
                     and channel_coverage is not None and channel_coverage >= rules.min_coverage)
    device_ready = channel_ready and device is not None and (device.channel, device.start_us, device.end_us) == (csi.channel, start_us, end_us)
    use_channel, use_device = use_context and channel_ready, use_context and device_ready
    if use_context and not use_channel:
        if mismatch:
            reasons.append('SNIFFER_CHANNEL_MISMATCH')
        elif channel and (channel.start_us, channel.end_us) != (start_us, end_us):
            reasons.append('SNIFFER_WINDOW_MISMATCH')
        elif sniffer.issue == 'sniffer_insufficient_coverage' or (
            channel_coverage is not None and channel_coverage < rules.min_coverage
        ):
            reasons.append('SNIFFER_INSUFFICIENT_COVERAGE')
        elif snf_status != 'fresh':
            reasons.append('SNIFFER_' + snf_status.upper())
    if use_channel and device is not None and not use_device:
        reasons.append('DEVICE_WINDOW_OR_CHANNEL_MISMATCH')
    elif use_channel and device is None:
        reasons.append('REGISTERED_ACTIVITY_UNAVAILABLE')

    if rx_status != 'fresh':
        label = 'UNKNOWN'
        reasons.append('CSI_' + rx_status.upper())
    elif csi is None or csi.coverage < rules.min_coverage or csi.receive_hz is None:
        label = 'UNKNOWN'
        reasons.append('CSI_INSUFFICIENT_COVERAGE')
    elif quality_state == 'UNKNOWN':
        label = 'UNKNOWN'
        reasons.append('CSI_QUALITY_UNKNOWN')
    else:
        sources.append('CSI_RX')
        reason_codes = {
            'low_rx_rate': 'CSI_LOW_RECEIVE_RATE',
            'high_packet_loss': 'CSI_HIGH_PACKET_LOSS',
            'irregular_csi_arrivals': 'CSI_IRREGULAR_ARRIVAL',
            'high_rssi_variance': 'CSI_HIGH_RSSI_VARIANCE',
        }
        if quality_reasons is None:
            quality_reasons = csi_impairments(csi.receive_hz, csi.packet_loss, csi.interarrival_p95_us,
                                              csi.rssi_variance_db2, rules)
        impairment = [reason_codes[key] for key in quality_reasons if key in reason_codes]
        if use_channel:
            sources.append('SNIFFER_CHANNEL')
        if use_device:
            sources.append('REGISTERED_ACTIVITY')
        if use_channel and channel.indicator == 'ELEVATED':
            reasons.append('ELEVATED_OBSERVED_TRAFFIC')
            if (use_device and device.frames_per_s >= rules.min_registered_frames_per_s
                    and csi.packet_loss is not None and 0 < csi.packet_loss
                    and csi.packet_loss >= rules.corroborating_loss_fraction):
                impairment.append('CSI_LOSS_WITH_ALIGNED_DEVICE_TRAFFIC')
        label = 'DEGRADED' if impairment else 'GOOD'
        reasons.extend(impairment or ['CSI_WITHIN_HEURISTIC_LIMITS'])

    evidence_source = ('INSUFFICIENT_DATA' if label == 'UNKNOWN' else
                       'CSI_AND_SNIFFER' if 'SNIFFER_CHANNEL' in sources else 'CSI_ONLY')
    return dict(reliability_label=label, data_valid=label != 'UNKNOWN', receiver_id=receiver_id,
                channel_alignment=alignment, channel_coverage=channel_coverage, evidence_source=evidence_source, reason_codes=reasons, event_timestamp=dict(session_us=end_us, utc=event_utc),
                window_start_us=start_us, window_end_us=end_us, data_sources=sources,
                source_freshness={name: dict(state=health.freshness(rules.max_source_age_s), age_s=health.age_s)
                                  for name, health in (('csi', rx), ('sniffer', sniffer),
                                                       ('device', sniffer if device else SourceHealth('missing')))},
                evidence_mode='CSI+Device' if 'REGISTERED_ACTIVITY' in sources else
                              'CSI+Channel' if 'SNIFFER_CHANNEL' in sources else 'CSI-only',
                config_version=rules.config_version, advisory_only=True,
                observed_indicators=dict(channel=channel.model_dump() if channel_ready else None,
                                         device=device.model_dump() if device_ready else None),
                quality_indicators=dict(csi=csi.model_dump() if csi and rx_status == 'fresh' else None,
                                        channel=channel.model_dump() if use_channel else None,
                                        device=device.model_dump() if use_device else None))


def evidence(report, row, offset_us=0):
    start, end = row['start_us'] + offset_us, row['end_us'] + offset_us
    channel = report['channel']
    csi = CsiQualityWindow(channel=channel, coverage=row['rx_coverage'], receive_hz=row['csi_receive_hz'],
                           packet_loss=row['packet_loss_fraction'], interarrival_p95_us=row['interarrival_p95_us'],
                           rssi_median_dbm=row['rssi_median_dbm'], rssi_variance_db2=row['rssi_variance_db2'],
                           noise_floor_dbm=row['noise_floor_median_dbm'], n_filtered_hz=row['n_filtered_hz'])
    radio = (ChannelActivityWindow(channel=channel, start_us=start, end_us=end,
                                   frames_per_s=row['sniffer_frames_per_s'], indicator=row['channel_activity_indicator'])
             if row['channel_activity_indicator'] is not None else None)
    devices = (DeviceActivityWindow(channel=channel, start_us=start, end_us=end, **row['registered_activity'])
               if row.get('registered_activity') is not None and radio else None)
    return csi, devices, radio
