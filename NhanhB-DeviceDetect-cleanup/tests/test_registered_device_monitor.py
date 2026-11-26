import csv
import json
import os
import pty
import sqlite3
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app import main
from backend.app.device_activity_protocol import parse_activity_line
from research.activity_records import Capture
from research.device_activity import ActivityMonitor, sanitize_packet, mac_digest


PREFIX = '/api/device-csi'
FIXTURE = Path(__file__).with_name('fixtures') / 'device_activity_v2.jsonl'
MAC = '02:11:22:33:44:55'  # Synthetic Stage 2 fixture, never a phone measurement.
OTHER_MAC = '06:aa:bb:cc:dd:ee'
TEST_KEY = bytes(32)
DEVICE = dict(id='0' * 32, name='Fixture', channel=6, consent_at='2026-11-23T00:00:00Z')


def reference_capture(root):
    device = DEVICE | {'name': 'Mẫu tham chiếu 9 giây'}
    trace = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    status = trace[1] | {'ts_us': 0, 'seq': 0}
    capture = Capture(root, [device], 0, source='SIMULATION', title='Tham chiếu 90% coverage', scenario='mixed')
    bindings = {mac_digest(TEST_KEY, MAC, 6): device['id']}

    def append(packet, arrival):
        parsed = parse_activity_line(json.dumps(packet))
        capture.append(arrival, packet=sanitize_packet(parsed, bindings, TEST_KEY))

    append(status, 0)
    for seq, (kind, frames, size, tx, rx, ack) in enumerate((
        ('management', 128, 8192, 64, 96, 0),
        ('data', 1400, 60000, 900, 700, 0),
        ('control', 264, 9995, 120, 180, 100),
    ), start=1):
        append(trace[2] | dict(seq=seq, ts_us=0, duration_us=1_000_000, frame_kind=kind, n_frames=frames,
                               n_bytes=size, tx_frames=tx, rx_frames=rx, block_ack_frames=ack), 1)
    # The last heartbeat crosses the Q1 boundary. Its 1.5-second interval stays outside the 9 valid seconds.
    for seq, tick in enumerate([*range(1, 10), 10.5], start=4):
        append(status | dict(seq=seq, ts_us=int(tick * 1_000_000), rx_callbacks=1792), tick)
    return capture.finish(10.5)['id']


def fixture_trace(through=10):
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    last = rows[-1]
    # Extend the existing fixture with silence for deterministic window and loss tests.
    return rows + [last | {'seq': last['seq'] + i - 1, 'ts_us': 1000 + i * 1_000_000}
                   for i in range(2, through + 1)]


def monitor_trace(through=10):
    monitor = ActivityMonitor([DEVICE])
    bindings = {mac_digest(TEST_KEY, MAC, 6): DEVICE['id']}
    rows = fixture_trace(through)
    for row in rows:
        monitor.feed(sanitize_packet(row, bindings, TEST_KEY), row['ts_us'] / 1_000_000)
    return monitor, rows[-1]


def wait_state(client, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = client.get(PREFIX + '/state').json()
        if predicate(state):
            return state
        time.sleep(0.01)
    pytest.fail('Activity source did not reach expected state')


def register(client, mac=MAC, *, name='Vivo Y20', channel=6, consent=True):
    return client.post(PREFIX + '/registry', json=dict(name=name, mac=mac, channel=channel, consent=consent))


def test_registry_consent_hmac_and_rename(client, tmp_path):
    assert register(client, consent=False).status_code == 422
    assert register(client, consent=1).status_code == 422
    invalid = register(client, name=f'Phone {MAC}', consent=False)
    assert invalid.status_code == 422 and MAC not in invalid.text
    assert register(client, '03:11:22:33:44:55').status_code == 422
    device = register(client).json()
    assert {'id', 'name', 'channel', 'consent_at'} == device.keys()
    assert register(client, MAC.upper()).status_code == 409
    updated = client.patch(f'{PREFIX}/registry/{device["id"]}', json={'name': 'Vivo thử nghiệm'})
    assert updated.status_code == 200 and updated.json()['name'] == 'Vivo thử nghiệm'
    listing = client.get(PREFIX + '/registry').json()['devices']
    assert listing == [updated.json()]

    root = tmp_path / 'runtime'
    key_file = root / '.device-activity.key'
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    with sqlite3.connect(root / 'metadata.sqlite3') as db:
        saved = db.execute('SELECT mac_hmac FROM registered_devices').fetchone()[0]
    assert saved == mac_digest(key_file.read_bytes(), MAC, 6)
    assert saved != mac_digest(key_file.read_bytes(), MAC, 11)
    assert saved not in str(listing) and MAC not in str(listing)
    assert stat.S_IMODE((root / 'metadata.sqlite3').stat().st_mode) == 0o600
    details = client.get(PREFIX + '/registry?details=true').json()
    assert details['devices'][0]['wifi_mac'] == MAC and details['configuration']['state'] == 'OFFLINE'
    assert MAC not in client.get(PREFIX + '/state').text
    state = client.get(PREFIX + '/state').json()['devices'][0]
    assert state['state'] == 'UNKNOWN' and state['frames_per_s'] is None


def test_real_serial_collector_sanitized_record_replay(client, monkeypatch, tmp_path):
    device = register(client).json()
    unverified = register(client, OTHER_MAC, name='Chưa thấy').json()
    wrong_channel = register(client, MAC, name='Kênh khác', channel=11).json()
    other_wire_mac = '02:ab:cd:ef:12:34'
    master, slave = pty.openpty()
    try:
        port = os.ttyname(slave)
        monkeypatch.setattr('backend.app.api.device_activity.list_ports.comports', lambda: [SimpleNamespace(device=port)])
        assert client.post(PREFIX + '/connect', json={'port': port, 'baud': 460800}).status_code == 200
        wait_state(client, lambda state: state['diagnostics']['baudrate'] == 460800)
        status = fixture_trace()[1] | {
            'registered_devices': 2, 'firmware_version': 'test-build',
            'management_frames': 0, 'data_frames': 0, 'control_frames': 0,
        }
        os.write(master, (json.dumps(status) + '\n').encode())
        waiting = wait_state(client, lambda state: state['connection'] == 'connected')
        assert waiting['diagnostics']['firmware_version'] == 'test-build'
        assert 'NO_ACTIVITY_RECORDS' in waiting['diagnostics']['reasons']
        assert 'NO_REGISTERED_DEVICE_MATCH' in waiting['diagnostics']['reasons']
        os.write(master, b'bad record\n')
        wait_state(client, lambda state: state['diagnostics']['parsing_errors'] == 1)
        capture_response = client.post(PREFIX + '/captures/start')
        assert capture_response.status_code == 201
        capture = capture_response.json()
        experiment = f'{PREFIX}/experiments/q1/{capture["id"]}'
        assert client.get(experiment + '/export.csv').status_code == 409
        marked = client.post(experiment + '/markers', json={'label': 'Bắt đầu tải dữ liệu'}).json()
        assert marked['elapsed_s'] >= 0
        assert register(client, '02:98:76:54:32:10').status_code == 409

        trace = fixture_trace()
        trace.insert(5, trace[4] | {'source_mac': other_wire_mac})
        trace = [row | {'seq': seq} for seq, row in enumerate(trace)]
        for row in trace:
            if row['type'] == 'status':
                row['registered_devices'] = 2
                row.update(firmware_version='test-build', management_frames=1, data_frames=7, control_frames=4)
        os.write(master, ''.join(json.dumps(line) + '\n' for line in trace).encode())
        state = wait_state(client, lambda state: state['window_end_us'] == 10_000_000)
        by_id = {entry['id']: entry for entry in state['devices']}
        active = by_id[device['id']]
        assert active['state'] == 'OBSERVED_ACTIVE' and active['observation_time_s'] == 10
        assert active['frames_per_s'] == pytest.approx(1.2) and active['bytes_per_s'] == pytest.approx(177.1)
        assert active['frame_types'] == {'control': 4, 'data': 7, 'management': 1}
        assert active['rssi_max_dbm'] == -41 and active['last_seen_us'] == 1000250
        assert state['channel_frames_per_s'] > 0
        assert state['diagnostics']['data_frames'] == 7
        assert state['diagnostics']['scan_mode'] == 'fixed'
        assert state['diagnostics']['queue_drops'] is None
        assert state['diagnostics']['activity_records_received'] > 0
        assert state['diagnostics']['last_received_at']
        assert 'CHANNEL_MISMATCH' in state['diagnostics']['reasons']
        assert 'firmware_binding_unverified' in by_id[unverified['id']]['reasons']
        assert 'wrong_channel' in by_id[wrong_channel['id']]['reasons']
        probe = client.get('/api/probe/state').json()
        assert probe['result'] is None and probe['capture_mode'] == 'DEVICE_ACTIVITY_FIXED_CHANNEL'
        assert client.post('/api/probe/disconnect').status_code == 409
        assert client.get(PREFIX + '/state').json()['window_end_us'] == state['window_end_us']
        history = client.get(PREFIX + '/activity/history').json()
        assert history['source'] == 'LIVE' and history['windows'][-1]['devices'][0]['id'] == device['id']

        extra = [trace[-1] | {'seq': trace[-1]['seq'] + i, 'ts_us': trace[-1]['ts_us'] + i * 1_000_000}
                 for i in range(1, 11)]
        os.write(master, ''.join(json.dumps(line) + '\n' for line in extra).encode())
        state = wait_state(client, lambda state: state['window_end_us'] == 20_000_000)
        silent = next(item for item in state['devices'] if item['id'] == device['id'])
        assert silent['state'] == 'NO_OBSERVED_ACTIVITY' and silent['frames_per_s'] == 0
        assert silent['last_seen_us'] == 1000250 and silent['rssi_max_dbm'] is None
        assert client.post(PREFIX + '/captures/stop').status_code == 200
        exported = client.get(experiment + '/export.csv')
        assert exported.status_code == 200
        rows = list(csv.DictReader(exported.text.lstrip('\ufeff').splitlines()))
        assert any(row['state'] == 'OBSERVED_ACTIVE' and float(row['frames_per_s']) == 1.2 for row in rows)
        assert rows[-1]['kind'] == 'marker' and rows[-1]['label'] == 'Bắt đầu tải dữ liệu'
        current_row = next(row for row in rows if row['device_id'] == device['id']
                           and row['window_end_us'] == str(state['window_end_us']))
        assert current_row['source'] == 'LIVE' and current_row['session_id'] == state['session_id']
        assert current_row['state'] == silent['state'] and current_row['channel_coverage'] == '1.0'
        assert current_row['observed_frames'] == current_row['observed_bytes'] == '0'
        assert current_row['rssi_max_dbm'] == '' and 'rssi_median_dbm' not in current_row and current_row['observation_time_s'] == '10.0'
        filters = dict(session_id=capture['id'], device_id=device['id'], lookback_s=60)
        series = client.get(PREFIX + '/activity/history', params=filters | {'source': 'LIVE'}).json()
        assert [row['window_end_us'] for row in series['windows']] == [10_000_000, 20_000_000]
        assert series['windows'][-1]['devices'] == [silent]
        assert client.get(PREFIX + '/activity/history', params=filters | {'source': 'REPLAY'}).status_code == 404
        assert MAC not in exported.text

        folder = tmp_path / 'runtime' / 'device-activity' / capture['id']
        raw = (folder / 'raw.jsonl').read_text()
        assert all(value not in raw for value in ('source_mac', MAC, OTHER_MAC, other_wire_mac, 'mac_hmac'))
        assert 'ignored_sample' in raw and device['id'] in raw
        assert client.get(PREFIX + '/captures').json()['captures'][0]['ended_at']
        assert client.post(PREFIX + '/disconnect').status_code == 200
        assert all(entry['state'] == 'UNKNOWN' for entry in client.get(PREFIX + '/state').json()['devices'])
        assert client.post(PREFIX + '/replay', json={'capture_id': capture['id'], 'speed': 100}).status_code == 200
        replayed = wait_state(client, lambda state: state['connection'] == 'finished')
        assert replayed['source'] == 'REPLAY' and replayed['devices'] == state['devices']
        replay_series = client.get(PREFIX + '/activity/history', params=filters | {'source': 'REPLAY'}).json()
        assert replay_series['source'] == 'REPLAY' and replay_series['windows'] == series['windows']
        assert client.get(PREFIX + '/activity/history', params=filters | {'source': 'LIVE'}).json() == series
        replay_csv = client.get(experiment + '/export.csv?replay=true')
        assert all(row['source'] == 'REPLAY' and row['session_id'] == replayed['session_id']
                   for row in csv.DictReader(replay_csv.text.lstrip('﻿').splitlines()))
    finally:
        client.post(PREFIX + '/disconnect')
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize(('changes', 'reason'), [
    ({'seq': 500}, 'sequence_gap'),
    ({'serial_errors': 1}, 'capture_errors'),
    ({'rx_callbacks': 82, 'unattributed_frames': 9}, 'excess_unattributed_frames'),
    ({'channel': 11}, 'wrong_channel'),
])
def test_unhealthy_capture_does_not_report_zero(changes, reason):
    monitor, last = monitor_trace(19)
    t = (last['ts_us'] + 1_000_000) / 1_000_000
    monitor.feed(last | {'seq': last['seq'] + 1, 'ts_us': last['ts_us'] + 1_000_000} | changes, t)
    state = monitor.snapshot(t, 'connected')['devices'][0]
    assert state['state'] == 'UNKNOWN' and state['frames_per_s'] is None and reason in state['reasons']


def test_stale_heartbeat_reconnect_and_window_boundary():
    monitor, last = monitor_trace(11)
    t = last['ts_us'] / 1_000_000
    status = monitor.snapshot(t, 'connected')['devices'][0]
    assert status['state'] == 'OBSERVED_ACTIVE'
    assert 'heartbeat_stale' in monitor.snapshot(t + 3, 'connected')['devices'][0]['reasons']
    assert 'sniffer_disconnected' in monitor.snapshot(t, 'reconnecting')['devices'][0]['reasons']
    monitor.feed(last | {'boot_id': 'fedcba9876543210', 'seq': 0, 'ts_us': 1000}, t + 0.2)
    state = monitor.snapshot(t + 0.2, 'connected')['devices'][0]
    assert state['state'] == 'UNKNOWN' and state['last_seen_us'] is None


def test_fixed_slots_keep_history_and_discard_crossing_counts():
    monitor, first_end = monitor_trace(10)
    first = monitor.snapshot(first_end['ts_us'] / 1e6, 'connected')
    device, = first['devices']
    assert (first['window_start_us'], first['window_end_us']) == (0, 10_000_000)
    assert (device['observed_frames'], device['observed_bytes']) == (12, 1771)
    assert (device['channel_coverage'], device['last_observed_channel']) == (1, 6)

    # A jittered interval spans the boundary at 20 s. Its counts cannot be placed
    # on either side. Complete intervals provide 9.5 s of observed coverage.
    sample = sanitize_packet(fixture_trace()[3], {mac_digest(TEST_KEY, MAC, 6): DEVICE['id']}, TEST_KEY)
    for i in range(1, 11):
        tick = first_end['ts_us'] + i * 1_000_000 - 500_000
        monitor.feed(first_end | {'seq': first_end['seq'] + i, 'ts_us': tick}, tick / 1e6)
    before = monitor.status
    end = before['ts_us'] + 1_000_000
    monitor.feed(sample | {'seq': before['seq'] + 1, 'ts_us': before['ts_us'], 'duration_us': 1_000_000}, end / 1e6)
    monitor.feed(before | {'seq': before['seq'] + 2, 'ts_us': end, 'rx_callbacks': before['rx_callbacks'] + sample['n_frames']},
                 end / 1e6)
    second = monitor.snapshot(end / 1e6, 'connected')
    assert second['window_end_us'] == 20_000_000
    assert second['devices'][0]['channel_coverage'] == .95
    assert second['devices'][0]['observed_frames'] is None
    assert second['devices'][0]['reasons'] == ['activity_crosses_window_boundary']
    for i in range(1, 11):
        tick = end + i * 1_000_000
        monitor.feed(monitor.status | {'seq': monitor.status['seq'] + 1, 'ts_us': tick}, tick / 1e6)
        if not monitor.completed:
            continue
        window, = monitor.completed
        current, = window['devices']
        assert current['state'] == 'UNKNOWN' and current['observed_frames'] is None
        assert current['channel_coverage'] == .9
        if window['window_end_us'] == 30_000_000:
            assert current['reasons'] == ['activity_crosses_window_boundary']


def test_disconnect_and_boot_preserve_window_grid():
    monitor, last = monitor_trace()
    stamp = last['ts_us'] / 1_000_000
    monitor.control('serial_disconnected', stamp + 0.5)
    assert monitor.snapshot(stamp + 1, 'reconnecting')['devices'][0]['state'] == 'UNKNOWN'
    monitor.control('serial_connected', stamp + 10.5)
    missing, = monitor.completed
    assert (missing['window_start_us'], missing['window_end_us']) == (10_000_000, 20_000_000)
    assert missing['devices'][0]['channel_coverage'] is None
    assert missing['devices'][0]['observed_frames'] is None
    monitor.feed(last | {'boot_id': 'fedcba9876543210', 'seq': 0, 'ts_us': 0}, stamp + 10.5)
    for i in range(1, 11):
        monitor.feed(monitor.status | {'seq': i, 'ts_us': i * 1_000_000}, stamp + 10.5 + i)
        if monitor.completed:
            resumed, = monitor.completed
            assert (resumed['window_start_us'], resumed['window_end_us']) == (20_000_000, 30_000_000)
            assert resumed['devices'][0]['state'] == 'UNKNOWN'


def test_history_keeps_30_minutes_and_scopes_device_and_range(client):
    service = main.svc
    wrong_channel = DEVICE | {'id': '1' * 32, 'channel': 11}
    devices = [DEVICE, wrong_channel]
    capture = Capture(service.activity_root, devices, 0)
    service.activity_session_id = capture.metadata['id']
    service.activity_source = 'serial'
    service.activity = ActivityMonitor(devices)
    bindings = {mac_digest(TEST_KEY, MAC, 6): DEVICE['id']}
    for row in fixture_trace(1810):
        stamp = row['ts_us'] / 1_000_000
        packet = sanitize_packet(row, bindings, TEST_KEY)
        service.feed_activity(packet, stamp)
        capture.append(stamp, packet=packet)
    service.remember_activity_windows()  # Repeated delivery of the same closed result is idempotent.
    capture.finish(stamp + .1)

    query = dict(session_id=capture.metadata['id'], device_id=wrong_channel['id'], source='LIVE', lookback_s=1800)
    active = client.get(PREFIX + '/activity/history', params=query).json()
    assert (active['window_start_us'], active['window_end_us']) == (10_000_000, 1_810_000_000)
    assert len(active['windows']) == 180
    assert len({row['window_end_us'] for row in active['windows']}) == 180
    assert all(row['devices'][0]['id'] == wrong_channel['id'] and
               row['devices'][0]['state'] == 'UNKNOWN' for row in active['windows'])
    assert client.get(PREFIX + '/activity/history', params=query | {'source': 'SIMULATION'}).status_code == 404
    assert client.post(PREFIX + '/disconnect').status_code == 200
    archived = client.get(PREFIX + '/activity/history', params=query).json()
    assert archived == active
    early = client.get(PREFIX + '/activity/history', params=query | {
        'device_id': DEVICE['id'], 'lookback_s': 60, 'end_us': 60_000_000}).json()
    assert len(early['windows']) == 6 and early['windows'][0]['devices'][0]['observed_frames'] == 12
    assert early['windows'][-1]['devices'][0]['frames_per_s'] == 0


def test_q1_only_experiment_archive_history_and_exports(client):
    first = register(client).json()['id']
    wrong_channel = register(client, OTHER_MAC, channel=11, name='Sai kênh').json()['id']
    response = client.post(PREFIX + '/captures/simulate', json=dict(
        title='Đo Q1 độc lập', scenario='mixed', device_ids=[first, wrong_channel]))
    assert response.status_code == 201, response.text
    capture = response.json()
    key = capture['id']
    assert capture['source'] == 'SIMULATION'
    assert capture['title'] == 'Đo Q1 độc lập' and capture['scenario'] == 'mixed'
    assert not main.app.state.probe_service.store.reliability_sessions()

    query = [('session_id', key), ('device_ids', first), ('device_ids', wrong_channel)]
    response = client.get(PREFIX + '/activity/history', params=query + [('source', 'SIMULATION')])
    assert response.status_code == 200, response.text
    windows = response.json()['windows']
    assert [(row['window_start_us'], row['window_end_us']) for row in windows] == [(0, 10_000_000), (10_000_000, 20_000_000)]
    assert client.get(PREFIX + '/activity/history', params=query + [('source', 'LIVE')]).status_code == 404
    state = client.get(PREFIX + '/state', params={'simulation_id': key}).json()
    assert {row['id']: row for row in state['devices']} == {row['id']: row for row in windows[-1]['devices']}
    assert {row['id']: row['state'] for row in state['devices']} == {
        first: 'NO_OBSERVED_ACTIVITY', wrong_channel: 'UNKNOWN'}

    def export(kind, ids=()):
        response = client.get(f'{PREFIX}/experiments/q1/{key}/export.csv',
                              params=[('format', kind), *[('device_ids', id_) for id_ in ids]])
        assert response.status_code == 200, response.text
        reader = csv.DictReader(response.text.lstrip('\ufeff').splitlines())
        assert reader.fieldnames is not None
        assert not {'receiver_id', 'jitter_ms', 'evidence_source'} & set(reader.fieldnames)
        rows = list(reader)
        assert {row['source'] for row in rows} == {'SIMULATION'}
        assert {row['session_id'] for row in rows} == {key}
        return rows[1:]

    detail = export('detail', [first])
    assert len(detail) == 2 and {row['device_id'] for row in detail} == {first}
    for window, line in zip(windows, detail):
        row = next(row for row in window['devices'] if row['id'] == first)
        for field in ('observed_frames', 'observed_bytes', 'frames_per_s', 'bytes_per_s', 'channel_coverage'):
            assert float(line[field]) == row[field]
        assert line['state'] == row['state']
    assert (detail[0]['data_frames'], detail[0]['tx_frames'], detail[0]['rx_frames']) == ('50', '50', '0')

    summary = {row['device_id']: row for row in export('summary')}
    active = summary[first]
    assert (active['observed_frames'], active['observed_bytes'], active['observation_time_s']) == ('50', '6000', '20.0')
    assert (active['avg_frames_per_s'], active['max_frames_per_s'], active['stddev_frames_per_s']) == ('2.5', '5.0', '2.5')
    assert (active['representative_rssi_dbm'], active['channel_coverage'], active['activity_ratio']) == ('-45', '1.0', '0.5')
    assert [active[field] for field in ('active_windows', 'quiet_windows', 'unknown_windows')] == ['1', '1', '0']
    assert summary[wrong_channel]['unknown_windows'] == '2'
    assert summary[wrong_channel]['observed_frames'] == summary[wrong_channel]['activity_ratio'] == ''

    raw = export('raw', [first])
    assert {row['record_type'] for row in raw} == {'status', 'activity_sample', 'control'}
    assert {row['device_id'] for row in raw if row['record_type'] == 'activity_sample'} == {first}
    assert all(MAC not in str(row) and OTHER_MAC not in str(row) for row in raw)


def test_q1_reference_uart_window_dashboard_and_csv(client):
    key = reference_capture(main.app.state.probe_service.activity_root)
    state = client.get(PREFIX + '/state', params={'simulation_id': key}).json()
    assert state['source'] == 'SIMULATION'
    device, = state['devices']
    assert (device['observed_frames'], device['observed_bytes'], device['observation_time_s']) == (1792, 78187, 9)
    assert device['state'] == 'OBSERVED_ACTIVE'
    assert (device['frames_per_s'], device['bytes_per_s'], device['channel_coverage']) == (1792 / 9, 78187 / 9, .9)
    analysis = device['frame_analysis']
    assert analysis['data'] == dict(count=1400, frames_per_s=1400 / 9, fraction=1400 / 1792)
    assert analysis['tx']['count'] + analysis['rx']['count'] > device['observed_frames']
    assert device['block_ack_frames'] == 100
    history = client.get(PREFIX + '/activity/history', params=dict(source='SIMULATION', session_id=key, device_id=device['id'])).json()
    assert history['windows'][0]['devices'] == [device]
    path = f'{PREFIX}/experiments/q1/{key}'
    summary = client.get(path + '/summary').json()
    assert summary['source'] == 'SIMULATION' and summary['session_id'] == key
    row, = summary['devices']
    assert row['avg_frames_per_s'] == device['frames_per_s'] and row['avg_bytes_per_s'] == device['bytes_per_s']
    assert row['duration_s'] == 10 and row['observation_time_s'] == 9 and row['active_fraction'] == 1
    for kind, expected in (('summary', row), ('detail', {'frames_per_s': device['frames_per_s'],
                                                         'tx_frames_per_s': analysis['tx']['frames_per_s'],
                                                         'data_fraction': analysis['data']['fraction']})):
        result = client.get(path + '/export.csv', params={'format': kind})
        assert result.status_code == 200
        data, = list(csv.DictReader(result.text.lstrip('\ufeff').splitlines()))[1:]
        for field, value in expected.items():
            assert data[field] == ('' if value is None else str(value))
