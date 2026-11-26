"""Versioned, metadata-only input for offline CSI quality experiments."""

import argparse
import csv
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.protocol import mac_valid
from research.activity_records import load_records
from research.activity_records import DeviceID
from research.device_activity import ActivityMonitor


MAX_INPUT_BYTES = 4_000_000
Tick = Annotated[int, Field(ge=0, le=2**53 - 1)]
Count = Annotated[int, Field(ge=0, le=2**32 - 1)]
Channel = Annotated[int, Field(ge=1, le=13)]
Dbm = Annotated[int, Field(ge=-128, le=127)]


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class ClockAnchor(Record):
    board_us: Tick
    session_us: Tick
    uncertainty_us: Count


class Span(Record):
    start_us: Tick
    end_us: Tick

    @model_validator(mode='after')
    def check_duration(self):
        if self.end_us <= self.start_us:
            raise ValueError('End must follow start')
        return self


class CsiSample(Record):
    ts_us: Tick
    seq: Count | None = None
    rssi_dbm: Dbm | None = None
    noise_floor_dbm: Dbm | None = None


class RxTelemetry(Span):
    n_rx_emitted: Count | None = None
    n_filtered: Count | None = None


class DeviceCounts(Record):
    frames: Count
    bytes: Count


class SnifferSpan(Span):
    channel: Channel
    frame_count: Count
    devices: dict[DeviceID, DeviceCounts] | None = Field(default=None, max_length=64)


class CsiTrace(Record):
    version: Literal['csi-quality-input-v1']
    provenance: Literal['synthetic', 'unverified_import', 'live_adapter']
    receiver_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")] | None = None
    duration_s: Annotated[int, Field(ge=1, le=300)]
    channel: Channel
    # One RX clock epoch and one declared reference stream per trace.
    rx_clock: list[ClockAnchor] = Field(default_factory=list, max_length=32)
    sniffer_clock: list[ClockAnchor] = Field(default_factory=list, max_length=32)
    samples: list[CsiSample] = Field(max_length=30_000)
    rx_connected: list[Span] = Field(default_factory=list, max_length=1500)
    rx_telemetry: list[RxTelemetry] = Field(default_factory=list, max_length=1500)
    sniffer_source: Literal['LIVE', 'SIMULATION'] | None = None
    sniffer_session_id: Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')] | None = None
    sniffer_intervals: list[SnifferSpan] = Field(default_factory=list, max_length=1500)
    sequence_kind: Literal['unknown', 'uart_emission', 'tx_contiguous'] = 'unknown'
    seq_modulus: Annotated[int, Field(ge=2, le=2**32)] | None = None
    tx_rate_verified: bool = False
    expected_tx_hz: Annotated[int, Field(ge=1, le=10_000)] | None = None

    @model_validator(mode='after')
    def check_trace(self):
        if self.provenance == 'synthetic' and (self.sniffer_source == 'LIVE' or self.sniffer_session_id):
            raise ValueError('Synthetic CSI cannot use recorded live sniffer evidence')
        if self.provenance == 'live_adapter' and self.sniffer_source == 'SIMULATION':
            raise ValueError('Live CSI cannot use synthetic sniffer evidence')
        if any(a.ts_us > b.ts_us for a, b in zip(self.samples, self.samples[1:])):
            raise ValueError('CSI timestamps must be ordered within one boot')
        for intervals in (self.rx_connected, self.rx_telemetry, self.sniffer_intervals):
            if any(a.end_us > b.start_us for a, b in zip(intervals, intervals[1:])):
                raise ValueError('Intervals must be ordered and non-overlapping')
        if self.seq_modulus is not None and any(
            sample.seq is not None and sample.seq >= self.seq_modulus for sample in self.samples
        ):
            raise ValueError('Sequence outside declared modulus')
        return self


def parse_trace(data: bytes) -> CsiTrace:
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError('CSI trace exceeds input limit')
    return CsiTrace.model_validate_json(data)


def sniffer_span(interval, bindings_verified):
    counts = {}
    for sample in interval.samples:
        counter = counts.setdefault(sample['device_id'], {'frames': 0, 'bytes': 0})
        counter['frames'] += sample['n_frames']
        counter['bytes'] += sample['n_bytes']
    return SnifferSpan(start_us=interval.start_us, end_us=interval.end_us,
                       channel=interval.channel, frame_count=interval.frame_count,
                       devices=counts if bindings_verified else None)


def replay_sniffer(path, devices, boot_id, anchors):
    """Read completed Stage 3 activity intervals without reconstructing device MACs."""
    if len(anchors) < 2:
        return []
    monitor = ActivityMonitor(devices)
    rows = []
    for received_at, packet in load_records(path):
        if packet['type'] == 'control':
            monitor.control(packet['kind'], received_at, devices=packet.get('devices'))
            continue
        interval = monitor.feed(packet, received_at)
        if interval and not interval.issues and packet['boot_id'] == boot_id:
            if anchors[0].board_us <= interval.start_us and interval.end_us <= anchors[-1].board_us:
                rows.append(sniffer_span(interval, monitor.last_seen))
    return rows


def import_logger_csi(stream, metadata, reference_mac):
    """Project the project logger's csi.csv into one normalized RX epoch."""
    if metadata.get('provenance') not in ('live_adapter', 'synthetic'):
        raise ValueError('Declare the origin of the logger recording')
    reference = reference_mac.strip().lower()
    if not mac_valid(reference):
        raise ValueError('Use the verified reference MAC for this RX link')
    reader = csv.DictReader(stream)
    fields = {'seq', 't_us', 'src_mac', 'rssi', 'noise_floor', 'channel'}
    if not fields.issubset(reader.fieldnames or []):
        raise ValueError('CSV does not match the CSI columns of the group logger')
    samples = []
    previous_tick = None
    previous_seq = None
    for row in reader:
        if row['src_mac'].lower() != reference:
            continue
        if int(row['channel']) != metadata['channel']:
            raise ValueError('Separate each RX channel change into a separate trace')
        tick, seq = int(row['t_us']), int(row['seq'])
        if previous_tick is not None and (tick < previous_tick or seq < previous_seq):
            raise ValueError('Separate each RX clock or UART sequence reset into a separate trace')
        if seq == previous_seq:
            continue
        if len(samples) >= 30_000:
            raise ValueError('Split the recording into bounded normalized batches')
        samples.append(dict(ts_us=tick, seq=seq, rssi_dbm=int(row['rssi']) if row['rssi'] else None,
                            noise_floor_dbm=int(row['noise_floor']) if row['noise_floor'] else None))
        previous_tick, previous_seq = tick, seq
    if not metadata.get('receiver_id'):
        raise ValueError('Logger import needs the receiver identity from the experiment')
    return CsiTrace.model_validate(metadata | {'samples': samples, 'sequence_kind': 'uart_emission',
                                              'seq_modulus': None})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--logger-metadata', type=Path, help='Normalize a project logger csi.csv with this evidence JSON')
    parser.add_argument('--reference-mac', help='Reference MAC from the verified RX link')
    args = parser.parse_args()
    if bool(args.logger_metadata) != bool(args.reference_mac):
        parser.error('--logger-metadata and --reference-mac must be used together')
    if args.logger_metadata:
        try:
            metadata = json.loads(args.logger_metadata.read_text(encoding='utf-8'))
            with args.trace.open(encoding='utf-8-sig', newline='') as stream:
                trace = import_logger_csi(stream, metadata, args.reference_mac)
        except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
            parser.error(str(error))
        print(trace.model_dump_json())
        return
    with args.trace.open('rb') as stream:
        trace = parse_trace(stream.read(MAX_INPUT_BYTES + 1))
    print(f'{trace.provenance}: {len(trace.samples)} RX records, {len(trace.rx_telemetry)} telemetry intervals')


if __name__ == '__main__':
    main()
