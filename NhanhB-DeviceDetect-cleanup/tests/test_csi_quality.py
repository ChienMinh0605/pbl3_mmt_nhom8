import json
from pathlib import Path

import pytest

from backend.app import main
from research.activity_records import Capture
from research.csi_ingestion import CsiTrace, parse_trace
from research.csi_quality import QualityRules, timeline
from research.device_activity import sanitize_packet


FIXTURES = Path(__file__).with_name('fixtures')
PREFIX = '/api/device-csi/quality'


@pytest.fixture
def synthetic():
    return parse_trace((FIXTURES / 'csi_quality_synthetic.json').read_bytes()).model_dump()


def analyze(data, seconds=1, **policy):
    return timeline(CsiTrace.model_validate(data), QualityRules(**policy), seconds)


def test_regular_csi_and_elevated_sniffer_traffic(synthetic):
    report = analyze(synthetic)
    assert report['provenance'] == 'synthetic' and report['heuristic_uncalibrated'] is True
    assert report['clocks']['rx']['clock_offset_us'] == -5_000_000
    assert report['clocks']['sniffer']['clock_offset_us'] == -8_000_000
    assert report['clocks']['combined_error_us'] == 2000
    assert len(report['windows']) == 10
    low, elevated = report['windows'][0], report['windows'][-1]
    assert (low['channel_activity_indicator'], elevated['channel_activity_indicator']) == ('LOW', 'ELEVATED')
    assert (low['sniffer_frames_per_s'], elevated['sniffer_frames_per_s']) == (40, 160)
    assert (low['n_filtered_hz'], elevated['n_filtered_hz']) == (12, 42)
    assert all(row['comparison_ready'] and row['quality'] == 'GOOD' for row in report['windows'])
    assert low['interarrival_median_us'] == low['interarrival_p95_us'] == 100_000
    assert low['rssi_median_dbm'] == -49 and low['rssi_variance_db2'] == 1
    assert low['noise_floor_median_dbm'] == -96 and low['csi_receive_hz'] == 10
    ten, = analyze(synthetic, 10)['windows']
    assert (ten['start_us'], ten['end_us'], ten['csi_received'], ten['packet_loss_fraction']) == (0, 10_000_000, 100, 0)
    assert ten['sniffer_frames_per_s'] == 100 and ten['n_filtered_hz'] == 27


@pytest.mark.parametrize(('expected_hz', 'basis', 'lost', 'denominator'), [
    (10, 'expected_tx_rate', 3, 10),
    (None, 'tx_sequence_interior', 3, 10),
])
def test_verified_tx_loss_and_policy(synthetic, expected_hz, basis, lost, denominator):
    synthetic['expected_tx_hz'] = expected_hz
    synthetic['samples'] = [sample for sample in synthetic['samples'] if sample['seq'] not in {2, 3, 6}]
    first = analyze(synthetic)['windows'][0]
    assert first['csi_received'] == 7 and first['csi_receive_hz'] == 7
    assert (first['lost_packets'], first['expected_packets'], first['loss_basis']) == (lost, denominator, basis)
    assert first['packet_loss_fraction'] == 0.3
    assert first['quality'] == 'DEGRADED' and 'high_packet_loss' in first['reasons']
    assert analyze(synthetic, max_loss_fraction=.4)['windows'][0]['quality'] == 'GOOD'


def test_tx_wrap_and_duplicate(synthetic):
    synthetic['seq_modulus'] = 4096
    synthetic['expected_tx_hz'] = None
    for row in synthetic['samples']:
        row['seq'] = (row['seq'] + 4094) % 4096
    synthetic['samples'].insert(3, synthetic['samples'][2].copy())
    first = analyze(synthetic)['windows'][0]
    assert first['csi_received'] == 11 and first['expected_packets'] == 10 and first['lost_packets'] == 0


def test_sniffer_and_rx_dropouts_are_distinct(synthetic):
    synthetic['sniffer_intervals'].pop(1)
    synthetic['sniffer_intervals'][1]['channel'] = 11
    start = synthetic['rx_connected'][0]['start_us']
    end = synthetic['rx_connected'][0]['end_us']
    synthetic['rx_connected'] = [{'start_us': start, 'end_us': start + 3_000_000},
                                 {'start_us': start + 4_000_000, 'end_us': end}]
    windows = analyze(synthetic)['windows']
    assert windows[1]['quality'] == 'GOOD' and not windows[1]['comparison_ready']
    assert windows[1]['channel_activity_indicator'] is None
    assert windows[1]['activity_unavailable_reason'] == 'sniffer_insufficient_coverage'
    assert windows[2]['activity_unavailable_reason'] == 'sniffer_other_channel'
    assert windows[3]['quality'] == 'UNKNOWN' and windows[3]['csi_receive_hz'] is None
    assert windows[3]['packet_loss_fraction'] is None
    assert windows[4]['quality'] == 'GOOD'


def test_clock_residual_and_missing_sniffer_anchors(synthetic):
    synthetic['rx_clock'].insert(1, {'board_us': 10_000_000, 'session_us': 5_100_000, 'uncertainty_us': 1000})
    report = analyze(synthetic)
    assert report['clocks']['rx']['reason'] == 'clock_uncertainty_exceeded'
    assert report['clocks']['rx']['sync_error_us'] == 101_000
    assert all(row['quality'] == 'UNKNOWN' and not row['comparison_ready'] for row in report['windows'])
    synthetic['rx_clock'].pop(1)
    synthetic['sniffer_clock'] = []
    row = analyze(synthetic)['windows'][0]
    assert row['quality'] == 'GOOD' and row['activity_unavailable_reason'] == 'sniffer_clock_not_aligned'


def test_optional_rx_telemetry_and_uart_sequence(synthetic):
    synthetic['expected_tx_hz'] = None
    synthetic['sequence_kind'] = 'uart_emission'
    synthetic['samples'].pop(2)
    for sample in synthetic['samples']:
        sample['noise_floor_dbm'] = None
    for telemetry in synthetic['rx_telemetry']:
        telemetry['n_filtered'] = None
    first = analyze(synthetic)['windows'][0]
    assert first['quality'] == 'GOOD' and first['rx_emitted_hz'] == 10
    assert first['n_filtered_hz'] is first['noise_floor_median_dbm'] is first['packet_loss_fraction'] is None
    assert first['loss_unavailable_reason'] == 'loss_evidence_unavailable'


def test_api_persists_replay_and_rejects_unverified_rx(client, synthetic):
    response = client.post(PREFIX + '/replays', json={'trace': synthetic, 'rules': {'min_rx_hz': 11}})
    assert response.status_code == 201
    replay_id = response.json()['id']
    response = client.get(f'{PREFIX}/replays/{replay_id}/timeline', params={'window_s': 10})
    assert response.status_code == 200
    report = response.json()
    assert report['provenance'] == 'synthetic' and report['windows'][0]['quality'] == 'DEGRADED'
    assert client.get(f'{PREFIX}/replays/{replay_id}/timeline?window_s=5').status_code == 422
    assert main.svc.store.quality_replay(replay_id)['rules']['min_rx_hz'] == 11
    synthetic['provenance'] = 'unverified_import'
    assert client.post(PREFIX + '/replays', json={'trace': synthetic}).status_code == 422


def test_api_reuses_stage3_sniffer_recording(client, synthetic):
    records = [json.loads(line) for line in (FIXTURES / 'device_activity_v2.jsonl').read_text().splitlines()]
    last = records[-1]
    records.extend(last | {'seq': last['seq'] + i - 1, 'ts_us': 1000 + i * 1_000_000} for i in range(2, 11))
    capture = Capture(main.svc.activity_root, [], 0)
    for row in records:
        capture.append(row['ts_us'] / 1_000_000, packet=sanitize_packet(row, {}, None))
    metadata = capture.finish(10.01)
    synthetic['sniffer_clock'] = [{'board_us': 1000 + t, 'session_us': t, 'uncertainty_us': 1000}
                                  for t in (0, 10_000_000)]
    synthetic['sniffer_intervals'] = []
    response = client.post(PREFIX + '/replays', json={'trace': synthetic, 'sniffer_capture_id': metadata['id'],
                                                     'sniffer_boot_id': last['boot_id']})
    assert response.status_code == 422
    synthetic.update(provenance='live_adapter', sniffer_source='LIVE', sniffer_session_id=metadata['id'])
    response = client.post(PREFIX + '/replays', json={'trace': synthetic, 'sniffer_capture_id': metadata['id'],
                                                      'sniffer_boot_id': last['boot_id']})
    assert response.status_code == 201
    replay_id = response.json()['id']
    report = client.get(f'{PREFIX}/replays/{replay_id}/timeline?window_s=10').json()
    assert report['sniffer_capture_id'] == metadata['id']
    row, = report['windows']
    assert row['sniffer_frames_per_s'] == 7.1 and row['sniffer_coverage'] == 1
    assert row['comparison_ready'] and row['channel_activity_indicator'] == 'LOW'


def test_jitter_is_population_deviation_and_unverified_tx_rate_is_unavailable(synthetic):
    synthetic.update(sequence_kind='uart_emission', tx_rate_verified=False)
    synthetic['samples'] = [
        {'ts_us': 5_000_000 + t, 'seq': i} for i, t in enumerate((50_000, 150_000, 350_000))
    ]
    first = analyze(synthetic)['windows'][0]
    assert first['csi_receive_hz'] == 3
    assert first['jitter_ms'] == 50
    assert first['tx_packet_rate'] is first['packet_loss_fraction'] is None
    assert first['n_filtered'] == 12
    synthetic['samples'].pop()
    assert analyze(synthetic)['windows'][0]['jitter_ms'] is None


def test_tx_sequence_reset_is_not_counted_as_loss(synthetic):
    synthetic.update(expected_tx_hz=None, seq_modulus=4096)
    synthetic['samples'][3]['seq'] = 0
    first = analyze(synthetic)['windows'][0]
    assert first['packet_loss_fraction'] is None
    assert first['loss_unavailable_reason'] == 'ambiguous_tx_sequence'


def test_import_project_logger_matches_normalized_rx_contract():
    from io import StringIO
    from research.csi_ingestion import import_logger_csi

    csv_text = ('host_time,seq,t_us,src_mac,rssi,noise_floor,channel,sig_mode,cwb,first_word_invalid,len,csi_hex\n'
                '0.1,1,100000,02:00:00:00:00:01,-47,-95,6,1,0,1,2,0aff\n'
                '0.2,3,200000,02:00:00:00:00:01,-49,,6,1,0,1,2,0aff\n'
                '0.4,4,400000,02:00:00:00:00:01,-49,-96,6,1,0,1,2,0aff\n'
                '0.5,5,500000,02:00:00:00:00:02,-30,-95,6,1,0,1,2,0aff\n')
    metadata = dict(version='csi-quality-input-v1', provenance='synthetic', receiver_id='fixture-rx',
                    channel=6, duration_s=1, rx_connected=[dict(start_us=0, end_us=1_000_000)],
                    rx_clock=[dict(board_us=t, session_us=t, uncertainty_us=1000) for t in (0, 1_000_000)])
    normalized = import_logger_csi(StringIO(csv_text), metadata, '02:00:00:00:00:01')
    assert normalized.sequence_kind == 'uart_emission'
    assert len(normalized.samples) == 3 and '02:00' not in normalized.model_dump_json()
    first = timeline(normalized, QualityRules(), 1)['windows'][0]
    assert first['csi_receive_hz'] == 3 and first['jitter_ms'] == 50
    assert first['packet_loss_fraction'] is None and first['tx_packet_rate'] is None
    assert first['n_filtered'] is None
    with pytest.raises(ValueError, match='channel change'):
        import_logger_csi(StringIO(csv_text), metadata | {'channel': 11}, '02:00:00:00:00:01')
