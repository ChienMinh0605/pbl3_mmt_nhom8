import json
from pathlib import Path

from backend.app import main
from research.activity_records import Capture
from research.device_activity import ActivityMonitor, mac_digest, sanitize_packet
from research.reliability_demo import demo_trace


FIXTURE = Path(__file__).with_name('fixtures') / 'device_activity_v2.jsonl'
SOURCE_A, SOURCE_B = '02:11:22:33:44:55', '06:aa:bb:cc:dd:ee'
DEVICES = [dict(id=key * 32, name=f'Device {key}', channel=6, consent_at='2026-11-23T00:00:00Z') for key in 'ab']


def sanitized_trace():
    key = bytes(32)
    bindings = {mac_digest(key, address, 6): device['id'] for address, device in zip((SOURCE_A, SOURCE_B), DEVICES)}
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows.insert(5, rows[3] | {'source_mac': SOURCE_B})
    for row in rows:
        if row['type'] == 'status':
            row['registered_devices'] = 2
    last = rows[-1]
    rows.extend(last | {'ts_us': 1000 + i * 1_000_000} for i in range(2, 21))
    for seq, row in enumerate(rows):
        yield sanitize_packet(row | {'seq': seq}, bindings, key)


def test_two_active_then_no_observed_activity_and_late_sample():
    monitor = ActivityMonitor(DEVICES)
    rows = list(sanitized_trace())
    for row in rows:
        now = row['ts_us'] / 1_000_000
        monitor.feed(row, now)
        if row['ts_us'] == 10_001_000:
            assert [device['state'] for device in monitor.snapshot(now, 'connected')['devices']] == ['OBSERVED_ACTIVE'] * 2
    silent = monitor.snapshot(now, 'connected')['devices']
    assert [device['state'] for device in silent] == ['NO_OBSERVED_ACTIVITY'] * 2
    assert all(device['last_seen_us'] == 1_000_250 for device in silent)
    late = next(row for row in rows if row['type'] == 'activity_sample' and 'device_id' in row)
    monitor.feed(late | {'seq': rows[-1]['seq'] + 1}, now + 1)
    monitor.feed(rows[-1] | {'seq': rows[-1]['seq'] + 2, 'ts_us': 30_001_000}, now + 1)
    assert all(device['state'] == 'UNKNOWN' and 'misaligned_sample' in device['reasons']
               for device in monitor.snapshot(now + 1, 'connected')['devices'])


def test_stage3_capture_through_q2_and_q3_replay(client):
    capture = Capture(main.svc.activity_root, DEVICES, 0)
    for row in sanitized_trace():
        capture.append(row['ts_us'] / 1_000_000, packet=row)
    meta = capture.finish(20.1)
    raw = (capture.root / 'raw.jsonl').read_text()
    assert SOURCE_A not in raw and SOURCE_B not in raw and 'mac_hmac' not in raw

    trace = demo_trace().model_dump()
    trace.update(duration_s=10, sniffer_intervals=[],
                 sniffer_clock=[dict(board_us=t + 1000, session_us=t, uncertainty_us=1000) for t in (0, 10_000_000)])
    q2 = client.post('/api/device-csi/quality/replays', json={
        'trace': trace, 'sniffer_capture_id': meta['id'], 'sniffer_boot_id': '0123456789abcdef',
    })
    assert q2.status_code == 422
    trace.update(provenance='live_adapter', sniffer_source='LIVE', sniffer_session_id=meta['id'])
    q2 = client.post('/api/device-csi/quality/replays', json={
        'trace': trace, 'sniffer_capture_id': meta['id'], 'sniffer_boot_id': '0123456789abcdef',
    })
    assert q2.status_code == 201, q2.text
    prefix = '/api/device-csi/reliability/sessions'
    q3 = client.post(prefix, json={'mode': 'REPLAY', 'quality_replay_id': q2.json()['id']})
    assert q3.status_code == 201, q3.text
    url = f'{prefix}/{q3.json()["id"]}/timeline?window_s=10'
    report = client.get(url).json()
    assert report['session']['sniffer_capture_id'] == meta['id'] and report['session']['provenance'] == 'live_adapter'
    row = report['current']
    assert row['event_timestamp']['session_us'] == 10_000_000
    assert row['evidence_mode'] == 'CSI+Device'
    assert row['quality_indicators']['device']['active_devices'] == 2
    assert client.get(url + '&context=csi-only').json()['current']['data_sources'] == ['CSI_RX']


def test_alarm_payload_is_outside_reliability_api_contract(client):
    response = client.post('/api/device-csi/reliability/sessions', json={
        'mode': 'DEMO', 'fall_alarm': {'action': 'cancel'}, 'abnormal_breathing_alarm': True,
    })
    assert response.status_code == 422
    assert client.get('/api/device-csi/reliability/sessions').json()['sessions'] == []
