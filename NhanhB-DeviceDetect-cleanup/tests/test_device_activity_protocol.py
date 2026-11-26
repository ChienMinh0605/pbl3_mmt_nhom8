import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.device_activity_protocol import adapter, parse_activity_line
from backend.app.protocol import parse_line


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name('fixtures')
JSONL = FIXTURES / 'device_activity_v2.jsonl'


@pytest.fixture
def samples():
    return [parse_activity_line(line) for line in JSONL.read_bytes().splitlines()]


def test_activity_jsonl_shapes_and_clock(samples):
    assert [record['seq'] for record in samples] == list(range(7))
    assert samples[0]['type'] == 'channel' and samples[0]['scan_mode'] == 'fixed'
    assert samples[1]['type'] == samples[-1]['type'] == 'status'
    activity = samples[2:-1]
    assert {sample['frame_kind'] for sample in activity} == {'management', 'control', 'data', 'misc'}
    assert all(sample['ts_us'] + sample['duration_us'] == samples[-1]['ts_us'] for sample in activity)
    assert activity[0]['block_ack_frames'] == 2
    assert activity[-1]['attribution'] == 'unattributed' and activity[-1]['source_mac'] is None


@pytest.mark.parametrize('change', [
    {'v': 1}, {'seq': 2**32}, {'channel': 14}, {'duration_us': 0}, {'source_mac': None},
    {'source_mac': '03:11:22:33:44:55'}, {'source_mac': '00:00:00:00:00:00'},
    {'attribution': 'unattributed'}, {'n_frames': True}, {'n_bytes': 8}, {'tx_frames': 5},
    {'tx_frames': 0, 'rx_frames': 0}, {'frame_kind': 'data'}, {'payload': 'secret'},
])
def test_rejects_invalid_selective_metadata(samples, change):
    with pytest.raises(ValueError):
        parse_activity_line(json.dumps(samples[2] | change))


def test_rejects_noise_and_keeps_v2_out_of_probe_service(samples):
    for invalid in ('ESP-ROM: boot', 'x' * 16_001, json.dumps(samples[-2] | {'rx_frames': 1})):
        with pytest.raises(ValueError):
            parse_activity_line(invalid)
    with pytest.raises(ValueError):
        parse_line(json.dumps(samples[-1]))


def test_schema_matches_runtime_parser():
    schema = json.loads((ROOT / 'docs/device-activity.schema.json').read_text())
    assert schema.pop('$schema') == 'https://json-schema.org/draft/2020-12/schema'
    assert schema.pop('title') == 'Device activity UART JSONL v2 record'
    assert schema == adapter.json_schema()


def test_native_80211_header_parser(tmp_path):
    compiler = shutil.which('cc')
    if compiler is None:
        pytest.skip('native C compiler unavailable')
    source = ROOT / 'firmware/sniffer/main'
    binary = tmp_path / 'activity_frame_test'
    subprocess.run([
        compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-I', source,
        FIXTURES / 'activity_frame_test.c', source / 'activity_frame.c', '-o', binary,
    ], check=True)
    subprocess.run([binary], check=True)
