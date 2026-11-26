"""Experiment annotations and CSV exports over the existing Q1/Q2/Q3 results."""

import asyncio
import csv
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, StringConstraints

from backend.app.api.csi_quality import saved_trace
from backend.app.api.csi_reliability import assess_row, quality_row_at
from backend.app.api.device_activity import MAC_IN_NAME
from backend.app.api.private_input import PrivateInputRoute
from research.activity_records import load_records, read_metadata, recorded_activity_windows
from research.csi_ingestion import Record
from research.csi_quality import QualityRules, quality_result, timeline
from research.csi_reliability import ReliabilityRules
from research.device_activity import frame_analysis


router = APIRouter(prefix='/api/device-csi/experiments', tags=['Device & CSI experiments'], route_class=PrivateInputRoute)
Scope = Literal['q1', 'q2', 'q3']


class Marker(Record):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    elapsed_s: Annotated[float, Field(ge=0, le=604800, allow_inf_nan=False)] | None = None


def lookup(service, scope, session_id):
    if scope == 'q1':
        folder = service.activity_root / session_id
        if service.activity_capture and service.activity_capture.metadata['id'] == session_id:
            return scope, service.activity_capture.metadata
        if (folder / 'metadata.json').is_file():
            return scope, read_metadata(folder)
    if scope == 'q2':
        replay = service.store.quality_replay(session_id)
        if replay:
            return scope, replay
    session = service.store.reliability_session(session_id)
    if session and (scope != 'q1' or session['mode'] in ('SIMULATION', 'DEMO')):
        return 'q3', session
    raise HTTPException(404, 'Không tìm thấy phiên thực nghiệm')


@router.get('/{scope}/{session_id}/markers')
async def markers(request: Request, scope: Scope, session_id: UUID):
    service = request.app.state.probe_service
    storage_scope, _ = lookup(service, scope, session_id.hex)
    return {'markers': service.store.device_csi_markers(storage_scope, session_id.hex)}


@router.post('/{scope}/{session_id}/markers', status_code=201)
async def mark(request: Request, scope: Scope, session_id: UUID, body: Marker):
    service = request.app.state.probe_service
    if MAC_IN_NAME.search(body.label):
        raise HTTPException(422, 'Dùng nhãn thao tác thay cho địa chỉ MAC')
    async with service.control:
        storage_scope, session = lookup(service, scope, session_id.hex)
        elapsed = body.elapsed_s
        if storage_scope == 'q1':
            capture = service.activity_capture
            if capture is None or capture.metadata['id'] != session_id.hex:
                raise HTTPException(409, 'Cần phiên Q1 đang ghi')
            elapsed = service.now() - capture.origin
        elif storage_scope == 'q3' and session['mode'] == 'LIVE':
            if session.get('ended_at'):
                raise HTTPException(409, 'Phiên LIVE đã kết thúc')
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(session['started_at'])).total_seconds()
        elif elapsed is None:
            raise HTTPException(422, 'Nhập mốc giây trên trục thời gian của phiên')
        elif storage_scope == 'q2' and elapsed > session['trace']['duration_s']:
            raise HTTPException(422, 'Mốc vượt quá thời lượng trace CSI')
        return service.store.add_device_csi_marker(storage_scope, session_id.hex, elapsed, body.label)


def activity_rows(windows, selected):
    for window in windows:
        for device in window['devices']:
            if selected is not None and device['id'] not in selected:
                continue
            kinds = device.get('frame_types') or {}
            analysis = frame_analysis(device)
            yield dict(boot_id=window['boot_id'], registry_revision=window.get('registry_revision'), window_start_us=window['window_start_us'],
                       window_end_us=window['window_end_us'], device_id=device['id'], device_name=device['name'],
                       actual_channel=window.get('channel'),
                       registered_channel=device['channel'], state=device['state'], reasons='|'.join(device['reasons']),
                       observation_time_s=device['observation_time_s'], channel_coverage=device['channel_coverage'],
                       data_valid=device['data_valid'], observed_frames=device['observed_frames'],
                       observed_bytes=device['observed_bytes'], last_observed_channel=device['last_observed_channel'],
                       frames_per_s=device['frames_per_s'], bytes_per_s=device['bytes_per_s'],
                       rssi_max_dbm=device['rssi_max_dbm'], last_seen_us=device['last_seen_us'],
                       channel_frames_per_s=window['channel_frames_per_s'],
                       management_frames=kinds.get('management'), data_frames=kinds.get('data'),
                       control_frames=kinds.get('control'), tx_frames=device.get('tx_frames'),
                       rx_frames=device.get('rx_frames'), block_ack_frames=device.get('block_ack_frames'),
                       **{f'{kind}_frames_per_s': item['frames_per_s'] for kind, item in analysis.items()},
                       **{f'{kind}_fraction': analysis[kind]['fraction'] for kind in ('management', 'data', 'control')})


def activity_summary(rows):
    grouped = defaultdict(list)
    for row in rows:
        key = tuple(row[field] for field in ('device_id', 'boot_id', 'registry_revision', 'actual_channel', 'registered_channel'))
        grouped[key].append(row)
    for (device_id, boot_id, revision, channel, registered_channel), windows in grouped.items():
        valid = [row for row in windows if row['data_valid']]
        frames = sum(row['observed_frames'] for row in valid) if valid else None
        byte_count = sum(row['observed_bytes'] for row in valid) if valid else None
        seconds = sum(row['observation_time_s'] for row in valid) if valid else None
        coverages = [row['channel_coverage'] for row in windows if row['channel_coverage'] is not None]
        rssis = [row['rssi_max_dbm'] for row in valid if row['rssi_max_dbm'] is not None]
        active = sum(row['state'] == 'OBSERVED_ACTIVE' for row in windows)
        quiet = sum(row['state'] == 'NO_OBSERVED_ACTIVITY' for row in windows)
        total = len(windows)
        unknown = total - active - quiet
        yield dict(kind='summary', device_id=device_id, device_name=windows[-1]['device_name'],
                   boot_id=boot_id, registry_revision=revision, actual_channel=channel, registered_channel=registered_channel,
                   duration_s=sum(row['window_end_us'] - row['window_start_us'] for row in windows) / 1_000_000,
                   observed_frames=frames, observed_bytes=byte_count, observation_time_s=seconds,
                   avg_frames_per_s=frames / seconds if seconds else None,
                   avg_bytes_per_s=byte_count / seconds if seconds else None,
                   max_frames_per_s=max((row['frames_per_s'] for row in valid), default=None),
                   max_bytes_per_s=max((row['bytes_per_s'] for row in valid), default=None),
                   stddev_frames_per_s=pstdev([row['frames_per_s'] for row in valid]) if valid else None,
                   stddev_bytes_per_s=pstdev([row['bytes_per_s'] for row in valid]) if valid else None,
                   representative_rssi_dbm=median(rssis) if rssis else None,
                   channel_coverage=mean(coverages) if coverages else None, total_windows=total,
                   active_windows=active, quiet_windows=quiet, unknown_windows=unknown,
                   active_fraction=active / total, quiet_fraction=quiet / total, unknown_fraction=unknown / total,
                   activity_ratio=active / (active + quiet) if active + quiet else None)


def raw_activity_rows(path, selected):
    for stamp, packet in load_records(path):
        kind = packet['type']
        if kind == 'activity_sample' and selected is not None and packet['device_id'] not in selected:
            continue
        yield {key: value for key, value in packet.items() if key != 'mode'} | dict(
            kind='raw', record_type=kind, elapsed_s=stamp, capture_mode=packet.get('mode'),
                            control_kind=packet.get('kind'))


def quality_rows(report, offset=0, session=None, evaluated_at=None):
    rules = ReliabilityRules.model_validate(session['rules']) if session else None
    for row in report['windows']:
        result = (quality_row_at(session, report, row, offset, evaluated_at, rules) if session
                  else quality_result(report, row, offset))
        yield dict(result, state=result['quality'], reasons='|'.join(result['reasons']),
                   csi_channel=result['channel'])


def reliability_rows(session, batches, window_s, combined):
    rules = ReliabilityRules.model_validate(session['rules'])
    for batch in batches:
        report = batch['reports'][str(window_s)]
        received_at = datetime.fromisoformat(batch['received_at'])
        for source in report['windows']:
            row = assess_row(session, report, source, batch['offset_us'], received_at, combined, rules)
            yield dict(window_start_us=row['window_start_us'], window_end_us=row['window_end_us'],
                       at=row['event_timestamp']['utc'], csi_channel=report['channel'], state=row['reliability_label'],
                       reasons='|'.join(row['reason_codes']), evidence_mode=row['evidence_mode'],
                       data_sources='|'.join(row['data_sources']), config_version=row['config_version'],
                       receiver_id=row['receiver_id'], data_valid=row['data_valid'],
                       channel_alignment=row['channel_alignment'], channel_coverage=row['channel_coverage'],
                       evidence_source=row['evidence_source'],
                       channel_frames_per_s=(row['observed_indicators']['channel'] or {}).get('frames_per_s'))


CSV_FIELDS = ('kind', 'scope', 'session_id', 'source', 'mode', 'provenance', 'started_at', 'ended_at', 'window_s',
              'at', 'elapsed_s', 'label', 'boot_id', 'registry_revision',
              'window_start_us', 'window_end_us', 'device_id', 'device_name', 'registered_channel', 'csi_channel', 'state', 'reasons',
              'rx_coverage', 'observation_time_s', 'channel_coverage', 'data_valid', 'observed_frames', 'observed_bytes',
              'last_observed_channel', 'frames_per_s', 'bytes_per_s', 'rssi_max_dbm', 'rssi_median_dbm', 'last_seen_us', 'channel_frames_per_s',
              'receiver_id', 'csi_receive_hz', 'tx_packet_rate', 'packet_loss_fraction', 'jitter_ms', 'noise_floor_median_dbm',
              'n_filtered', 'loss_basis', 'loss_unavailable_reason', 'channel_alignment', 'evidence_source',
              'evidence_mode', 'data_sources', 'config_version')


Q1_BASE = CSV_FIELDS[:9] + ('title', 'scenario')
Q1_DETAIL = Q1_BASE + ('at', 'elapsed_s', 'label', 'boot_id', 'registry_revision', 'window_start_us', 'actual_channel',
                       'window_end_us', 'device_id', 'device_name', 'registered_channel', 'state', 'reasons',
                       'observation_time_s', 'channel_coverage', 'data_valid', 'observed_frames', 'observed_bytes',
                       'last_observed_channel', 'frames_per_s', 'bytes_per_s', 'rssi_max_dbm', 'last_seen_us',
                       'channel_frames_per_s', 'management_frames', 'data_frames', 'control_frames',
                       'tx_frames', 'rx_frames', 'block_ack_frames',
                       'management_frames_per_s', 'data_frames_per_s', 'control_frames_per_s',
                       'tx_frames_per_s', 'rx_frames_per_s', 'management_fraction', 'data_fraction', 'control_fraction')
Q1_SUMMARY = Q1_BASE + ('device_id', 'device_name', 'boot_id', 'registry_revision', 'actual_channel', 'registered_channel',
                        'duration_s', 'observed_frames', 'observed_bytes', 'observation_time_s',
                        'avg_frames_per_s', 'avg_bytes_per_s', 'max_frames_per_s', 'max_bytes_per_s',
                        'stddev_frames_per_s', 'stddev_bytes_per_s', 'representative_rssi_dbm',
                        'channel_coverage', 'total_windows', 'active_windows', 'quiet_windows',
                        'unknown_windows', 'active_fraction', 'quiet_fraction', 'unknown_fraction', 'activity_ratio')
Q1_RAW = Q1_BASE + ('elapsed_s', 'record_type', 'control_kind', 'v', 'node', 'boot_id', 'registry_revision',
                    'seq', 'ts_us', 'channel', 'device_id', 'duration_us', 'attribution', 'frame_kind',
                    'n_frames', 'n_bytes', 'rssi_max_dbm', 'tx_frames', 'rx_frames', 'block_ack_frames',
                    'capture_mode', 'capture_active', 'scan_mode', 'runtime_config', 'channel_min', 'channel_max',
                    'firmware_version', 'serial_baud', 'registered_devices', 'rx_callbacks', 'invalid_frames',
                    'off_channel_frames', 'unattributed_frames', 'unregistered_frames', 'management_frames',
                    'data_frames', 'control_frames', 'serial_errors', 'bytes_written', 'queue_drops')


class CsvLine:
    def write(self, value):
        return value


def csv_stream(metadata, rows, events, fields=CSV_FIELDS):
    writer = csv.DictWriter(CsvLine(), fields, extrasaction='ignore')
    metadata = metadata.copy()
    title = metadata.get('title')
    if title and title.lstrip().startswith(('=', '+', '-', '@')):
        metadata['title'] = "'" + title
    yield '\ufeff' + writer.writeheader()
    yield writer.writerow(metadata | {'kind': 'session'})
    for kind, items in (('window', rows), ('marker', events)):
        for item in items:
            row = metadata | {'kind': kind} | item
            for field in ('label', 'device_name'):
                value = row.get(field)
                if value and value.lstrip().startswith(('=', '+', '-', '@')):
                    row[field] = "'" + value
            yield writer.writerow(row)


DeviceFilter = Annotated[list[UUID] | None, Query(max_length=208)]


def q1_export_data(service, key, replay, format, device_ids, all_devices):
    storage_scope, session = lookup(service, 'q1', key)
    if replay and (storage_scope != 'q1' or session.get('source') == 'SIMULATION'):
        raise HTTPException(422, 'Chỉ chọn REPLAY khi xuất bản ghi UART LIVE')
    defaults = session.get('device_ids')
    selected = ({item.hex for item in device_ids} if device_ids else
                set(defaults) if defaults is not None and not all_devices else None)
    if storage_scope == 'q1':
        if not session['ended_at']:
            raise HTTPException(409, 'Kết thúc phiên Q1 trước khi xuất CSV')
        path = service.activity_root / key / 'raw.jsonl'
        original = session.get('source', 'LIVE')
        mode = 'REPLAY' if replay else original
        provenance = 'synthetic' if original == 'SIMULATION' else 'recorded_uart'
        rows = (raw_activity_rows(path, selected) if format == 'raw'
                else activity_rows(recorded_activity_windows(path, session['devices']), selected))
    else:
        if format == 'raw':
            raise HTTPException(404, 'Phiên này không có bản ghi UART thô')
        batches = service.store.reliability_batches(key, limit=-1)
        rows = activity_rows((window for batch in batches for window in batch.get('activity_windows', [])), selected)
        mode, provenance = session['mode'], session['provenance']
    return storage_scope, session, ('SIMULATION' if mode == 'DEMO' else mode), provenance, rows


@router.get('/q1/{session_id}/summary')
def q1_summary(request: Request, session_id: UUID, replay: bool = False, device_ids: DeviceFilter = None,
               all_devices: bool = False):
    service = request.app.state.probe_service
    _, _, source, _, rows = q1_export_data(service, session_id.hex, replay, 'summary', device_ids, all_devices)
    return dict(source=source, session_id=session_id.hex, devices=list(activity_summary(rows)))


@router.get('/{scope}/{session_id}/export.csv')
async def export_csv(request: Request, scope: Scope, session_id: UUID,
                     window_s: int = 10, context: Literal['combined', 'csi-only'] = 'combined',
                     replay: bool = False, format: Literal['detail', 'summary', 'raw'] = 'detail',
                     device_ids: DeviceFilter = None,
                     all_devices: bool = False):
    if window_s not in (1, 10) or (scope == 'q1' and window_s != 10):
        raise HTTPException(422, 'Q1 dùng cửa sổ 10 giây. CSI hỗ trợ 1 hoặc 10 giây.')
    if scope != 'q1' and (format != 'detail' or device_ids or all_devices):
        raise HTTPException(422, 'Định dạng và chọn thiết bị chỉ áp dụng cho Q1')
    service = request.app.state.probe_service
    key = session_id.hex
    if replay and scope != 'q1':
        raise HTTPException(422, 'Chỉ chọn REPLAY khi xuất bản ghi UART LIVE')
    fields, filename = CSV_FIELDS, f'{scope}-{key}.csv'
    if scope == 'q1':
        storage_scope, session, mode, provenance, rows = q1_export_data(
            service, key, replay, format, device_ids, all_devices)
        fields, filename = {
            'detail': (Q1_DETAIL, 'q1_activity_detail.csv'),
            'summary': (Q1_SUMMARY, 'q1_experiment_summary.csv'),
            'raw': (Q1_RAW, 'q1_raw_capture.csv'),
        }[format]
        if format == 'summary':
            rows = activity_summary(rows)
    else:
        storage_scope, session = lookup(service, scope, key)
    if scope != 'q1' and storage_scope == 'q2':
        trace = saved_trace(session)
        report = await asyncio.to_thread(timeline, trace, QualityRules.model_validate(session['rules']), window_s)
        rows = quality_rows(report)
        mode, provenance = 'REPLAY', trace.provenance
    elif scope != 'q1':
        batches = service.store.reliability_batches(key, limit=-1)
        if scope == 'q2':
            rows = (row for batch in batches for row in quality_rows(
                batch['reports'][str(window_s)], batch['offset_us'], session,
                datetime.fromisoformat(batch['received_at'])))
        else:
            rows = reliability_rows(session, batches, window_s, context == 'combined')
        mode, provenance = session['mode'], session['provenance']
    source = 'SIMULATION' if mode == 'DEMO' else mode
    metadata = dict(scope=scope, session_id=key, source=source, mode=source, provenance=provenance, window_s=window_s,
                    started_at=session.get('started_at'), ended_at=session.get('ended_at'),
                    title=session.get('title'), scenario=session.get('scenario'))
    events = service.store.device_csi_markers(storage_scope, key) if format == 'detail' else ()
    return StreamingResponse(csv_stream(metadata, rows, events, fields), media_type='text/csv',
                             headers={'Content-Disposition': f'attachment; filename="{filename}"'})
