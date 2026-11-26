"""Exercise Device & CSI on the normal dashboard using a synthetic PTY and CSI RX."""

import argparse
import csv
import io
import json
import os
import pty
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from research.csi_ingestion import import_logger_csi
from research.csi_quality import SECOND
from research.device_activity import MAX_HEARTBEAT_S

ROOT = Path(__file__).resolve().parents[1]
API = '/api/device-csi'
SESSIONS = API + '/reliability/sessions'
DEVICE_MAC = '02:11:22:33:44:55'
REFERENCE_MAC = '02:00:00:00:00:01'
DURATION = 20


@dataclass(frozen=True)
class Settings:
    channel: int = 6
    csi_channel: int = 6
    device: bool = True
    traffic: int = 40
    csi: str = 'good'
    quiet_after: int = DURATION
    heartbeat_loss: bool = False
    disconnect: bool = False


SCENARIOS = {
    'S01': Settings(),
    'S02': Settings(quiet_after=10),
    'S03': Settings(channel=11),
    'S04': Settings(heartbeat_loss=True),
    'S05': Settings(device=False),
    'S06': Settings(csi='loss'),
    'S07': Settings(),
    'S08': Settings(csi_channel=11),
    'S09': Settings(traffic=180),
    'S10': Settings(csi='off'),
    'S11': Settings(disconnect=True),
    'S12': Settings(),
}


def request(url, path, body=None, *, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(url + path, data, {'Content-Type': 'application/json'}), timeout=4) as response:
        return response.read().decode('utf-8-sig') if raw else json.load(response)


def wait_for(probe, description, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = probe()
        except URLError:
            result = None
        if result:
            return result
        time.sleep(.025)
    raise RuntimeError(f'Không nhận được {description}')


@contextmanager
def dashboard(parent, port):
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='run-', dir=parent)).resolve()
    link = folder / 'sniffer-pty'
    config = folder / 'probe.json'
    shutil.copyfile(ROOT / 'configs/probe.json', config)
    log = folder / 'backend.log'
    env = dict(os.environ, WIFI_PORT=str(port), WIFI_SIMULATION_PTY=str(link),
               WIFI_SIMULATION_DATA_DIR=str(folder), WIFI_PROBE_CONFIG=str(config), WIFI_DASHBOARD_CONFIG='')
    with log.open('w') as output:
        server = subprocess.Popen([sys.executable, '-m', 'scripts.serve'], cwd=ROOT,
                                  env=env, stdout=output, stderr=subprocess.STDOUT)
    try:
        address = wait_for(lambda: re.search(r'Mở (http://127\.0\.0\.1:\d+)', log.read_text())
                           if server.poll() is None else None, f'URL backend, xem {log}')
        url = address[1]
        wait_for(lambda: request(url, '/api/health')['ok'], 'health backend')
        request(url, API + '/registry', dict(name='Thiết bị Python PTY', mac=DEVICE_MAC, channel=6, consent=True))
        yield url, folder, link
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def rx_trace(settings, rng):
    channel = settings.csi_channel
    meta = dict(version='csi-quality-input-v1', provenance='synthetic', receiver_id='python-rx',
                duration_s=DURATION, channel=channel)
    end = DURATION * SECOND
    # The virtual TX counter measures the sent packet schedule. The logger records
    # RX emission sequence separately, as it does on the group CSV interface.
    tx = [(seq, seq * 100_000 + 50_000) for seq in range(DURATION * 10)]
    meta.update(expected_tx_hz=len(tx) // DURATION, tx_rate_verified=True)
    logger = io.StringIO()
    writer = csv.writer(logger)
    writer.writerow(('host_time', 'seq', 't_us', 'src_mac', 'rssi', 'noise_floor', 'channel', 'sig_mode',
                     'cwb', 'first_word_invalid', 'len', 'csi_hex'))
    received = {}
    if settings.csi != 'off':
        meta.update(rx_clock=[dict(board_us=t, session_us=t, uncertainty_us=1000) for t in (0, end)],
                    rx_connected=[dict(start_us=0, end_us=end)])
        missing = set(rng.sample(range(100, len(tx)), 25)) if settings.csi == 'loss' else set()
        for seq, sent_at in tx:
            if seq in missing:
                continue
            tick = sent_at + rng.randint(-3000, 3000)
            if settings.csi == 'jitter':
                second, within = divmod(seq, 10)
                tick = second * SECOND + (50_000 if second % 2 == 0 else 850_000) + within * 5000
            writer.writerow((tick / SECOND, len(received), tick, REFERENCE_MAC, rng.randint(-51, -47),
                             -95, channel, 1, 0, 1, 2, '0000'))
            received[tick] = seq
        meta['rx_telemetry'] = [
            dict(start_us=i * SECOND, end_us=(i + 1) * SECOND,
                 n_rx_emitted=sum(i * SECOND <= t < (i + 1) * SECOND for t in received),
                 n_filtered=settings.traffic // 10)
            for i in range(DURATION)
        ]
    logger.seek(0)
    trace = import_logger_csi(logger, meta, REFERENCE_MAC)
    # The test transmitter also supplies its counter, keyed by matched RX tick.
    samples = [sample.model_copy(update={'seq': received[sample.ts_us]}) for sample in trace.samples]
    return trace.model_copy(update={'samples': samples, 'sequence_kind': 'tx_contiguous'}).model_dump()


@contextmanager
def collect_uart(url, link, settings, rng, tick_delay):
    request(url, API + '/disconnect', {})
    master, slave = pty.openpty()
    try:
        link.unlink(missing_ok=True)
        link.symlink_to(os.ttyname(slave))
        request(url, API + '/connect', dict(port=str(link), baud=460800))

        def state():
            return request(url, API + '/state')

        wait_for(lambda: state()['diagnostics']['baudrate'] == 460800, 'cổng PTY đã mở')
        boot = rng.getrandbits(64)
        sequence = 0
        counters = dict(rx_callbacks=0, unregistered_frames=0, bytes_written=0)

        def emit(kind, tick, **fields):
            nonlocal sequence
            wire = dict(v=2, node='sniffer', boot_id=f'{boot:016x}', channel=settings.channel,
                        seq=sequence, ts_us=tick * SECOND, type=kind) | fields
            line = (json.dumps(wire, separators=(',', ':')) + '\n').encode()
            os.write(master, line)
            sequence += 1
            counters['bytes_written'] += len(line)

        fixed = dict(mode='DEVICE_ACTIVITY_FIXED_CHANNEL', scan_mode='fixed')

        def heartbeat(tick):
            emit('status', tick, **fixed, **counters, capture_active=True, registered_devices=1,
                 serial_baud=460800, firmware_version='python-pty-v2', invalid_frames=0,
                 off_channel_frames=0, unattributed_frames=0, serial_errors=0,
                 management_frames=0, control_frames=0, data_frames=counters['rx_callbacks'])

        emit('channel', 0, **fixed)
        heartbeat(0)
        def virtual_heartbeat():
            row = state()
            if row['source'] == 'SIMULATION' and row['session_id'] and row['connection'] == 'connected':
                return row
            return None

        ready = wait_for(virtual_heartbeat, 'heartbeat mô phỏng')
        ticks = 10 if settings.disconnect else DURATION
        for tick in range(1, ticks + 1):
            time.sleep(tick_delay)
            active = settings.device and tick <= settings.quiet_after
            count = 12 if active else 0
            counters['rx_callbacks'] += settings.traffic
            counters['unregistered_frames'] += settings.traffic - count
            if settings.heartbeat_loss and 10 < tick < DURATION:
                if tick == 11:
                    wait_for(lambda: 'HEARTBEAT_STALE' in state()['diagnostics']['reasons'],
                             'heartbeat quá hạn', timeout=MAX_HEARTBEAT_S + 3)
                continue
            if active and not (settings.heartbeat_loss and tick == DURATION):
                emit('activity_sample', tick - 1, duration_us=SECOND, source_mac=DEVICE_MAC,
                     attribution='registered', frame_kind='data', n_frames=count, n_bytes=count * 120,
                     tx_frames=count, rx_frames=0, block_ack_frames=0, rssi_max_dbm=rng.randint(-46, -42))
            heartbeat(tick)
        wait_for(lambda: state()['window_end_us'] == ticks * SECOND, f'cửa sổ đến {ticks} s')
        if settings.disconnect:
            os.close(master)
            master = None
            wait_for(lambda: state()['connection'] == 'reconnecting', 'collector phát hiện tháo PTY')
        yield ready['session_id']
    finally:
        try:
            request(url, API + '/disconnect', {})
        except URLError:
            pass
        if master is not None:
            os.close(master)
        os.close(slave)


def check_scenario(name, report, csv_rows):
    activity = report['activity']
    device, = activity['devices']
    quality, reliability = report['quality'], report['current']
    assert report['source'] == activity['source'] == 'SIMULATION'
    assert activity['session_id'] == report['session_id']
    assert (quality['window_start_us'], quality['window_end_us']) == (10 * SECOND, 20 * SECOND)
    if name == 'S01':
        assert device['state'] == 'OBSERVED_ACTIVE' and device['channel_coverage'] == 1
        assert (device['observed_frames'], device['observed_bytes']) == (120, 14_400)
    elif name == 'S02':
        assert device['state'] == 'NO_OBSERVED_ACTIVITY' and device['channel_coverage'] == 1
        assert device['observed_frames'] == 0 and device['rssi_max_dbm'] is None
    elif name == 'S03':
        assert device['state'] == 'UNKNOWN' and 'wrong_channel' in device['reasons']
        assert device['observed_frames'] is None
    elif name == 'S04':
        assert device['state'] == 'UNKNOWN' and 'heartbeat_gap' in device['reasons']
    elif name == 'S05':
        assert quality['quality'] == 'GOOD' and quality['csi_receive_hz'] == 10 and quality['packet_loss_fraction'] == 0
        assert 0 < quality['jitter_ms'] < 10 and quality['n_filtered'] == 40
    elif name == 'S06':
        assert quality['quality'] == reliability['reliability_label'] == 'DEGRADED'
        assert quality['packet_loss_fraction'] == .25 and 'high_packet_loss' in quality['reasons']
    elif name == 'S07':
        assert reliability['evidence_source'] == 'CSI_AND_SNIFFER'
        assert reliability['channel_alignment'] == 'MATCHED' and reliability['channel_coverage'] == 1
    elif name == 'S08':
        assert reliability['evidence_source'] == 'CSI_ONLY' and reliability['channel_alignment'] == 'MISMATCH'
    elif name == 'S09':
        assert reliability['reliability_label'] == 'GOOD'
        assert reliability['quality_indicators']['channel']['frames_per_s'] == 180
    elif name == 'S10':
        assert quality['quality'] == reliability['reliability_label'] == 'UNKNOWN'
        assert quality['csi_receive_hz'] is None and reliability['evidence_source'] == 'INSUFFICIENT_DATA'
    elif name == 'S11':
        assert device['state'] == 'UNKNOWN' and 'sniffer_disconnected' in device['reasons']
        assert quality['quality'] == 'GOOD' and reliability['evidence_source'] == 'CSI_ONLY'
    elif name == 'S12':
        board, rx, combined = (csv_rows[scope][-1] for scope in ('q1', 'q2', 'q3'))
        assert {row['window_end_us'] for row in (board, rx, combined)} == {str(20 * SECOND)}
        assert {row['source'] for rows in csv_rows.values() for row in rows} == {'SIMULATION'}
        assert {row['session_id'] for rows in csv_rows.values() for row in rows} == {report['session_id']}
        assert board['state'] == device['state'] and int(board['observed_frames']) == device['observed_frames']
        assert float(board['observation_time_s']) == device['observation_time_s']
        assert float(board['channel_coverage']) == device['channel_coverage']
        assert rx['receiver_id'] == quality['receiver_id'] and rx['state'] == quality['quality']
        assert float(rx['jitter_ms']) == quality['jitter_ms'] and float(rx['rx_coverage']) == quality['rx_coverage']
        assert combined['state'] == reliability['reliability_label'] and combined['evidence_source'] == reliability['evidence_source']


def run_scenario(url, folder, link, name, settings, seed, tick_delay, *, verify=True):
    rng = random.Random(seed)
    with collect_uart(url, link, settings, rng, tick_delay) as activity_id:
        session = request(url, SESSIONS, dict(mode='SIMULATION', activity_session_id=activity_id,
                                              simulation_trace=rx_trace(settings, rng)))
        report = request(url, f'{SESSIONS}/{session["id"]}/timeline?window_s=10')
    if verify:
        csv_rows = {}
        if name == 'S12':
            for scope in ('q1', 'q2', 'q3'):
                text = request(url, f'{API}/experiments/{scope}/{session["id"]}/export.csv?window_s=10', raw=True)
                csv_rows[scope] = [row for row in csv.DictReader(io.StringIO(text)) if row['kind'] == 'window']
                (folder / f'{session["id"]}-{scope}.csv').write_text(text, encoding='utf-8-sig')
        check_scenario(name, report, csv_rows)
    q1 = report['activity']['devices'][0]['state']
    print(f'{name} {"PASS" if verify else "RUN"} id={session["id"]} '
          f'Q1={q1} Q2={report["quality"]["quality"]} Q3={report["current"]["reliability_label"]} '
          f'{report["current"]["evidence_source"]}', flush=True)


def interactive(run, scenario):
    print('Lệnh: run S01..S12 | device on/off | channel 1..13 | csi-channel 1..13 | '
          'traffic low/high | csi good/loss/jitter/off | disconnect on/off | start | stop', flush=True)
    settings = SCENARIOS[scenario]
    while True:
        try:
            command = input('simulation> ').strip().split()
        except EOFError:
            return
        match command:
            case ['stop'] | ['quit']:
                return
            case ['run', name] if name.upper() in SCENARIOS:
                scenario = name.upper()
                settings = SCENARIOS[scenario]
                run(scenario, settings)
            case ['start']:
                run(scenario, settings, verify=settings == SCENARIOS[scenario])
            case ['channel' | 'csi-channel' as field, value] if value.isdecimal() and 1 <= int(value) <= 13:
                settings = replace(settings, **{field.replace('-', '_'): int(value)})
            case ['device' | 'disconnect' as field, 'on' | 'off' as value]:
                settings = replace(settings, **{field: value == 'on'})
            case ['traffic', 'low' | 'high' as value]:
                settings = replace(settings, traffic=40 if value == 'low' else 180)
            case ['csi', 'good' | 'loss' | 'jitter' | 'off' as value]:
                settings = replace(settings, csi=value)
            case []:
                continue
            case _:
                print('Lệnh không hợp lệ. Dùng các lựa chọn ở trên.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group()
    choices.add_argument('--scenario', choices=SCENARIOS, default='S12')
    choices.add_argument('--all', action='store_true', help='Chạy và kiểm đủ 12 kịch bản')
    parser.add_argument('--seed', type=int, default=20261126)
    parser.add_argument('--port', type=int, default=0, help='0 để tự chọn cổng dashboard')
    parser.add_argument('--tick-delay', type=float, default=.15, help='Giây thực giữa hai tick UART 1 s')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/python-simulation')
    parser.add_argument('--exit-after-run', action='store_true', help='Dừng backend khi kiểm xong')
    args = parser.parse_args()
    if not .02 <= args.tick_delay <= 1:
        parser.error('--tick-delay phải từ 0.02 đến 1 s')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        parser.error('Cần build Dashboard trước bằng npm run build')
    load_dotenv(ROOT / '.env')
    live_root = (ROOT / os.getenv('WIFI_PROBE_DATA_DIR', 'data/runtime')).resolve()
    if args.output.resolve().is_relative_to(live_root):
        parser.error('--output phải nằm ngoài thư mục dữ liệu LIVE')
    try:
        with dashboard(args.output, args.port) as (url, folder, link):
            print(f'Dashboard {url} · Dữ liệu SIMULATION {folder}', flush=True)

            def run(name, settings, *, verify=True):
                run_scenario(url, folder, link, name, settings, args.seed, args.tick_delay, verify=verify)

            failed = False
            for name in SCENARIOS if args.all else (args.scenario,):
                try:
                    run(name, SCENARIOS[name])
                except (AssertionError, RuntimeError, OSError) as error:
                    print(f'{name} FAIL {error}', file=sys.stderr, flush=True)
                    failed = True
            if not args.exit_after_run:
                interactive(run, args.scenario)
            return int(failed)
    except KeyboardInterrupt:
        return 130
    except HTTPError as error:
        print(f'HTTP {error.code} {error.read().decode()}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
