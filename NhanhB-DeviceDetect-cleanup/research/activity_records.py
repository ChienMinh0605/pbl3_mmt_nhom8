"""Record and replay validated, MAC-free envelopes for the activity monitor."""

import json
from math import isfinite
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from backend.app.device_activity_protocol import Channel, Sample, Status, UInt32, Wire
from backend.app.storage import utc
from research.device_activity import ActivityMonitor


DeviceID = Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')]


class DeviceSample(Sample):
    device_id: DeviceID
    attribution: Literal['registered']
    frame_kind: Literal['management', 'control', 'data']

    @model_validator(mode='after')
    def validate_observed_endpoints(self):
        if self.tx_frames + self.rx_frames < self.n_frames:
            raise ValueError('Each stored frame requires an observed endpoint')
        return self


class IgnoredSample(Wire):
    type: Literal['ignored_sample']


Packet = Annotated[Channel | Status | DeviceSample | IgnoredSample, Field(discriminator='type')]
packet_adapter = TypeAdapter(Packet)


class PublicDevice(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: DeviceID
    name: Annotated[str, Field(min_length=1, max_length=80)]
    channel: Annotated[int, Field(ge=1, le=13)]
    consent_at: str


class Control(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['serial_connected', 'serial_disconnected', 'invalid_line', 'session_stopped',
                  'registry_pending', 'registry_applied']
    devices: list[PublicDevice] | None = None
    registry_revision: UInt32 | None = None

    @model_validator(mode='after')
    def check_registry_event(self):
        if self.kind == 'registry_applied':
            if self.devices is None or self.registry_revision is None:
                raise ValueError('Registry event needs the applied device snapshot and revision')
        elif self.devices is not None or self.registry_revision is not None:
            raise ValueError('Unexpected registry snapshot')
        return self


class CaptureMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: DeviceID
    version: Literal[1]
    started_at: str
    ended_at: str | None
    records: Annotated[int, Field(ge=0)]
    registry_revision: UInt32 | None = None
    source: Literal['LIVE', 'SIMULATION'] = 'LIVE'
    title: str | None = None
    scenario: str | None = None
    device_ids: list[DeviceID] | None = None
    device_catalog: list[PublicDevice] | None = None
    devices: list[PublicDevice]


class Capture:
    def __init__(self, root, devices, now, registry_revision=None, **experiment):
        self.metadata = dict(id=uuid4().hex, version=1, started_at=utc(), ended_at=None,
                             records=0, devices=[row.copy() for row in devices])
        self.metadata.update(experiment)
        self.device_catalog = {row['id']: row.copy() for row in devices}
        if registry_revision is not None:
            self.metadata['registry_revision'] = registry_revision
        self.root = root / self.metadata['id']
        self.root.mkdir(parents=True, mode=0o700)
        self.origin = now
        self.raw = (self.root / 'raw.jsonl').open('x', buffering=1, encoding='utf-8')
        try:
            self.save_metadata()
        except OSError:
            self.raw.close()
            raise

    def append(self, now, *, packet=None, kind=None, **details):
        payload = {'packet': packet} if packet is not None else {'control': {'kind': kind, **details}}
        row = dict(host_elapsed_s=now - self.origin, **payload)
        self.raw.write(json.dumps(row, separators=(',', ':')) + '\n')
        self.metadata['records'] += 1
        if kind == 'registry_applied':
            self.device_catalog.update((row['id'], row.copy()) for row in details['devices'])

    def save_metadata(self):
        temp = self.root / 'metadata.tmp'
        temp.write_text(json.dumps(self.metadata, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.root / 'metadata.json')

    def finish(self, now):
        try:
            self.append(now, kind='session_stopped')
        finally:
            self.raw.close()
        self.metadata['ended_at'] = utc()
        self.metadata['device_catalog'] = list(self.device_catalog.values())
        self.save_metadata()
        return self.metadata


def read_metadata(folder):
    meta = CaptureMetadata.model_validate_json((folder / 'metadata.json').read_bytes())
    if meta.id != folder.name:
        raise ValueError('Device activity capture ID mismatch')
    return meta.model_dump()


def load_records(path):
    previous = 0.0
    with path.open('rb') as stream:
        for line in stream:
            if len(line) > 16_000:
                raise ValueError('Oversized device activity replay row')
            row = json.loads(line)
            t = row['host_elapsed_s']
            if type(t) not in (float, int) or not isfinite(t) or t < previous:
                raise ValueError('Invalid device activity replay time')
            if 'packet' in row and 'control' not in row:
                payload = packet_adapter.validate_python(row['packet']).model_dump()
            elif 'control' in row and 'packet' not in row:
                payload = {'type': 'control', **Control.model_validate(row['control']).model_dump()}
            else:
                raise ValueError('Invalid device activity replay envelope')
            previous = t
            yield t, payload


def recorded_activity_windows(path, devices):
    """Read closed Q1 windows from a capture, using the same monitor as collection."""
    monitor = ActivityMonitor(devices)
    for stamp, packet in load_records(path):
        if packet['type'] == 'control':
            monitor.control(packet['kind'], stamp, devices=packet.get('devices'))
        else:
            monitor.feed(packet, stamp)
        yield from monitor.completed


def simulated_capture(root, devices, channel, **experiment):
    """Produce an isolated UART-shaped Q1 fixture without constructing a CSI session."""
    capture = Capture(root, devices, 0, source='SIMULATION', **experiment)
    visible = [row for row in devices if row['channel'] == channel][:16]
    sequence = count = 0
    for second in range(21):
        wire = dict(v=2, node='sniffer', boot_id=capture.metadata['id'][:16], channel=channel)
        if 0 < second <= 10:
            for index, device in enumerate(visible):
                frames = 5 + index
                capture.append(second, packet=wire | dict(
                    type='activity_sample', seq=sequence, ts_us=(second - 1) * 1_000_000,
                    duration_us=1_000_000, attribution='registered', device_id=device['id'],
                    frame_kind='data', n_frames=frames, n_bytes=frames * 120, tx_frames=frames,
                    rx_frames=0, block_ack_frames=0, rssi_max_dbm=-45 - index))
                sequence += 1
                count += frames
        capture.append(second, packet=wire | dict(
            type='status', seq=sequence, ts_us=second * 1_000_000, mode='DEVICE_ACTIVITY_FIXED_CHANNEL',
            scan_mode='fixed', capture_active=True, registered_devices=len(visible), rx_callbacks=count,
            invalid_frames=0, off_channel_frames=0, unattributed_frames=0, unregistered_frames=0,
            serial_errors=0, bytes_written=0, serial_baud=460800, firmware_version='q1-simulation'))
        sequence += 1
    return capture.finish(20)
