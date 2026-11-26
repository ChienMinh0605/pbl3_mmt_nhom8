"""One serial owner, independent of HTTP/UI cadence. Bounded line buffering."""
import asyncio,json,time,uuid,os
from collections import deque
from itertools import cycle
import serial
from backend.app.device_activity_protocol import parse_activity_line
from backend.app.storage import Store,utc
from backend.app.protocol import PROBE_BAUD_RATES, parse_line
from research.activity_records import Capture, load_records as load_activity_records
from research.dashboard import DashboardBuffer, DashboardConfig
from research.device_activity import MAX_HEARTBEAT_S, WINDOW_US, ActivityMonitor, sanitize_packet
from research.detectors import ALGORITHM_VERSION,Comparison
from research.stream import Stream

BAUD_DETECTION_TIMEOUT_S = 3.0
CONFIG_REPLY_TIMEOUT_S = 1.0
CONFIG_ATTEMPTS = 3

class ProbeService:
    def __init__(self,root,cfg,dashboard_config=None, *, simulation_port=None):
        self.store=Store(root);self.probe_cfg=cfg;self.control=asyncio.Lock()
        self.dashboard_config = dashboard_config or DashboardConfig()
        self.simulation_port = simulation_port
        self.serial=None;self.task=None;self.mode='idle';self.connection='disconnected'
        self.error=None;self.serial_args=None;self.session=None;self.raw=None;self.truth=None;self.current_truth=None
        self.origin=None;self.replay_file=None;self.event_file=None;self.journal_seq=0
        self.counters=dict(valid=0,invalid=0,bytes=0,reconnects=0)
        self.activity_source = None
        self.activity = ActivityMonitor()
        self.activity_bindings = {}
        self.activity_secret = None
        self.activity_capture = None
        self.activity_capture_error = None
        self.activity_replay_id = None
        self.activity_playback_source = None
        self.activity_session_id = None
        self.runtime_board = None
        self.runtime_applied = None
        self.runtime_attempt = None
        self.runtime_wait = None
        self.runtime_task = None
        self.runtime_error = None
        self.activity_history = deque(maxlen=30 * 60 * 1_000_000 // WINDOW_US)
        self.reset_serial_diagnostics()
        self.reset_stream()

    def reset_serial_diagnostics(self):
        self.serial_protocol = None
        self.serial_baud = None
        self.serial_status_at = None
        self.last_serial_received_at = None
        self.activity_records_received = 0
        self.serial_parsing_errors = 0
    def reset_stream(self):
        self.stream=Stream(self.probe_cfg);self.clock=time.monotonic()
        self.dashboard = DashboardBuffer(self.dashboard_config)
        self.timeline_origin=self.origin if self.session else self.clock
        self.status=None;self.probe_history=[];self.channels=[];self.journal_seq=0
    def apply_rssi(self,cfg):
        """Keep the radio/heartbeat and raw audit, restart inference under one threshold."""
        old=self.probe_cfg.rssi_min
        self.stream.advance(self.alg_now())
        self.probe_cfg=cfg;self.stream.cfg=cfg;self.stream.engine=Comparison(cfg)
        if self.status:self.stream.engine.excluded.add(self.status['own_mac'])
        self.probe_history=[]
        self.stream.event('rssi_filter_changed',self.alg_now(),previous_rssi_min=old,rssi_min=cfg.rssi_min)
        self.dashboard = DashboardBuffer(self.dashboard_config)
        t = self.alg_now()
        if self.status and self.stream.valid(t):
            self.dashboard.add(self.stream.heartbeat, self.status)
    @property
    def engine(self):return self.stream.engine
    def now(self):return self.clock if self.mode in ('replay','synthetic') else time.monotonic()
    def alg_now(self):
        now=self.now();return now-self.timeline_origin if self.mode=='serial' else now
    def _journal(self):
        for ev in self.stream.events:
            if ev['event_seq']<=self.journal_seq:continue
            if self.event_file:self.event_file.write(json.dumps(ev,ensure_ascii=False)+'\n')
            self.journal_seq=ev['event_seq']
    def control_event(self,kind,now=None):
        now=self.now() if now is None else now
        t=now-self.timeline_origin if self.mode=='serial' else now
        if self.activity_source == 'serial':
            if kind == 'serial_disconnected':
                self.reset_runtime_connection()
            self.activity_control(kind, now)
            self.record_activity(now, kind=kind)
            return
        packet = dict(type='control',kind=kind)
        self.dashboard.add(t, packet)
        self.stream.feed(packet,t)
        if self.raw:
            self.raw.write(json.dumps(dict(control=dict(kind=kind),host_elapsed_s=now-self.origin,host_time=utc(),source='serial'))+'\n')
        self._journal()
    def ingest(self,line,now=None, *, detecting_baud=None):
        now=time.monotonic() if now is None else now
        if detecting_baud is not None:
            packet = self.detect_serial_status(line, detecting_baud, now)
            if packet is None:
                return
        else:
            parser = parse_activity_line if self.activity_source == 'serial' else parse_line
            try:
                packet = parser(line)
            except ValueError:
                self.counters['bytes'] += len(line)
                self.invalid_serial_line(now)
                return
        self.counters['bytes'] += len(line)
        if packet['type'] == 'config_reply':
            self.accept_runtime_reply(packet, now)
            return
        self.counters['valid']+=1;self.clock=now
        if self.mode == 'serial':
            self.last_serial_received_at = utc()
            if packet['type'] == 'status':
                self.serial_protocol = packet['v']
                self.serial_status_at = now
        if packet['v'] == 2:
            self.ingest_activity(packet, now)
        else:
            self.ingest_probe(packet, now)

    def detect_serial_status(self, line, baud, now):
        try:
            packet = parse_activity_line(line)
        except ValueError:
            try:
                packet = parse_line(line)
            except ValueError:
                return None
        if packet['type'] != 'status' or packet['serial_baud'] != baud:
            return None
        version = packet['v']
        if self.simulation_port and version != 2:
            return None
        if (version == 1 and self.activity_capture) or (version == 2 and self.session):
            return None
        if version == 2 and self.activity_source != 'serial':
            bindings = self.store.activity_bindings()
            self.activity_secret = self.store.activity_key() if bindings else None
            self.activity_bindings = bindings
            self.activity = ActivityMonitor(self.store.registered_devices())
            self.activity_source = 'serial'
            self.activity_session_id = uuid.uuid4().hex
        elif version == 1:
            self.activity_source = None
        self.connection = 'connected'
        self.control_event('serial_connected', now)
        return packet

    def ingest_probe(self,p,now):
        t=now-self.timeline_origin if self.mode=='serial' else now
        if self.raw:
            self.raw.write(json.dumps(dict(packet=p,host_time=utc(),host_elapsed_s=now-self.origin,source='serial'))+'\n')
            self.session['records']+=1
        self.dashboard.add(t, p)
        self.stream.feed(p,t);self._journal()
        if p['type']=='status':self.status=p
        if p['type'] in ('status','channel'):
            self.channels.append(dict(t=t,channel=p['channel']));self.channels=self.channels[-100:]

    def activity_control(self, kind, stamp, *, devices=None):
        self.activity.control(kind, stamp, devices=devices)
        self.remember_activity_windows()

    def invalid_activity_line(self, now):
        self.activity_control('invalid_line', now)
        self.record_activity(now, kind='invalid_line')

    def invalid_serial_line(self, now):
        self.counters['invalid'] += 1
        if self.mode == 'serial':
            self.serial_parsing_errors += 1
        if self.activity_source == 'serial':
            self.invalid_activity_line(now)

    def ingest_activity(self, packet, now):
        if self.activity_output_source() == 'LIVE':
            if packet['type'] == 'status':
                self.observe_runtime_status(packet, now)
            if packet.get('registry_revision') is not None or (self.runtime_board or {}).get('runtime_config'):
                if self.runtime_applied is None or self.runtime_key(packet) != self.runtime_applied[0]:
                    return
        if packet['type'] == 'activity_sample':
            self.activity_records_received += 1
        packet = sanitize_packet(packet, self.activity_bindings, self.activity_secret)
        self.feed_activity(packet, now)
        self.record_activity(now, packet=packet)

    @staticmethod
    def runtime_key(packet):
        return packet['boot_id'], packet.get('registry_revision'), packet['channel']

    def reset_runtime_connection(self):
        self.runtime_board = None
        self.runtime_applied = None
        self.runtime_attempt = None
        self.runtime_error = None
        if self.runtime_wait and not self.runtime_wait['future'].done():
            self.runtime_wait['future'].set_result('offline')

    def observe_runtime_status(self, packet, now):
        previous = self.runtime_board
        self.runtime_board = packet
        if not packet.get('runtime_config'):
            if previous and previous.get('runtime_config'):
                self.reset_runtime_connection()
                self.runtime_board = packet
                self.reload_activity_registry()
            return
        if self.store.activity_channel() is None:
            self.store.set_activity_channel(packet['channel'])
        key = self.runtime_key(packet)
        if self.runtime_applied and key == self.runtime_applied[0]:
            return
        if previous and previous['boot_id'] != packet['boot_id'] and self.runtime_wait:
            future = self.runtime_wait['future']
            if not future.done():
                future.set_result('rebooted')
        self.begin_registry_change(now)
        if (not self.runtime_wait and key != self.runtime_attempt
                and (self.runtime_task is None or self.runtime_task.done())):
            self.runtime_task = asyncio.create_task(self.sync_after_status())

    def begin_registry_change(self, now):
        self.runtime_applied = None
        if not self.activity.registry_pending:
            self.activity_control('registry_pending', now)
            self.record_activity(now, kind='registry_pending')

    def reload_activity_registry(self):
        self.activity_bindings = self.store.activity_bindings()
        self.activity_secret = self.store.activity_key() if self.activity_bindings else None
        return self.store.registered_devices()

    def accept_runtime_reply(self, reply, now):
        pending = self.runtime_wait
        if not pending or pending['future'].done() or reply['request_id'] != pending['id']:
            return
        boot, revision, _ = pending['board']
        if reply['boot_id'] != boot or (self.runtime_board or {}).get('boot_id') != boot:
            return
        if not reply['ok']:
            pending['future'].set_result(reply['error'])
            return
        if (reply['channel'] != pending['channel'] or reply['registered_devices'] != len(pending['macs'])
                or reply.get('macs') is None or tuple(reply['macs']) != pending['macs']
                or reply['registry_revision'] not in (revision, (revision + 1) & 0xffffffff)):
            pending['future'].set_result('unexpected_ack')
            return
        try:
            devices = self.reload_activity_registry()
        except (OSError, ValueError):
            pending['future'].set_result('registry_key_unavailable')
            return
        key = self.runtime_key(reply)
        self.runtime_board = self.runtime_board | {
            name: reply[name] for name in ('channel', 'registered_devices', 'registry_revision')
        }
        self.runtime_applied = (key, pending['macs'])
        self.activity_control('registry_applied', now, devices=devices)
        self.record_activity(now, kind='registry_applied', devices=devices, registry_revision=key[1])
        pending['future'].set_result(None)

    def runtime_online(self):
        return (self.activity_output_source() == 'LIVE' and self.connection == 'connected'
                and self.serial_status_at is not None and self.now() - self.serial_status_at <= MAX_HEARTBEAT_S)

    def runtime_configuration(self):
        board = self.runtime_board or {}
        channel = self.store.activity_channel()
        supported = bool(board.get('runtime_config'))
        online = self.runtime_online()
        applied = self.runtime_applied if online else None
        if not online or not supported:
            state = 'OFFLINE'
        elif applied:
            state = 'SYNCED'
        elif self.runtime_error:
            state = 'SYNC_FAILED'
        else:
            state = 'PENDING'
        return dict(state=state, supported=supported if online else None, desired_channel=channel,
                    applied_channel=board.get('channel') if online else None,
                    registry_revision=board.get('registry_revision') if online else None,
                    firmware_count=board.get('registered_devices') if online else None,
                    channel_min=board.get('channel_min'), channel_max=board.get('channel_max'),
                    error=self.runtime_error if supported and online else None)

    async def sync_after_status(self):
        async with self.control:
            if self.runtime_board and self.runtime_key(self.runtime_board) != self.runtime_attempt:
                await self.sync_runtime()

    async def sync_runtime(self):
        board = self.runtime_board or {}
        if self.activity_output_source() != 'LIVE' or not board.get('runtime_config'):
            return
        if not self.runtime_online() or not self.serial:
            self.runtime_attempt = None
            self.begin_registry_change(self.now())
            return
        channel = self.store.activity_channel()
        macs = tuple(sorted(row['wifi_mac'] for row in self.store.registered_devices(include_mac=True)
                            if row['channel'] == channel and row['wifi_mac']))
        self.runtime_attempt = self.runtime_key(board)
        self.runtime_error = None
        self.begin_registry_change(self.now())
        if not board['channel_min'] <= channel <= board['channel_max']:
            self.runtime_error = 'invalid_channel'
            return
        if len(macs) > 16:
            self.runtime_error = 'invalid_registry'
            return
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        pending = dict(id=request_id, future=future, channel=channel, macs=macs, board=self.runtime_attempt)
        self.runtime_wait = pending
        command = (json.dumps(dict(v=2, type='config_command', request_id=request_id, command='set_registry',
                                   channel=channel, macs=macs), separators=(',', ':')) + '\n').encode()
        connection = self.serial
        try:
            for _ in range(CONFIG_ATTEMPTS):
                if connection is not self.serial or self.connection != 'connected':
                    self.runtime_error = 'offline'
                    break
                try:
                    if not future.done() and await asyncio.to_thread(connection.write, command) != len(command):
                        self.runtime_error = 'write_failed'
                        break
                    self.runtime_error = await asyncio.wait_for(asyncio.shield(future), CONFIG_REPLY_TIMEOUT_S)
                    break
                except TimeoutError:
                    self.runtime_error = 'ack_timeout'
                except OSError:
                    self.runtime_error = 'write_failed'
                    break
        finally:
            # A new revision can become visible even when every ACK was lost.
            # Keep this failure for the boot; another identical heartbeat must not retry forever.
            if self.runtime_board and self.runtime_board['boot_id'] == pending['board'][0]:
                self.runtime_attempt = self.runtime_key(self.runtime_board)
            self.runtime_wait = None
            if not future.done():
                future.cancel()

    def feed_activity(self, packet, now):
        self.activity.feed(packet, now)
        self.remember_activity_windows()

    def remember_activity_windows(self):
        # A source/session change clears the buffer before its clock starts again.
        for window in self.activity.completed:
            if not self.activity_history or self.activity_history[-1]['window_end_us'] < window['window_end_us']:
                self.activity_history.append(window)

    def activity_output_source(self):
        if self.activity_source == 'replay':
            return self.activity_playback_source
        if self.simulation_port:
            return 'SIMULATION'
        return 'LIVE' if self.activity_source == 'serial' else None

    def activity_snapshot(self):
        live = self.mode == 'serial'
        monitor = self.activity if self.activity_source else ActivityMonitor(self.store.registered_devices())
        now = self.now()
        connection = self.connection if live or self.activity_source else 'disconnected'
        result = monitor.snapshot(now, connection)
        status = (self.runtime_board or monitor.status) if self.serial_protocol == 2 else self.status if live else None
        if live and (self.runtime_board or {}).get('runtime_config') and (
            self.runtime_applied is None or not self.runtime_online()
        ):
            issues = set(result['issues']) | {'registry_not_synced'}
            result['devices'] = [monitor.unavailable(device, issues) for device in self.store.registered_devices()]
        heartbeat_at = self.serial_status_at
        heartbeat_age = max(0, now - heartbeat_at) if heartbeat_at is not None else None
        firmware_mode = None
        reasons = []
        if self.activity_source == 'replay':
            firmware_mode = (monitor.status or {}).get('mode')
        elif self.connection in ('reconnecting', 'disconnected') or not live:
            reasons.append('SNIFFER_DISCONNECTED')
        elif self.serial_protocol == 1:
            firmware_mode = 'PROBE_BASELINE'
            reasons.append('FIRMWARE_MODE_UNSUPPORTED')
            for device in result['devices']:
                device['reasons'] = ['firmware_mode_unsupported']
        elif self.serial_protocol != 2:
            reasons.append('AWAITING_ACTIVITY_HEARTBEAT')
        else:
            firmware_mode = (status or {}).get('mode', 'DEVICE_ACTIVITY_FIXED_CHANNEL')
            if not self.activity_records_received:
                reasons.append('NO_ACTIVITY_RECORDS')
            if any('wrong_channel' in row['reasons'] for row in result['devices']):
                reasons.append('CHANNEL_MISMATCH')
            if any('firmware_binding_unverified' in row['reasons'] and 'wrong_channel' not in row['reasons']
                   for row in result['devices']):
                reasons.append('NO_REGISTERED_DEVICE_MATCH')
        if heartbeat_age is not None and heartbeat_age > (MAX_HEARTBEAT_S if self.serial_protocol == 2 else self.probe_cfg.heartbeat_s):
            reasons.append('HEARTBEAT_STALE')

        return result | dict(
            source=self.activity_output_source(),
            session_id=self.activity_session_id,
            replay_capture_id=self.activity_replay_id,
            capture=self.activity_capture.metadata if self.activity_capture else None,
            capture_error=self.activity_capture_error,
            diagnostics=dict(connection=connection,
                             port=self.serial_args[0] if live and self.serial_args else None, baudrate=self.serial_baud,
                             requested_baudrate=self.serial_args[1] if live and self.serial_args else None,
                             firmware_version=(status or {}).get('firmware_version'), capture_mode=firmware_mode,
                             scan_mode=(status or {}).get('scan_mode'),
                             queue_drops=(status or {}).get('queue_drops', (status or {}).get('probe_dropped')),
                             channel=(status or {}).get('channel', result['channel']),
                             heartbeat_age_s=heartbeat_age, registered_devices=(status or {}).get('registered_devices'),
                             management_frames=(status or {}).get('management_frames'),
                             data_frames=(status or {}).get('data_frames'), control_frames=(status or {}).get('control_frames'),
                             unattributed_frames=(status or {}).get('unattributed_frames'),
                             unregistered_frames=(status or {}).get('unregistered_frames'),
                             invalid_frames=(status or {}).get('invalid_frames'),
                             off_channel_frames=(status or {}).get('off_channel_frames'),
                             rx_callbacks=(status or {}).get('rx_callbacks'),
                             bytes_written=(status or {}).get('bytes_written'),
                             activity_records_received=self.activity_records_received if live else None,
                             parsing_errors=self.serial_parsing_errors if live else None,
                             serial_errors=(status or {}).get('serial_errors'),
                             last_received_at=self.last_serial_received_at, error=self.error if live else None,
                             reasons=reasons))

    @property
    def activity_root(self):
        return self.store.root / 'device-activity'

    def start_activity_capture(self, **experiment):
        now = self.now()
        if (self.activity_output_source() != 'LIVE' or self.connection != 'connected' or self.activity_capture or
                self.activity.status_at is None or now - self.activity.status_at > MAX_HEARTBEAT_S):
            raise ValueError('Cần nguồn serial activity có heartbeat hợp lệ và chưa ghi phiên')
        if (self.runtime_board or {}).get('runtime_config') and self.runtime_applied is None:
            raise ValueError('Cần đồng bộ registry với firmware trước khi ghi')
        revision = self.runtime_applied[0][1] if self.runtime_applied else None
        self.activity_capture = Capture(self.activity_root, self.activity.devices.values(), now, revision, **experiment)
        self.activity.reset()
        self.activity_session_id = self.activity_capture.metadata['id']
        self.activity_history.clear()
        self.activity_capture_error = None
        return self.activity_capture.metadata

    def record_activity(self, now, **row):
        if self.activity_capture is None:
            return
        try:
            self.activity_capture.append(now, **row)
        except OSError:
            capture, self.activity_capture = self.activity_capture, None
            self.activity_capture_error = 'capture_write_failed'
            try:
                capture.raw.close()
            except OSError:
                pass

    def stop_activity_capture(self):
        if self.activity_capture is None:
            raise ValueError('Chưa có phiên activity đang ghi')
        capture, self.activity_capture = self.activity_capture, None
        try:
            stamp = self.now()
            self.activity_control('session_stopped', stamp)
            return capture.finish(stamp)
        except OSError:
            self.activity_capture_error = 'capture_write_failed'
            raise
    def snapshot(self):
        t=self.alg_now();state=self.stream.snapshot(t);self._journal()
        valid=self.connection=='connected' and state['valid'];result=state['result'] if valid else None
        if result and (not self.probe_history or t-self.probe_history[-1]['t']>=1):
            self.probe_history.append(dict(t=t,unique=result['unique_count'],timeout=result['timeout_count'],sherlock=result['sherlock']['count']))
            self.probe_history=self.probe_history[-180:]
        return dict(mode=self.mode,connection=self.connection,error=self.error,valid=valid,heartbeat_age_s=state['heartbeat_age_s'],
                    capture_mode={1: 'PROBE_BASELINE', 2: 'DEVICE_ACTIVITY_FIXED_CHANNEL'}.get(self.serial_protocol),
                    dashboard_source_id=self.dashboard.source_id,
                    result=result,firmware=self.status,counters=self.counters.copy(),history=self.probe_history,
                    config=self.stream.cfg.model_dump(),session=self.session,current_truth=self.current_truth,channels=self.channels[-20:],
                    algorithm_version=ALGORITHM_VERSION,events=state['events'],quality=state['quality'],recent_sources=state['recent_sources'],
                    raw_mac_count=state['raw_mac_count'],active_mac_count=state['active_mac_count'],expired_mac_count=state['expired_mac_count'],
                    channel_observation_s=state['channel_observation_s'],
                    semantics='Số nguồn MAC duy trì xác nhận quan sát; không kết luận thiết bị đã rời')
    async def dashboard_snapshot(self):
        while True:
            dashboard = self.dashboard
            t = self.alg_now()
            cfg = self.stream.cfg
            state = dict(mode=self.mode, connection=self.connection,
                         valid=self.connection == 'connected' and self.stream.valid(t),
                         config=cfg.model_dump(), raw_mac_count=self.stream.probe_records.mac_count(),
                         active_mac_count=sum(t - row.last_seen_s <= cfg.mac_expiry_s for row in self.stream.audit.values()))
            report = await dashboard.snapshot(dashboard.capture(t, state))
            if dashboard is self.dashboard and self.connection == state['connection']:
                return report
    def diagnostics(self,mac):
        result=self.stream.diagnostics(mac,self.alg_now());self._journal();return result
    def marker(self,kind,mac=None,notes=''):
        if not self.session or self.mode!='serial':raise ValueError('Bắt đầu phiên serial trước khi đánh dấu')
        row=dict(t_s=time.monotonic()-self.origin,kind=kind,mac=mac,notes=notes,host_time=utc())
        with (self.folder/'markers.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        self.store.event('experiment_marker',row);return row
    async def connect(self,port,baud, *, detect_protocol=False):
        if self.mode == 'serial' and self.serial_args and self.serial_args[0] == port and (
            (baud == self.serial_args[1] and (not detect_protocol or self.detect_protocol or self.serial_protocol)) or
            (baud is None and not detect_protocol and self.serial_protocol)
        ):
            return
        await self.stop();self.mode='serial';self.serial_args=(port,baud);self.connection='connecting';self.error=None
        self.detect_protocol = detect_protocol or baud is None
        self.activity_capture_error = None
        self.task=asyncio.create_task(self.serial_loop())
    async def serial_loop(self):
        port, requested_baud = self.serial_args
        baud_rates = cycle(PROBE_BAUD_RATES) if requested_baud is None else None
        baud = next(baud_rates) if baud_rates is not None else requested_baud
        fragment = b''
        discard = False
        baud_deadline = 0.0
        try:
            while True:
                try:
                    if self.serial is None:
                        self.serial=serial.Serial(port,baud,timeout=.1,write_timeout=.5,exclusive=True if os.name!='nt' else None)
                        self.serial_baud = baud
                        self.error = None
                        fragment, discard = b'', False
                        if not self.detect_protocol:
                            self.connection = 'connected'
                            self.control_event('serial_connected')
                        else:
                            self.connection = 'connecting'
                            baud_deadline = time.monotonic() + BAUD_DETECTION_TIMEOUT_S
                    chunk=await asyncio.to_thread(self.serial.read,4096);fragment+=chunk
                    while b'\n' in fragment:
                        line,fragment=fragment.split(b'\n',1)
                        if line and not discard:
                            self.ingest(line, detecting_baud=baud if self.connection == 'connecting' else None)
                        discard=False
                    if len(fragment)>16000:
                        fragment=b''
                        discard=True
                        if self.connection != 'connecting':self.invalid_serial_line(self.now())
                    if baud_rates is not None and self.connection == 'connecting' and time.monotonic() >= baud_deadline:
                        self.serial.close()
                        self.serial = None
                        baud = next(baud_rates)
                except (serial.SerialException,OSError,ValueError) as e:
                    self.error=str(e);self.connection='reconnecting';self.control_event('serial_disconnected')
                    self.counters['reconnects']+=1
                    if self.serial:self.serial.close();self.serial=None
                    await asyncio.sleep(1)
        finally:
            if self.serial:self.serial.close();self.serial=None
    async def stop(self):
        if self.runtime_task:
            self.runtime_task.cancel()
            try:
                await self.runtime_task
            except asyncio.CancelledError:
                pass
            self.runtime_task = None
        self.reset_runtime_connection()
        if self.serial:
            try:self.serial.cancel_read()
            except (AttributeError,OSError):pass
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
            self.task=None
        if self.serial:self.serial.close();self.serial=None
        if self.session:self.stop_session()
        if self.activity_capture:
            try:
                self.stop_activity_capture()
            except OSError:
                pass  # The capture stays unfinished and cannot be replayed.
        self.activity_source = None
        self.activity_replay_id = None
        self.activity_playback_source = None
        self.activity_session_id = None
        self.activity_history.clear()
        self.activity = ActivityMonitor()
        self.activity_bindings = {}
        self.activity_secret = None
        self.serial_args = None
        self.reset_serial_diagnostics()
        self.connection='disconnected';self.mode='idle';self.reset_stream()

    async def replay_activity(self, path, speed, devices, capture_id=None, *, source='REPLAY'):
        await self.stop()
        self.mode, self.connection, self.activity_source = 'replay', 'connected', 'replay'
        self.error, self.activity_capture_error, self.clock = None, None, 0.
        self.activity = ActivityMonitor(devices)
        self.activity_replay_id = capture_id
        self.activity_playback_source = source
        self.activity_session_id = capture_id or uuid.uuid4().hex
        self.task = asyncio.create_task(self.activity_replay_loop(path, speed))

    async def timed_records(self, records, speed):
        prev = 0.
        for t, packet in records:
            gap = max(0, t - prev)
            while gap > 1:
                await asyncio.sleep(1 / speed)
                prev += 1
                gap -= 1
                self.clock = prev
            await asyncio.sleep(gap / speed)
            prev = self.clock = t
            yield t, packet

    async def activity_replay_loop(self, path, speed):
        try:
            async for stamp, packet in self.timed_records(load_activity_records(path), speed):
                if packet['type'] == 'control':
                    kind = packet['kind']
                    self.activity_control(kind, stamp, devices=packet.get('devices'))
                    if kind in ('serial_connected', 'serial_disconnected'):
                        self.connection = 'connected' if kind == 'serial_connected' else 'reconnecting'
                else:
                    self.feed_activity(packet, stamp)
            self.connection = 'finished'
        except asyncio.CancelledError:
            raise
        except (ValueError, OSError, KeyError, TypeError):
            self.error = 'Invalid device activity replay'
            self.connection = 'error'
    async def replay(self,path,speed,synthetic,cfg,setup_id=None):
        await self.stop();self.mode='synthetic' if synthetic else 'replay';self.connection='connected';self.error=None
        self.stream=Stream(cfg);self.clock=0.
        self.dashboard.setup_id = None if synthetic else setup_id
        self.replay_file=str(path);self.task=asyncio.create_task(self.replay_loop(path,speed))
    async def replay_loop(self,path,speed):
        from research.evaluate import load_records
        try:
            async for t,p in self.timed_records(load_records(path), speed):
                if p['type']=='control':
                    self.clock=t;self.dashboard.add(t,p);self.stream.feed(p,t);self._journal()
                else:self.ingest(json.dumps(p),t)
            self.connection='finished'
        except asyncio.CancelledError:raise
        except Exception as e:self.error=str(e);self.connection='error'
    def start_session(self,meta):
        if self.mode!='serial' or not self.snapshot()['valid']:raise ValueError('Cần sniffer serial và heartbeat hợp lệ')
        if self.session:raise ValueError('Đang có phiên thu')
        self.origin=time.monotonic();self.timeline_origin=self.origin;self.probe_history=[]
        self.stream=Stream(self.probe_cfg);self.journal_seq=0
        self.dashboard = DashboardBuffer(self.dashboard_config)
        if self.status:
            self.stream.feed(self.status,0.)
            self.dashboard.add(0.,self.status)
        sid=uuid.uuid4().hex;self.folder=self.store.root/'experiments'/sid;self.folder.mkdir(parents=True)
        self.session=dict(id=sid,started_at=utc(),ended_at=None,records=0,synthetic=False,algorithm_version=ALGORITHM_VERSION,config=self.probe_cfg.model_dump(),firmware=self.status,**meta)
        if self.dashboard.setup_id is not None:
            self.session['dashboard_setup_id'] = self.dashboard.setup_id
        self.event_file=(self.folder/'algorithm-events.jsonl').open('w',buffering=1)
        self.raw=(self.folder/'raw.jsonl').open('w',buffering=1);self.truth=(self.folder/'truth.jsonl').open('w',buffering=1)
        self.current_truth=dict(t_s=0.,host_time=utc(),device_count=meta['device_count'],people_count=meta.get('people_count'),notes=meta.get('notes',''))
        self.truth.write(json.dumps(self.current_truth,ensure_ascii=False)+'\n')
        if self.status:
            self.raw.write(json.dumps(dict(packet=self.status,host_elapsed_s=0,host_time=utc(),source='serial'))+'\n');self.session['records']+=1
        self._save_meta();return self.session
    def _save_meta(self):
        (self.folder/'metadata.json').write_text(json.dumps(self.session,ensure_ascii=False,indent=2));self.store.save(self.session)
    def add_truth(self,device_count,people_count=None,notes=''):
        if not self.truth:raise ValueError('Chưa bắt đầu phiên')
        row=dict(t_s=time.monotonic()-self.origin,host_time=utc(),device_count=device_count,people_count=people_count,notes=notes)
        self.truth.write(json.dumps(row,ensure_ascii=False)+'\n');self.store.event('ground_truth',row);self.current_truth=row;return row
    def stop_session(self):
        if not self.session:raise ValueError('Không có phiên')
        # Host control record, not a fabricated board heartbeat.
        self.control_event('session_stopped')
        self.raw.close();self.truth.close();self.event_file.close();self.raw=None;self.truth=None;self.event_file=None
        self.session['ended_at']=utc();self.session['duration_s']=time.monotonic()-self.origin
        self._save_meta();out=self.session;self.session=None;self.origin=None;self.current_truth=None;return out
