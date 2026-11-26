"""Local registry and capture endpoints for Registered Device Activity Monitor."""

import asyncio
import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from serial.tools import list_ports

from backend.app.api.private_input import PrivateInputRoute
from backend.app.protocol import mac_valid
from backend.app.storage import utc
from research.activity_records import read_metadata, recorded_activity_windows, simulated_capture
from research.device_activity import WINDOW_US, frame_analysis, mac_digest, register_device


router = APIRouter(prefix='/api/device-csi', tags=['Registered device activity'], route_class=PrivateInputRoute)
DeviceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
MAC_IN_NAME = re.compile(r'(?i)(?<![0-9a-f])(?:[0-9a-f]{12}|(?:[0-9a-f]{2}(?:\s*[:-]\s*|\s+)){5}[0-9a-f]{2})(?![0-9a-f])')


class NameChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: DeviceName

    @field_validator('name')
    @classmethod
    def omit_mac(cls, value):
        if MAC_IN_NAME.search(value):
            raise ValueError('Tên thiết bị cần dùng nhãn riêng thay cho MAC')
        return value


class Registration(NameChange):
    mac: SecretStr
    channel: Annotated[int, Field(ge=1, le=13, strict=True)]
    consent: Literal[True]

    @field_validator('consent', mode='before')
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError('Cần xác nhận đã có sự đồng ý')
        return value


class Connection(BaseModel):
    # Keep the existing qualified name used by the OpenAPI component.
    __module__ = 'backend.app.device_activity_api'

    model_config = ConfigDict(extra='forbid')
    port: Annotated[str, Field(min_length=1, max_length=128)]
    baud: Literal[460800, 921600] | None = None


class Replay(BaseModel):
    # Keep the existing qualified name used by the OpenAPI component.
    __module__ = 'backend.app.device_activity_api'

    model_config = ConfigDict(extra='forbid')
    capture_id: UUID
    speed: Annotated[float, Field(ge=0.25, le=100)] = 1.0


class ChannelChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    channel: Annotated[int, Field(ge=1, le=13, strict=True)]


def registry_mac(body):
    mac = body.mac.get_secret_value().strip().lower()
    if not mac_valid(mac) or mac == '00:00:00:00:00:00' or int(mac[:2], 16) & 1:
        raise HTTPException(422, 'Cần MAC unicast hợp lệ của thiết bị')
    return mac


def require_registry_editable(service):
    if service.activity_source == 'replay' or (service.mode == 'serial' and service.connection == 'connected'
          and not (service.runtime_board or {}).get('runtime_config')):
        raise HTTPException(409, 'Firmware hiện tại không hỗ trợ cấu hình runtime. Ngắt nguồn để lưu cấu hình cục bộ.')


def mark_sync_response(response, configuration):
    response.headers['X-Registry-Sync'] = configuration['state']
    if configuration['state'] != 'SYNCED':
        # Desired state is saved. This is not an acknowledgement from the board.
        response.status_code = 202


@router.get('/registry')
async def registry(request: Request, details: bool = False):
    service = request.app.state.probe_service
    result = {'devices': service.store.registered_devices(include_mac=details)}
    if details:
        result['configuration'] = service.runtime_configuration()
    return result


@router.post('/registry', status_code=201)
async def register(request: Request, response: Response, body: Registration):
    service = request.app.state.probe_service
    mac = registry_mac(body)
    async with service.control:
        require_registry_editable(service)
        try:
            service.store.activity_key()
        except (OSError, ValueError) as error:
            raise HTTPException(503, 'Không thể mở khóa HMAC của registry') from error
        try:
            device = register_device(service.store, body.name, mac, body.channel)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if device is None:
            raise HTTPException(409, 'MAC đã được đăng ký trên kênh này')
        await service.sync_runtime()
        mark_sync_response(response, service.runtime_configuration())
        return device


@router.patch('/registry/{device_id}')
async def update_registration(request: Request, response: Response, device_id: UUID, body: Registration | NameChange):
    service = request.app.state.probe_service
    full_update = isinstance(body, Registration)
    async with service.control:
        if full_update:
            require_registry_editable(service)
        fields = {}
        if full_update:
            mac = registry_mac(body)
            try:
                digest = mac_digest(service.store.activity_key(), mac, body.channel)
            except (OSError, ValueError) as error:
                raise HTTPException(503, 'Không thể mở khóa HMAC của registry') from error
            fields.update(channel=body.channel, mac=mac, digest=digest)
        try:
            exists = service.store.update_device(device_id.hex, body.name, **fields)
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, 'MAC đã được đăng ký trên kênh này') from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if not exists:
            raise HTTPException(404, 'Thiết bị không tồn tại')
        if full_update or (service.runtime_board or {}).get('runtime_config'):
            await service.sync_runtime()
            mark_sync_response(response, service.runtime_configuration())
        elif service.activity_source == 'serial' and device_id.hex in service.activity.devices:
            service.activity.devices[device_id.hex]['name'] = body.name
        return next(device for device in service.store.registered_devices() if device['id'] == device_id.hex)


@router.delete('/registry/{device_id}')
async def delete_registration(request: Request, response: Response, device_id: UUID):
    service = request.app.state.probe_service
    async with service.control:
        require_registry_editable(service)
        if not service.store.delete_device(device_id.hex):
            raise HTTPException(404, 'Thiết bị không tồn tại')
        await service.sync_runtime()
        configuration = service.runtime_configuration()
        mark_sync_response(response, configuration)
        return configuration


@router.put('/registry/channel')
async def configure_channel(request: Request, response: Response, body: ChannelChange):
    service = request.app.state.probe_service
    async with service.control:
        require_registry_editable(service)
        board = service.runtime_board or {}
        if board.get('runtime_config') and not board['channel_min'] <= body.channel <= board['channel_max']:
            raise HTTPException(422, 'Kênh thu nằm ngoài dải cho phép của firmware')
        service.store.set_activity_channel(body.channel)
        await service.sync_runtime()
        configuration = service.runtime_configuration()
        mark_sync_response(response, configuration)
        return configuration


@router.post('/registry/sync')
async def resync_registry(request: Request, response: Response):
    service = request.app.state.probe_service
    async with service.control:
        await service.sync_runtime()
        configuration = service.runtime_configuration()
        mark_sync_response(response, configuration)
        return configuration


def activity_overview(snapshot, synced):
    devices = snapshot['devices']
    states = ('OBSERVED_ACTIVE', 'NO_OBSERVED_ACTIVITY', 'UNKNOWN')
    return dict(registered=len(devices), synced=synced,
                states={state: sum(row['state'] == state for row in devices) for state in states})


def saved_simulation(service, key):
    # Compatibility for Q1 windows written by previous simulation tooling.
    session = service.store.reliability_session(key)
    if not session or session['mode'] not in ('SIMULATION', 'DEMO'):
        return None, []
    return session, service.store.reliability_batches(key, limit=-1)


@router.get('/state')
async def snapshot(request: Request, simulation_id: UUID | None = None):
    service = request.app.state.probe_service
    state = service.activity_snapshot()
    config = service.runtime_configuration()
    synced = config['firmware_count'] if config['state'] == 'SYNCED' else None
    if simulation_id and (state['source'], state['session_id']) != ('SIMULATION', simulation_id.hex):
        key = simulation_id.hex
        folder = service.activity_root / key
        meta, windows = None, []
        if (folder / 'metadata.json').is_file():
            meta = read_metadata(folder)
            if meta['source'] == 'SIMULATION':
                windows = await asyncio.to_thread(lambda: list(recorded_activity_windows(folder / 'raw.jsonl', meta['devices'])))
        else:
            meta, batches = saved_simulation(service, key)
            windows = [current for batch in batches if (current := batch.get('activity_current'))]
            if not windows:
                windows = [window for batch in batches for window in batch.get('activity_windows', [])]
        if not windows:
            raise HTTPException(404, 'Không tìm thấy phiên mô phỏng Q1')
        state = windows[-1] | dict(source='SIMULATION', session_id=key, capture=None, capture_error=None)
    if state['source'] != 'LIVE':
        synced = None
    return state | dict(overview=activity_overview(state, synced),
                        devices=[row | {'frame_analysis': frame_analysis(row)} for row in state['devices']])


def select_history(windows, device_ids, lookback_s, end_us):
    duration_us = lookback_s * 1_000_000
    recent = deque(maxlen=duration_us // WINDOW_US)
    last_end = 0
    for window in windows:
        end = window['window_end_us']
        if end_us is not None and end > end_us:
            break
        if end <= last_end:
            continue
        last_end = end
        devices = [row | {'frame_analysis': frame_analysis(row)} for row in window['devices'] if row['id'] in device_ids]
        if devices:
            recent.append(window | {'devices': devices})
    end = end_us if end_us is not None else last_end
    start = max(0, end - duration_us)
    return dict(window_start_us=start, window_end_us=end,
                windows=[row for row in recent if row['window_start_us'] >= start])


def archived_history(folder, source, device_ids, lookback_s, end_us):
    metadata = read_metadata(folder)
    if not metadata['ended_at'] or metadata['source'] != source:
        return None
    return select_history(recorded_activity_windows(folder / 'raw.jsonl', metadata['devices']),
                          device_ids, lookback_s, end_us)


@router.get('/activity/history')
async def history(request: Request, source: Literal['LIVE', 'SIMULATION', 'REPLAY'] | None = None,
                  session_id: UUID | None = None, device_id: UUID | None = None,
                  device_ids: Annotated[list[UUID] | None, Query(max_length=208)] = None,
                  lookback_s: Annotated[int, Query(ge=10, le=1800)] = 1800,
                  end_us: Annotated[int | None, Query(ge=0, le=2**53 - 1)] = None):
    service = request.app.state.probe_service
    active_source = service.activity_output_source()
    if source is None and session_id is None and device_id is None and device_ids is None and end_us is None and lookback_s == 1800:
        return dict(source=active_source, session_id=service.activity_session_id,
                    capture_id=service.activity_replay_id, windows=list(service.activity_history))
    if source is None or session_id is None or bool(device_id) == bool(device_ids):
        raise HTTPException(422, 'Cần nguồn, ID phiên và ID thiết bị cho truy vấn lịch sử')
    ids = {item.hex for item in (device_ids or [device_id])}
    key = session_id.hex
    result = None
    if source == active_source and key == service.activity_session_id:
        result = select_history(service.activity_history, ids, lookback_s, end_us)
    elif source in ('LIVE', 'SIMULATION'):
        folder = service.activity_root / key
        if (folder / 'metadata.json').is_file():
            try:
                result = await asyncio.to_thread(archived_history, folder, source, ids, lookback_s, end_us)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise HTTPException(422, 'Bản ghi Activity không hợp lệ') from error
        elif source == 'SIMULATION':
            session, batches = saved_simulation(service, key)
            if session:
                windows = (window for batch in batches for window in batch.get('activity_windows', []))
                result = select_history(windows, ids, lookback_s, end_us)
    if result is None:
        raise HTTPException(404, 'Không tìm thấy phiên Activity của nguồn đã chọn')
    filter_fields = {'device_id': device_id.hex} if device_id else {'device_ids': sorted(ids)}
    return dict(result, source=source, session_id=key, **filter_fields)


@router.post('/connect')
async def connect(request: Request, body: Connection):
    service = request.app.state.probe_service
    if service.simulation_port:
        port = Path(body.port)
        pty = port.resolve()
        if (body.port != service.simulation_port or pty.parent != Path('/dev/pts')
                or not pty.name.isdecimal() or not pty.is_char_device()):
            raise HTTPException(400, 'Cần PTY đã cấu hình cho SIMULATION')
    elif body.port not in {port.device for port in list_ports.comports()}:
        raise HTTPException(400, 'Cổng không tồn tại')
    async with service.control:
        if service.session or service.activity_capture:
            raise HTTPException(409, 'Kết thúc phiên trước khi đổi nguồn')
        await service.connect(body.port, body.baud, detect_protocol=True)
    return {'ok': True}


@router.post('/disconnect')
async def disconnect(request: Request):
    service = request.app.state.probe_service
    async with service.control:
        if service.session:
            raise HTTPException(409, 'Kết thúc phiên Probe trước khi ngắt nguồn USB')
        if service.mode == 'serial' or service.activity_source:
            await service.stop()
    return {'ok': True}


class Experiment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    scenario: Literal['baseline', 'traffic', 'mixed', 'channel', 'other']
    device_ids: Annotated[list[UUID], Field(max_length=208)]


def experiment_metadata(body, devices):
    if body is None:
        return {}
    if MAC_IN_NAME.search(body.title):
        raise HTTPException(422, 'Tên thực nghiệm không chứa địa chỉ MAC')
    ids = sorted({item.hex for item in body.device_ids})
    if not set(ids) <= {device['id'] for device in devices}:
        raise HTTPException(422, 'Có thiết bị thực nghiệm không còn trong registry')
    return dict(title=body.title, scenario=body.scenario, device_ids=ids)


@router.get('/captures')
async def captures(request: Request):
    service = request.app.state.probe_service
    rows = []
    for path in sorted(service.activity_root.glob('*/metadata.json')):
        try:
            metadata = read_metadata(path.parent)
            rows.append(metadata | dict(devices=metadata.pop('device_catalog') or metadata['devices'], has_raw=True))
        except (ValueError, OSError):
            continue
    for session in service.store.reliability_sessions():
        if session['mode'] not in ('SIMULATION', 'DEMO'):
            continue
        batches = service.store.reliability_batches(session['id'], limit=1)
        windows = batches[0].get('activity_windows', []) if batches else []
        if windows:
            rows.append(dict(id=session['id'], source='SIMULATION', started_at=session['started_at'],
                             ended_at=session.get('ended_at') or session['started_at'], title='Mô phỏng UART đã lưu',
                             scenario=None, records=None, devices=windows[-1]['devices'], device_ids=None, has_raw=False))
    return {'captures': sorted(rows, key=lambda row: row['started_at'], reverse=True)}


@router.post('/captures/start', status_code=201)
async def start_capture(request: Request, body: Experiment | None = None):
    service = request.app.state.probe_service
    async with service.control:
        if body and not body.device_ids:
            raise HTTPException(422, 'Chọn ít nhất một thiết bị thực nghiệm')
        try:
            return service.start_activity_capture(**experiment_metadata(body, service.store.registered_devices()))
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except OSError as error:
            raise HTTPException(500, 'Không thể tạo phiên activity') from error


@router.post('/captures/simulate', status_code=201)
async def simulate(request: Request, body: Experiment | None = None):
    service = request.app.state.probe_service
    async with service.control:
        if service.session or service.activity_capture or service.mode == 'serial':
            raise HTTPException(409, 'Ngắt kết nối USB hoặc kết thúc phiên đang ghi trước khi chạy mô phỏng')
        devices = service.store.registered_devices()
        options = experiment_metadata(body, devices)
        if body:
            if devices and not options['device_ids']:
                raise HTTPException(422, 'Chọn ít nhất một thiết bị thực nghiệm')
            devices = [device for device in devices if device['id'] in options['device_ids']]
        if not devices:
            devices = [dict(id=uuid4().hex, name='Thiết bị mô phỏng',
                            channel=service.store.activity_channel() or 6, consent_at=utc())]
            options['device_ids'] = [devices[0]['id']]
        channel = service.store.activity_channel() or devices[0]['channel']
        return await asyncio.to_thread(simulated_capture, service.activity_root, devices, channel, **options)


@router.post('/captures/stop')
async def stop_capture(request: Request):
    service = request.app.state.probe_service
    async with service.control:
        try:
            return service.stop_activity_capture()
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except OSError as error:
            raise HTTPException(500, 'Không thể lưu phiên activity') from error


@router.post('/replay')
async def replay(request: Request, body: Replay):
    service = request.app.state.probe_service
    async with service.control:
        if service.session or service.activity_capture:
            raise HTTPException(409, 'Kết thúc phiên trước khi phát lại')
        folder = service.activity_root / body.capture_id.hex
        raw = folder / 'raw.jsonl'
        if not (folder / 'metadata.json').is_file() or not raw.is_file():
            raise HTTPException(404, 'Phiên activity không tồn tại')
        try:
            meta = read_metadata(folder)
        except (ValueError, OSError) as error:
            raise HTTPException(400, 'Metadata phiên không hợp lệ') from error
        if not meta['ended_at']:
            raise HTTPException(409, 'Phiên chưa hoàn tất')
        await service.replay_activity(raw, body.speed, meta['devices'], meta['id'],
                                      source='SIMULATION' if meta['source'] == 'SIMULATION' else 'REPLAY')
    return {'ok': True}
