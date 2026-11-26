import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.app import main
from research.csi_reliability import (
    ChannelActivityWindow, CsiQualityWindow, DeviceActivityWindow, ReliabilityRules, SourceHealth, assess,
)
from research.reliability_demo import demo_trace


PREFIX = '/api/device-csi/reliability/sessions'
HEALTHY = SourceHealth('available', True, 0)
MISSING = SourceHealth('missing')
BASE = CsiQualityWindow(channel=6, coverage=1, receive_hz=10, packet_loss=0,
                        interarrival_p95_us=100_000, rssi_median_dbm=-47, rssi_variance_db2=1,
                        noise_floor_dbm=None, n_filtered_hz=None)
RADIO = ChannelActivityWindow(channel=6, start_us=0, end_us=1_000_000, frames_per_s=180, indicator='ELEVATED')
DEVICE = DeviceActivityWindow(channel=6, start_us=0, end_us=1_000_000, active_devices=1, frames_per_s=12, bytes_per_s=210)


def evaluate(csi=BASE, device=DEVICE, radio=RADIO, rx=HEALTHY, sniffer=HEALTHY, **kwargs):
    return assess(csi, device, radio, rx, sniffer, start_us=0, end_us=1_000_000, event_utc=None,
                  rules=ReliabilityRules(), channel_coverage=kwargs.pop("channel_coverage", 1), **kwargs)


@pytest.mark.parametrize(('loss', 'combined', 'solo'), [(0, 'GOOD', 'GOOD'), (.07, 'DEGRADED', 'GOOD'), (.25, 'DEGRADED', 'DEGRADED')])
def test_stable_traffic_and_corroboration(loss, combined, solo):
    csi = BASE.model_copy(update={'packet_loss': loss})
    result = evaluate(csi)
    assert result['reliability_label'] == combined
    assert evaluate(csi, use_context=False)['reliability_label'] == solo
    assert result['quality_indicators']['csi']['noise_floor_dbm'] is None
    assert result['quality_indicators']['csi']['n_filtered_hz'] is None


def test_fallback_for_channel_time_and_sniffer_faults():
    csi = BASE.model_copy(update={'packet_loss': .07})
    for radio, sniffer, reason in (
        (RADIO, SourceHealth('disconnected'), 'SNIFFER_DISCONNECTED'),
        (RADIO, replace(HEALTHY, clock_aligned=False), 'SNIFFER_DESYNCHRONIZED'),
        (RADIO.model_copy(update={'channel': 11}), HEALTHY, 'SNIFFER_CHANNEL_MISMATCH'),
        (RADIO.model_copy(update={'start_us': 1}), HEALTHY, 'SNIFFER_WINDOW_MISMATCH'),
    ):
        row = evaluate(csi, radio=radio, sniffer=sniffer)
        assert row['reliability_label'] == 'GOOD' and row['data_sources'] == ['CSI_RX']
        assert reason in row['reason_codes'] and row['quality_indicators']['device'] is None


@pytest.mark.parametrize('health', [MISSING, SourceHealth('disconnected'), replace(HEALTHY, age_s=16), replace(HEALTHY, clock_aligned=False)])
def test_rx_unknown_is_advisory_only(health):
    row = evaluate(rx=health)
    assert row['reliability_label'] == 'UNKNOWN' and row['quality_indicators']['csi'] is None
    assert row['advisory_only'] is True
    assert not {'suppress_alert', 'alarm', 'delay'}.intersection(row)


def test_session_api_demo_replay_and_live_isolation(client):
    def start(**body):
        response = client.post(PREFIX, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    demo = start(mode='DEMO')
    demo_result = client.get(f'{PREFIX}/{demo["id"]}/timeline?window_s=10').json()
    assert [row['reliability_label'] for row in demo_result['timeline']] == ['GOOD', 'DEGRADED']
    assert demo_result['current']['evidence_mode'] == 'CSI+Device'
    saved = client.post('/api/device-csi/quality/replays', json={'trace': demo_trace().model_dump()}).json()
    replay = start(mode='REPLAY', quality_replay_id=saved['id'])
    assert replay['provenance'] == 'synthetic'
    assert client.get(f'{PREFIX}/{replay["id"]}/timeline').json()['session']['mode'] == 'REPLAY'

    live = start(mode='LIVE', rules={'max_source_age_s': 2})
    path = f'{PREFIX}/{live["id"]}'
    assert client.get(path + '/timeline').json()['current']['reliability_label'] == 'UNKNOWN'
    body = {'offset_us': 0, 'trace': demo_trace().model_dump()}
    assert client.post(path + '/batches', json=body).status_code == 422
    body['trace']['provenance'] = 'live_adapter'
    assert client.post(path + '/batches', json=body).status_code == 422  # unlinked context
    body['trace'].update(sniffer_source='LIVE', sniffer_session_id='0' * 32)
    assert client.post(path + '/batches', json=body).status_code == 422  # different recording session
    body['trace']['sniffer_session_id'] = live['id']
    assert client.post(path + '/batches', json=body).status_code == 422  # future window
    with main.svc.store.db:
        live['started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=24)).isoformat()
        main.svc.store.db.execute('UPDATE reliability_sessions SET data=? WHERE id=?', (json.dumps(live), live['id']))
    assert client.post(path + '/batches', json=body).status_code == 202
    assert client.post(path + '/batches', json=body).status_code == 202
    body['trace']['samples'][0]['rssi_dbm'] = -65
    assert client.post(path + '/batches', json=body).status_code == 409
    report = client.get(path + '/timeline').json()
    assert len(report['timeline']) == 20 and report['current']['reliability_label'] == 'UNKNOWN'
    assert 'CSI_STALE' in report['current']['reason_codes']
    assert report['session']['mode'] == 'LIVE' and report['session']['config_version'] != demo['config_version']


def test_live_normalized_batch_is_fresh_and_uses_csi_only(client):
    live = client.post(PREFIX, json={'mode': 'LIVE'}).json()
    live['started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=11)).isoformat()
    with main.svc.store.db:
        main.svc.store.db.execute('UPDATE reliability_sessions SET data=? WHERE id=?', (json.dumps(live), live['id']))
    trace = demo_trace().model_dump() | {'provenance': 'live_adapter', 'duration_s': 10, 'sniffer_intervals': [], 'sniffer_clock': [], 'sniffer_source': None}
    url = f'{PREFIX}/{live["id"]}'
    assert client.post(url + '/batches', json={'offset_us': 0, 'trace': trace}).status_code == 202
    report = client.get(url + '/timeline?window_s=10').json()
    current = report['current']
    assert current['source_freshness']['csi']['state'] == 'fresh'
    assert current['source_freshness']['sniffer']['state'] == 'missing'
    assert current['event_timestamp']['utc'] is not None and current['event_timestamp']['session_us'] == 10_000_000
    assert current['reliability_label'] == 'GOOD' and current['data_sources'] == ['CSI_RX']


def test_experiment_markers_and_csv_for_q2_and_q3(client):
    base = '/api/device-csi/experiments'
    trace = demo_trace().model_dump()
    replay = client.post('/api/device-csi/quality/replays', json={'trace': trace}).json()
    assert client.get('/api/device-csi/quality/replays').json()['replays'][0]['id'] == replay['id']
    replay_path = f'{base}/q2/{replay["id"]}'
    replay_marker = {'label': '=Mốc thử CSV', 'elapsed_s': 5}
    assert client.post(replay_path + '/markers', json=replay_marker).status_code == 201

    def read_csv(path):
        response = client.get(path + '/export.csv?window_s=10')
        assert response.status_code == 200
        assert response.headers['content-disposition'].startswith('attachment')
        return list(csv.DictReader(response.text.lstrip('\ufeff').splitlines()))

    rows = read_csv(replay_path)
    assert rows[0]['mode'] == 'REPLAY' and rows[0]['provenance'] == 'synthetic'
    assert rows[1]['csi_receive_hz'] and rows[-1]['label'] == "'=Mốc thử CSV"

    live = client.post(PREFIX, json={'mode': 'LIVE'}).json()
    live['started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=24)).isoformat()
    with main.svc.store.db:
        main.svc.store.db.execute('UPDATE reliability_sessions SET data=? WHERE id=?', (json.dumps(live), live['id']))
    path = f'{PREFIX}/{live["id"]}'
    batch = {'offset_us': 0, 'trace': trace | {'provenance': 'live_adapter', 'sniffer_source': 'LIVE', 'sniffer_session_id': live['id']}}  # Test data only.
    assert client.post(path + '/batches', json=batch).status_code == 202
    q2_path, q3_path = (f'{base}/{scope}/{live["id"]}' for scope in ('q2', 'q3'))
    assert client.post(q2_path + '/markers', json={'label': 'Bắt đầu thao tác'}).status_code == 201
    assert client.get(q3_path + '/markers').json()['markers'][0]['elapsed_s'] >= 24
    stopped = client.post(path + '/stop').json()
    assert client.post(path + '/stop').json()['ended_at'] == stopped['ended_at']
    assert client.post(path + '/batches', json=batch).status_code == 409
    assert client.post(q3_path + '/markers', json={'label': 'Muộn'}).status_code == 409
    q2, q3 = read_csv(q2_path), read_csv(q3_path)
    assert q2[1]['csi_receive_hz'] and q3[1]['evidence_mode']
    assert q2[0]['mode'] == q3[0]['mode'] == 'LIVE'
    assert q2[-1]['label'] == q3[-1]['label'] == 'Bắt đầu thao tác'


def test_low_channel_coverage_cannot_contribute_sniffer_evidence():
    row = evaluate(channel_coverage=.7)
    assert row['evidence_source'] == 'CSI_ONLY'
    assert row['channel_coverage'] == .7
    assert 'SNIFFER_INSUFFICIENT_COVERAGE' in row['reason_codes']
    assert evaluate(rx=MISSING)['evidence_source'] == 'INSUFFICIENT_DATA'


def test_live_quality_isolates_receivers_and_matches_csv(client):
    def new_live():
        live = client.post(PREFIX, json={'mode': 'LIVE'}).json()
        live['started_at'] = (datetime.now(timezone.utc) - timedelta(seconds=22)).isoformat()
        with main.svc.store.db:
            main.svc.store.db.execute('UPDATE reliability_sessions SET data=? WHERE id=?',
                                      (json.dumps(live), live['id']))
        return live

    first, second = new_live(), new_live()
    base = demo_trace().model_dump() | dict(provenance='live_adapter', duration_s=10,
                                           sniffer_intervals=[], sniffer_clock=[], sniffer_source=None)
    base['rx_clock'][-1]['board_us'] = base['rx_clock'][-1]['session_us'] = 10_000_000
    base['rx_connected'] = [{'start_us': 0, 'end_us': 10_000_000}]
    base['samples'] = [row for row in base['samples'] if row['ts_us'] < 10_000_000]
    first_trace = base | dict(receiver_id='rx-a')
    second_trace = base | dict(receiver_id='rx-b', samples=base['samples'][::2], tx_rate_verified=False,
                               sequence_kind='uart_emission')
    for session, trace in ((first, first_trace), (second, second_trace)):
        assert client.post(f'{PREFIX}/{session["id"]}/batches',
                           json={'offset_us': 10_000_000, 'trace': trace}).status_code == 202
    assert client.post(f'{PREFIX}/{first["id"]}/batches',
                       json={'offset_us': 0, 'trace': second_trace}).status_code == 409
    a, b = (client.get(f'{PREFIX}/{entry["id"]}/timeline?window_s=10').json()
            for entry in (first, second))
    assert (a['quality']['receiver_id'], a['quality']['csi_receive_hz']) == ('rx-a', 10)
    assert (b['quality']['receiver_id'], b['quality']['csi_receive_hz']) == ('rx-b', 5)
    assert b['quality']['packet_loss_fraction'] is None
    assert a['current']['evidence_source'] == 'CSI_ONLY'
    for scope, outcome in [('q2', a['quality']), ('q3', a['current'])]:
        response = client.get(f'/api/device-csi/experiments/{scope}/{first["id"]}/export.csv')
        record = next(row for row in csv.DictReader(response.text.lstrip('\ufeff').splitlines())
                      if row['kind'] == 'window')
        assert record['source'] == a['source'] == 'LIVE'
        assert record['session_id'] == a['session_id']
        assert int(record['window_end_us']) == outcome['window_end_us']
        assert record['receiver_id'] == outcome['receiver_id']
        assert record['data_valid'] == str(outcome['data_valid'])
        assert record['channel_coverage'] == ''
        if scope == 'q2':
            assert float(record['jitter_ms']) == outcome['jitter_ms']
            assert float(record['rx_coverage']) == 1
            assert float(record['rssi_median_dbm']) == outcome['rssi_median_dbm']
            assert record['csi_channel'] == '6' and record['registered_channel'] == ''
            assert float(record['tx_packet_rate']) == 10
        else:
            assert record['evidence_source'] == outcome['evidence_source']


def test_simulation_q1_uses_monitor_and_exports_same_result(client):
    simulated = client.post(PREFIX, json={'mode': 'SIMULATION'}).json()
    reply = client.get(f'{PREFIX}/{simulated["id"]}/timeline?window_s=10').json()
    assert reply['source'] == 'SIMULATION'
    device, = reply['activity']['devices']
    assert device['state'] == 'OBSERVED_ACTIVE'
    assert device['observed_frames'] == 240 and device['channel_coverage'] == 1
    assert device['frames_per_s'] == 24 and device['observation_time_s'] == 10
    assert client.get('/api/device-csi/state').json()['source'] is None
    response = client.get(f'/api/device-csi/experiments/q1/{simulated["id"]}/export.csv')
    rows = list(csv.DictReader(response.text.lstrip('\ufeff').splitlines()))
    assert all(row['source'] == 'SIMULATION' for row in rows)
    assert [int(row['window_end_us']) for row in rows if row['kind'] == 'window'] == [10_000_000, 20_000_000]
    assert int(rows[-1]['observed_frames']) == device['observed_frames']
    assert rows[-1]['device_id'] == device['id']
