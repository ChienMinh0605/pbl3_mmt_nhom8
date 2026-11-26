import csv
import io
import json
import os
import pty
import select
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app import main
from research.detectors import ProbeConfig
from test_registered_device_monitor import MAC, OTHER_MAC, fixture_trace, register, wait_state


PREFIX = '/api/device-csi'
THIRD_MAC = '02:55:66:77:88:99'


class RuntimeBoard:
    """ESP32 protocol peer. It preserves its applied config across simulated boots."""

    def __init__(self, master):
        self.master = master
        self.input = b''
        self.boot = '0123456789abcdef'
        self.revision = 7
        self.channel = 6
        self.macs = []
        self.tick = self.seq = self.count = 0
        trace = fixture_trace()
        self.sample = trace[3]
        self.status = trace[1]

    def command(self, timeout=3):
        deadline = time.monotonic() + timeout
        while b'\n' not in self.input:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.master], [], [], remaining)[0]:
                return None
            self.input += os.read(self.master, 4096)
        line, self.input = self.input.split(b'\n', 1)
        packet = json.loads(line)
        assert packet['v'] == 2 and packet['type'] == 'config_command' and packet['request_id']
        return packet

    def send(self, packet):
        os.write(self.master, (json.dumps(packet) + '\n').encode())

    def wire(self, packet, tick):
        self.send(packet | dict(boot_id=self.boot, seq=self.seq, ts_us=tick * 1_000_000,
                                channel=self.channel, registry_revision=self.revision))
        self.seq += 1

    def heartbeat(self):
        self.wire(self.status | dict(runtime_config=True, channel_min=1, channel_max=11,
                                     registered_devices=len(self.macs), rx_callbacks=self.count), self.tick)

    def advance(self, seconds, *, frames=7):
        for _ in range(seconds):
            for mac in self.macs:
                self.wire(self.sample | dict(source_mac=mac, duration_us=1_000_000, n_frames=frames,
                                              n_bytes=frames * 120, tx_frames=frames, rx_frames=0), self.tick)
                self.count += frames
            self.tick += 1
            self.heartbeat()

    def configure(self, command, *, ack=True, error=None):
        assert command['command'] == 'set_registry'
        if not error:
            new_config = command['channel'], command['macs']
            if new_config != (self.channel, self.macs):
                self.channel, self.macs = new_config
                self.revision += 1
        if ack:
            reply = dict(v=2, node='sniffer', type='config_reply', boot_id=self.boot,
                         request_id=command['request_id'], ok=error is None, channel=self.channel,
                         registered_devices=len(self.macs), registry_revision=self.revision)
            self.send(reply | ({'error': error} if error else {'macs': self.macs}))
        self.heartbeat()

    def reboot(self):
        self.boot = 'fedcba9876543210'
        self.tick = self.seq = self.count = 0
        self.heartbeat()


@contextmanager
def virtual_board(monkeypatch):
    master, slave = pty.openpty()
    try:
        port = os.ttyname(slave)
        monkeypatch.setattr('backend.app.api.device_activity.list_ports.comports',
                            lambda: [SimpleNamespace(device=port)])
        yield RuntimeBoard(master), port
    finally:
        os.close(master)
        os.close(slave)


def connect(client, board, port):
    response = client.post(PREFIX + '/connect', json={'port': port, 'baud': 460800})
    assert response.status_code == 200
    wait_state(client, lambda state: state['diagnostics']['baudrate'] == 460800)
    board.heartbeat()


def configuration(client):
    return client.get(PREFIX + '/registry?details=true').json()['configuration']


def wait_sync(client):
    wait_state(client, lambda _: configuration(client)['state'] == 'SYNCED')


def test_runtime_registry_crud_channel_and_capture_revision(client, monkeypatch, tmp_path):
    first = register(client).json()
    with virtual_board(monkeypatch) as (board, port), ThreadPoolExecutor() as calls:
        connect(client, board, port)
        command = board.command()
        assert command['macs'] == [MAC]
        board.configure(command)
        wait_sync(client)
        capture = client.post(PREFIX + '/captures/start', json=dict(
            title='Đổi registry khi đang ghi', scenario='channel', device_ids=[first['id']])).json()
        assert capture['registry_revision'] == board.revision
        board.advance(11)
        before = wait_state(client, lambda s: s['window_end_us'] == 10_000_000)
        assert before['devices'][0]['observed_frames'] == 70

        adding = calls.submit(register, client, OTHER_MAC, name='Thiết bị thứ hai')
        command = board.command()
        assert command['macs'] == sorted([MAC, OTHER_MAC])
        assert not adding.done() and configuration(client)['state'] == 'PENDING'
        pending = client.get(PREFIX + '/state').json()
        assert len(pending['devices']) == 2
        assert all(row['state'] == 'UNKNOWN' for row in pending['devices'])
        board.configure(command)
        added = adding.result(timeout=3)
        assert added.status_code == 201 and added.headers['X-Registry-Sync'] == 'SYNCED'
        second = added.json()
        wait_state(client, lambda s: s['diagnostics']['registered_devices'] == 2)
        board.advance(10, frames=3)
        after = wait_state(client, lambda s: s['window_end_us'] == 20_000_000)
        assert {row['observed_frames'] for row in after['devices']} == {30}
        assert after['registry_revision'] == before['registry_revision'] + 1

        edit = calls.submit(client.patch, PREFIX + '/registry/' + second['id'],
                            json=dict(name='Mạng khác', mac=THIRD_MAC, channel=11, consent=True))
        command = board.command()
        assert command['macs'] == [MAC] and command['channel'] == 6
        board.configure(command)
        assert edit.result(timeout=3).status_code == 200
        assert client.put(PREFIX + '/registry/channel', json={'channel': 13}).status_code == 422
        changing = calls.submit(client.put, PREFIX + '/registry/channel', json={'channel': 11})
        command = board.command()
        assert command['channel'] == 11 and command['macs'] == [THIRD_MAC]
        board.configure(command)
        result = changing.result(timeout=3).json()
        assert result['state'] == 'SYNCED' and result['desired_channel'] == result['applied_channel'] == 11

        deleting = calls.submit(client.delete, PREFIX + '/registry/' + first['id'])
        command = board.command()
        assert command['macs'] == [THIRD_MAC]
        revision = board.revision
        board.configure(command)
        assert deleting.result(timeout=3).json()['registry_revision'] == revision  # idempotent firmware configuration
        assert {row['id'] for row in client.get(PREFIX + '/registry').json()['devices']} == {second['id']}
        assert client.post(PREFIX + '/captures/stop').status_code == 200
        saved = next(row for row in client.get(PREFIX + '/captures').json()['captures'] if row['id'] == capture['id'])
        assert {row['id'] for row in saved['devices']} == {first['id'], second['id']}
        raw_dir = tmp_path / 'runtime' / 'device-activity' / capture['id']
        raw = (raw_dir / 'raw.jsonl').read_text()
        assert 'registry_applied' in raw and all(mac not in raw for mac in (MAC, OTHER_MAC, THIRD_MAC))

        # Drop the in-memory monitor. The archived Timeline and CSV read the same revision boundary.
        assert client.post(PREFIX + '/disconnect').status_code == 200
        exported = client.get(f'{PREFIX}/experiments/q1/{capture["id"]}/export.csv')
        rows = [row for row in csv.DictReader(io.StringIO(exported.text.lstrip('\ufeff'))) if row['kind'] == 'window']
        assert {row['device_id'] for row in rows} == {first['id']}
        assert [(row['registry_revision'], row['observed_frames']) for row in rows if row['device_id'] == first['id']] == [
            (str(before['registry_revision']), '70'), (str(after['registry_revision']), '30')]
        exported = client.get(f'{PREFIX}/experiments/q1/{capture["id"]}/export.csv', params={'all_devices': True})
        rows = [row for row in csv.DictReader(io.StringIO(exported.text.lstrip('\ufeff'))) if row['kind'] == 'window']
        assert {row['device_id'] for row in rows} == {first['id'], second['id']}
        history = client.get(PREFIX + '/activity/history',
                             params=dict(source='LIVE', session_id=capture['id'], device_id=first['id'])).json()
        assert [row['registry_revision'] for row in history['windows']] == [before['registry_revision'], after['registry_revision']]
        summary_path = f'{PREFIX}/experiments/q1/{capture["id"]}/summary'
        summaries = client.get(summary_path).json()['devices']
        measured = [(row['registry_revision'], row['observed_frames'], row['avg_frames_per_s'])
                    for row in summaries if row['observed_frames'] is not None]
        assert measured == [(before['registry_revision'], 70, 7), (after['registry_revision'], 30, 3)]


def test_registry_retries_lost_ack_timeout_and_reboots(client, monkeypatch):
    monkeypatch.setattr('research.collector.CONFIG_REPLY_TIMEOUT_S', .25)
    register(client)
    with virtual_board(monkeypatch) as (board, port), ThreadPoolExecutor() as calls:
        connect(client, board, port)
        first = board.command()
        board.configure(first, ack=False)
        revision = board.revision
        retry = board.command()
        assert retry == first
        board.configure(retry)
        wait_sync(client)
        assert board.revision == revision

        adding = calls.submit(register, client, OTHER_MAC, name='Đã lưu backend')
        attempts = [board.command() for _ in range(3)]
        assert attempts[0] == attempts[1] == attempts[2]
        saved = adding.result(timeout=3)
        assert saved.status_code == 202 and saved.headers['X-Registry-Sync'] == 'SYNC_FAILED'
        assert configuration(client)['error'] == 'ack_timeout'
        board.heartbeat()
        assert board.command(timeout=.4) is None
        assert all(row['state'] == 'UNKNOWN' for row in client.get(PREFIX + '/state').json()['devices'])

        syncing = calls.submit(client.post, PREFIX + '/registry/sync')
        board.configure(board.command(), error='nvs_write_failed')
        assert syncing.result(timeout=3).json()['error'] == 'nvs_write_failed'
        board.reboot()
        command = board.command()
        assert command['macs'] == sorted([MAC, OTHER_MAC])
        board.configure(command)
        wait_sync(client)
        revision = board.revision
        assert client.post(PREFIX + '/disconnect').status_code == 200
        connect(client, board, port)
        reconnect = board.command()
        assert reconnect['macs'] == command['macs']
        board.configure(reconnect)
        wait_sync(client)
        assert board.revision == revision


def test_registry_limit_and_backend_restart(tmp_path, monkeypatch):
    config = tmp_path / 'probe.json'
    config.write_text(ProbeConfig().model_dump_json())
    monkeypatch.setenv('WIFI_PROBE_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setenv('WIFI_PROBE_CONFIG', str(config))
    with virtual_board(monkeypatch) as (board, port):
        with TestClient(main.app) as client:
            assert client.put(PREFIX + '/registry/channel', json={'channel': 11}).status_code == 202
            for index in range(16):
                assert register(client, f'02:01:02:03:04:{index:02x}', channel=11).status_code == 202
            assert register(client, MAC, channel=11).status_code == 409
            assert register(client, MAC, channel=6).status_code == 202
            connect(client, board, port)
            command = board.command()
            assert command['channel'] == 11 and len(command['macs']) == 16
            board.configure(command)
            wait_sync(client)
        with TestClient(main.app) as client:
            connect(client, board, port)
            restored = board.command()
            assert restored['channel'] == command['channel'] and restored['macs'] == command['macs']
            previous = board.revision
            board.configure(restored)
            wait_sync(client)
            assert board.revision == previous
            assert board.command(timeout=.25) is None


def test_revision_change_marks_partial_window_unknown():
    from research.device_activity import ActivityMonitor, mac_digest, sanitize_packet
    from test_registered_device_monitor import DEVICE, TEST_KEY

    monitor = ActivityMonitor([DEVICE])
    bindings = {mac_digest(TEST_KEY, MAC, 6): DEVICE['id']}
    for row in fixture_trace(10):
        monitor.feed(sanitize_packet(row, bindings, TEST_KEY) | {'registry_revision': 7},
                     row['ts_us'] / 1_000_000)
    first = monitor.latest
    assert first['registry_revision'] == 7 and first['devices'][0]['observed_frames'] == 12

    status = fixture_trace(10)[-1]
    monitor.control('registry_pending', 12.001)
    assert monitor.snapshot(12.001, 'connected')['devices'][0]['state'] == 'UNKNOWN'
    monitor.control('registry_applied', 12.001, devices=[DEVICE])
    for i in range(12, 21):
        monitor.feed(status | {'ts_us': i * 1_000_000 + 1000, 'seq': i, 'registry_revision': 8}, i + .001)
    transition = monitor.latest
    assert transition['window_start_us'] == first['window_end_us']
    assert transition['registry_revision'] == 8
    assert transition['devices'][0]['observed_frames'] is None
    assert 'capture_epoch_changed' in transition['devices'][0]['reasons']
