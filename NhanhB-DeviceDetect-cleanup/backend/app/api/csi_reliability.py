"""Versioned reliability sessions over normalized RX metadata and existing Q2 replay."""

import asyncio
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator

from backend.app.api.csi_quality import saved_trace
from backend.app.api.private_input import PrivateInputRoute
from backend.app.storage import utc
from research.csi_ingestion import ClockAnchor, CsiTrace, Record, sniffer_span
from research.csi_quality import SECOND, quality_result, timeline
from research.csi_reliability import ReliabilityRules, SourceHealth, assess, evidence
from research.reliability_demo import demo_activity, demo_trace


router = APIRouter(prefix='/api/device-csi/reliability', tags=['CSI reliability'], route_class=PrivateInputRoute)
VERSION = 'csi-reliability-v1'


class SessionRequest(Record):
    mode: Literal['LIVE', 'REPLAY', 'SIMULATION', 'DEMO']
    quality_replay_id: Annotated[UUID, Field(strict=False)] | None = None
    rules: ReliabilityRules | None = None
    simulation_trace: CsiTrace | None = None
    activity_session_id: Annotated[UUID, Field(strict=False)] | None = None

    @model_validator(mode='after')
    def check_replay(self):
        if (self.mode == 'REPLAY') != (self.quality_replay_id is not None):
            raise ValueError('REPLAY requires a Q2 replay ID')
        if self.simulation_trace is not None:
            trace = self.simulation_trace
            if (self.mode != 'SIMULATION' or self.activity_session_id is None or trace.provenance != 'synthetic'
                    or trace.sniffer_intervals or trace.sniffer_clock or trace.sniffer_source
                    or trace.receiver_id is None or trace.duration_s % 10):
                raise ValueError('PTY simulation requires a synthetic RX trace and the active Activity session')
        elif self.activity_session_id is not None:
            raise ValueError('PTY simulation requires a trace')
        return self


class LiveBatch(Record):
    offset_us: Annotated[int, Field(ge=0, le=604_800_000_000, multiple_of=10_000_000)]
    trace: CsiTrace

    @model_validator(mode='after')
    def complete_windows(self):
        if self.trace.duration_s % 10:
            raise ValueError('LIVE batches must cover complete 10 second windows')
        return self


def analyze_batch(trace, rules):
    checked = trace.sniffer_source == ('SIMULATION' if trace.provenance == 'synthetic' else 'LIVE')
    return {str(width): timeline(trace, rules, width) | {'sniffer_context_verified': checked} for width in (1, 10)}


def simulation_capture(service, activity_id, trace):
    if service.activity_output_source() != 'SIMULATION' or service.activity_session_id != activity_id:
        raise HTTPException(409, 'Trace CSI cần đúng phiên PTY SIMULATION')
    monitor = service.activity
    origin = monitor.origin_us
    spans, anchors = [], []
    if origin is not None and service.connection == 'connected':
        end = min(monitor.status['ts_us'], origin + trace.duration_s * SECOND)
        if end > origin:
            # Both virtual clocks count microseconds from the run's first heartbeat.
            anchors = [ClockAnchor(board_us=t, session_us=t - origin, uncertainty_us=1000)
                       for t in (origin, end)]
            spans = [sniffer_span(interval, monitor.last_seen) for interval in monitor.intervals
                     if not interval.issues and origin <= interval.start_us and interval.end_us <= end]
    captured = trace.model_copy(update=dict(sniffer_source='SIMULATION', sniffer_intervals=spans, sniffer_clock=anchors))
    return captured, list(service.activity_history), service.activity_snapshot()


def event_time(session, event_us):
    if session['mode'] != 'LIVE':
        return None
    return datetime.fromisoformat(session['started_at']) + timedelta(microseconds=event_us)


def assess_row(session, report, row, offset_us, evaluated_at, context, rules):
    csi, devices, radio = evidence(report, row, offset_us)
    if not report.get('sniffer_context_verified'):
        devices = radio = None
    end = offset_us + row['end_us']
    event_at = event_time(session, end)
    age = max(0., (evaluated_at - event_at).total_seconds()) if event_at else 0.
    rx_clock = report['clocks']['rx']['aligned']
    rx_state = ('available' if csi.coverage or not rx_clock else 'disconnected') if (
        report['input_rx_samples'] or report['input_rx_intervals']) else 'missing'
    rx = SourceHealth(rx_state, rx_clock, age if rx_state == 'available' else None)
    reason = row['activity_unavailable_reason']
    if not report.get('sniffer_context_verified'):
        reason = 'sniffer_context_unverified'
    sniffer_state = ('available' if radio or reason in ('sniffer_clock_not_aligned', 'sniffer_other_channel')
                     else 'disconnected') if report['input_sniffer_intervals'] else 'missing'
    sniffer = SourceHealth(sniffer_state, report['clocks']['comparison_aligned'],
                          age if sniffer_state == 'available' else None, reason)
    coverage = (row['sniffer_coverage'] if report.get('sniffer_context_verified') and
                report['input_sniffer_intervals'] and report['clocks']['comparison_aligned'] else None)
    return assess(csi, devices, radio, rx, sniffer, start_us=offset_us + row['start_us'], end_us=end,
                  event_utc=event_at.isoformat() if event_at else None, rules=rules, use_context=context,
                  receiver_id=report.get('receiver_id'), channel_coverage=coverage,
                  quality_state=row['quality'] if report.get('receiver_id') else 'UNKNOWN',
                  quality_reasons=row['reasons'] if report.get('receiver_id') else None)


def quality_row_at(session, report, row, offset, evaluated_at, rules):
    event = event_time(session, offset + row['end_us'])
    stale = event and (evaluated_at - event).total_seconds() > rules.max_source_age_s
    result = quality_result(report, row, offset, unavailable='rx_stale' if stale else None)
    return result | {'at': event.isoformat() if event else None}


def public_session(session):
    if session['provenance'] == 'synthetic' and session.get('sniffer_capture_id'):
        return session | {'sniffer_capture_id': None}
    return session


def session_report(session, batches, window_s, context, now):
    rules = ReliabilityRules.model_validate(session['rules'])
    recent = ((report, row, batch['offset_us'], batch['received_at'])
              for batch in reversed(batches) for report in (batch['reports'][str(window_s)],)
              for row in reversed(report['windows']))
    selected = list(islice(recent, 300))
    rows = [assess_row(session, report, row, offset, datetime.fromisoformat(received_at), context, rules)
            for report, row, offset, received_at in reversed(selected)]
    last = selected[0] if selected else None
    evaluated_at = datetime.fromisoformat(last[3]) if last and session.get('ended_at') else now
    current = (assess_row(session, *last[:3], evaluated_at, context, rules) if last else
               assess(None, None, None, SourceHealth('missing'), SourceHealth('missing'),
                      start_us=None, end_us=None, event_utc=None, rules=rules, use_context=context))
    quality = quality_result(None, None, unavailable='rx_missing')
    if last:
        report, row, offset, _ = last
        quality = quality_row_at(session, report, row, offset, evaluated_at, rules)
    source = 'SIMULATION' if session['mode'] == 'DEMO' else session['mode']
    activity = batches[-1].get('activity_windows', []) if source == 'SIMULATION' and batches else []
    activity_current = batches[-1].get('activity_current') if source == 'SIMULATION' and batches else None
    return dict(activity=activity_current or (activity[-1] if activity else None), quality=quality, source=source, session_id=session['id'], version=VERSION, session=public_session(session), window_s=window_s, context=context,
                current=current, timeline=rows, clocks=last[0]['clocks'] if last else None)


@router.get('/sessions')
async def list_sessions(request: Request):
    sessions = request.app.state.probe_service.store.reliability_sessions()
    return {'sessions': [public_session(session) for session in sessions]}


@router.post('/sessions', status_code=201)
async def create_session(request: Request, body: SessionRequest):
    service = request.app.state.probe_service
    store = service.store
    if service.simulation_port and body.mode == 'LIVE':
        raise HTTPException(409, 'Backend PTY chỉ thu SIMULATION')
    rules = body.rules or ReliabilityRules()
    trace = None
    sniffer_capture_id = None
    activity_id = body.activity_session_id.hex if body.activity_session_id else None
    if body.simulation_trace is not None:
        trace, windows, current = simulation_capture(service, activity_id, body.simulation_trace)
    elif body.mode in ('SIMULATION', 'DEMO'):
        trace = demo_trace()
    elif body.mode == 'REPLAY':
        saved = store.quality_replay(body.quality_replay_id.hex)
        if saved is None:
            raise HTTPException(404, 'CSI quality replay không tồn tại')
        trace = saved_trace(saved)
        sniffer_capture_id = saved.get('sniffer_capture_id') if trace.sniffer_source == 'LIVE' else None
        if body.rules is None:
            rules = ReliabilityRules.model_validate(saved['rules'])
    session = dict(id=activity_id or uuid4().hex, version=VERSION, mode='SIMULATION' if body.mode == 'DEMO' else body.mode,
                   provenance=trace.provenance if trace else 'live_adapter', started_at=utc(),
                   rules=rules.model_dump(), config_version=rules.config_version,
                   sniffer_capture_id=sniffer_capture_id,
                   quality_replay_id=body.quality_replay_id.hex if body.quality_replay_id else None)
    batch = None
    if trace:
        reports = await asyncio.to_thread(analyze_batch, trace, rules)
        payload = dict(offset_us=0, received_at=utc(), reports=reports)
        if activity_id:
            payload.update(activity_windows=windows, activity_current=current)
        elif session['mode'] == 'SIMULATION':
            payload['activity_windows'] = list(demo_activity(trace))
        batch = (0, trace.duration_s * SECOND, payload)
    if activity_id and store.reliability_session(activity_id):
        raise HTTPException(409, 'Phiên PTY đã được lưu')
    store.save_reliability_session(session, batch)
    return session


@router.post('/sessions/{session_id}/batches', status_code=202)
async def ingest_live(request: Request, session_id: UUID, body: LiveBatch):
    store = request.app.state.probe_service.store
    session = store.reliability_session(session_id.hex)
    if session is None:
        raise HTTPException(404, 'Reliability session không tồn tại')
    if session['mode'] != 'LIVE' or body.trace.provenance != 'live_adapter':
        raise HTTPException(422, 'LIVE chỉ nhận trace từ adapter live')
    if session.get('ended_at'):
        raise HTTPException(409, 'Phiên đã kết thúc')
    if body.trace.receiver_id is None:
        raise HTTPException(422, 'Batch LIVE cần receiver_id')
    if body.trace.sniffer_intervals and (
        body.trace.sniffer_source != 'LIVE' or body.trace.sniffer_session_id != session_id.hex
    ):
        raise HTTPException(422, 'Ngữ cảnh sniffer LIVE cần cùng nguồn và cùng ID phiên')
    end = body.offset_us + body.trace.duration_s * SECOND
    if event_time(session, end) > datetime.now(timezone.utc):
        raise HTTPException(422, 'Batch LIVE nằm trong tương lai theo đồng hồ phiên')
    rules = ReliabilityRules.model_validate(session['rules'])
    reports = await asyncio.to_thread(analyze_batch, body.trace, rules)
    if store.reliability_session(session_id.hex).get('ended_at'):
        raise HTTPException(409, 'Phiên đã kết thúc')
    previous = store.reliability_batches(session_id.hex, limit=1)
    if previous:
        receiver_id = previous[0]['reports']['10'].get('receiver_id')
        if receiver_id is not None and receiver_id != body.trace.receiver_id:
            raise HTTPException(409, 'Mỗi phiên CSI chỉ nhận batch từ một receiver')
    try:
        store.save_reliability_batch(session_id.hex, body.offset_us, end,
                                     dict(offset_us=body.offset_us, received_at=utc(), reports=reports))
    except ValueError as error:
        raise HTTPException(409, 'Batch LIVE chồng lấn cửa sổ đã lưu') from error
    return {'session_id': session_id.hex, 'accepted_end_us': end}


@router.post('/sessions/{session_id}/stop')
async def stop_session(request: Request, session_id: UUID):
    store = request.app.state.probe_service.store
    session = store.reliability_session(session_id.hex)
    if session is None:
        raise HTTPException(404, 'Reliability session không tồn tại')
    if session['mode'] != 'LIVE':
        raise HTTPException(409, 'Chỉ dừng được phiên ghi LIVE')
    return store.stop_reliability_session(session)


@router.get('/sessions/{session_id}/timeline')
async def get_timeline(request: Request, session_id: UUID, window_s: int = 1,
                       context: Literal['combined', 'csi-only'] = 'combined'):
    store = request.app.state.probe_service.store
    session = store.reliability_session(session_id.hex)
    if session is None:
        raise HTTPException(404, 'Reliability session không tồn tại')
    if window_s not in (1, 10):
        raise HTTPException(422, 'Cửa sổ phải là 1 hoặc 10 giây')
    batches = store.reliability_batches(session_id.hex)
    return await asyncio.to_thread(session_report, session, batches, window_s, context == 'combined', datetime.now(timezone.utc))
