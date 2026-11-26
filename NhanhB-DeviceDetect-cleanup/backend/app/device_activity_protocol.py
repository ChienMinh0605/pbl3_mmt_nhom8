"""Validate UART JSONL v2 from DEVICE_ACTIVITY_FIXED_CHANNEL firmware."""

import argparse
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


MAX_LINE_BYTES = 16_000
UInt32 = Annotated[int, Field(ge=0, le=2**32 - 1)]
SafeUInt = Annotated[int, Field(ge=0, le=2**53 - 1)]
Mac = Annotated[str, Field(pattern=r'^(?:[0-9a-f][02468ace]:)(?:[0-9a-f]{2}:){4}[0-9a-f]{2}$')]


class Wire(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')

    v: Literal[2]
    node: Literal['sniffer']
    boot_id: Annotated[str, Field(pattern=r'^[0-9a-f]{16}$')]
    ts_us: SafeUInt
    seq: UInt32
    channel: Annotated[int, Field(ge=1, le=13)]
    registry_revision: UInt32 | None = None


class Sample(Wire):
    type: Literal['activity_sample']
    frame_kind: Literal['management', 'control', 'data', 'misc']
    duration_us: Annotated[SafeUInt, Field(gt=0)]
    n_frames: Annotated[UInt32, Field(gt=0)]
    n_bytes: Annotated[UInt32, Field(ge=4)]
    tx_frames: UInt32
    rx_frames: UInt32
    block_ack_frames: UInt32
    rssi_max_dbm: Annotated[int, Field(ge=-128, le=127)]

    @model_validator(mode='after')
    def check_counts(self):
        if self.n_bytes < 4 * self.n_frames or max(self.tx_frames, self.rx_frames, self.block_ack_frames) > self.n_frames:
            raise ValueError('invalid aggregated frame counts')
        if self.block_ack_frames and self.frame_kind != 'control':
            raise ValueError('Block Ack requires control frame kind')
        return self


class RegisteredSample(Sample):
    attribution: Literal['registered']
    source_mac: Mac
    frame_kind: Literal['management', 'control', 'data']

    @model_validator(mode='after')
    def require_observed_endpoint(self):
        if self.source_mac == '00:00:00:00:00:00' or self.tx_frames + self.rx_frames < self.n_frames:
            raise ValueError('registered samples need an observed endpoint for each frame')
        return self


class UnattributedSample(Sample):
    attribution: Literal['unattributed']
    source_mac: None
    tx_frames: Literal[0]
    rx_frames: Literal[0]


class FixedChannel(Wire):
    mode: Literal['DEVICE_ACTIVITY_FIXED_CHANNEL']
    scan_mode: Literal['fixed']


class Status(FixedChannel):
    type: Literal['status']
    capture_active: Literal[True]
    registered_devices: Annotated[int, Field(ge=0, le=16)]
    rx_callbacks: UInt32
    invalid_frames: UInt32
    off_channel_frames: UInt32
    unattributed_frames: UInt32
    unregistered_frames: UInt32
    serial_errors: UInt32
    bytes_written: UInt32
    serial_baud: Literal[460800]
    firmware_version: Annotated[str, Field(min_length=1, max_length=31)] | None = None
    management_frames: UInt32 | None = None
    data_frames: UInt32 | None = None
    control_frames: UInt32 | None = None
    queue_drops: UInt32 | None = None
    runtime_config: bool = False
    channel_min: Annotated[int, Field(ge=1, le=13)] | None = None
    channel_max: Annotated[int, Field(ge=1, le=13)] | None = None

    @model_validator(mode='after')
    def check_runtime(self):
        if self.runtime_config and (self.registry_revision is None or self.channel_min is None
                                    or self.channel_max is None or not self.channel_min <= self.channel <= self.channel_max):
            raise ValueError('runtime-capable heartbeat requires a revision and a valid channel range')
        return self


class Channel(FixedChannel):
    type: Literal['channel']


class ConfigReply(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    v: Literal[2]
    node: Literal['sniffer']
    type: Literal['config_reply']
    boot_id: Annotated[str, Field(pattern=r'^[0-9a-f]{16}$')]
    request_id: Annotated[str, Field(min_length=1, max_length=64)]
    ok: bool
    error: Annotated[str, Field(pattern=r'^[a-z_]{1,64}$')] | None = None
    registry_revision: UInt32
    channel: Annotated[int, Field(ge=1, le=13)]
    registered_devices: Annotated[int, Field(ge=0, le=16)]
    macs: Annotated[list[Mac], Field(max_length=16)] | None = None
    runtime_config: bool = False
    channel_min: Annotated[int, Field(ge=1, le=13)] | None = None
    channel_max: Annotated[int, Field(ge=1, le=13)] | None = None

    @model_validator(mode='after')
    def check_result(self):
        if self.ok == (self.error is not None):
            raise ValueError('reply must acknowledge or report an error')
        return self


FrameSample = Annotated[RegisteredSample | UnattributedSample, Field(discriminator='attribution')]
adapter = TypeAdapter(Annotated[FrameSample | Status | Channel | ConfigReply, Field(discriminator='type')])


def parse_activity_line(line: bytes | str) -> dict:
    if len(line) > MAX_LINE_BYTES:
        raise ValueError('oversized device activity record')
    return adapter.validate_json(line).model_dump(exclude_unset=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path, help='JSONL capture file')
    args = parser.parse_args()
    valid = invalid = 0
    with args.capture.open('rb') as stream:
        for number, line in enumerate(stream, 1):
            try:
                parse_activity_line(line.rstrip(b'\r\n'))
            except ValueError:
                print(f'Invalid device activity record at line {number}', file=sys.stderr)
                invalid += 1
            else:
                valid += 1
    print(f'{valid} valid records, {invalid} invalid records')
    return int(invalid > 0 or valid == 0)


if __name__ == '__main__':
    sys.exit(main())
