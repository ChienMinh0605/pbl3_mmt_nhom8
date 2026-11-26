"""Persist and replay normalized CSI quality input through the existing local API."""

import asyncio
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator

from backend.app.api.private_input import PrivateInputRoute
from research.activity_records import read_metadata
from research.csi_ingestion import CsiTrace, Record, replay_sniffer
from research.csi_quality import QualityRules, quality_result, timeline


router = APIRouter(prefix='/api/device-csi/quality', tags=['CSI channel quality'], route_class=PrivateInputRoute)


class QualityReplay(Record):
    trace: CsiTrace
    rules: QualityRules = Field(default_factory=QualityRules)
    sniffer_capture_id: Annotated[UUID, Field(strict=False)] | None = None
    sniffer_boot_id: Annotated[str, Field(pattern=r'^[0-9a-f]{16}$')] | None = None

    @model_validator(mode='after')
    def require_capture_boot(self):
        if (self.sniffer_capture_id is None) != (self.sniffer_boot_id is None):
            raise ValueError('Select a capture and its boot together')
        if self.sniffer_capture_id and self.trace.sniffer_intervals:
            raise ValueError('Select either sniffer intervals or a capture')
        return self


def saved_trace(saved):
    trace = CsiTrace.model_validate(saved['trace'])
    attached_id = saved.get('sniffer_capture_id')
    if trace.provenance == 'synthetic':
        verified = attached_id is None and trace.sniffer_source == 'SIMULATION'
    else:
        verified = attached_id is not None and trace.sniffer_source == 'LIVE' and trace.sniffer_session_id == attached_id
    if not verified:
        return trace.model_copy(update={'sniffer_intervals': [], 'sniffer_clock': [], 'sniffer_source': None})
    return trace


@router.post('/replays', status_code=201)
async def create_replay(request: Request, body: QualityReplay):
    if body.trace.provenance not in ('synthetic', 'live_adapter'):
        raise HTTPException(422, 'Cần trace tổng hợp hoặc dữ liệu adapter đã chuẩn hóa')
    if body.trace.provenance == 'synthetic' and body.trace.sniffer_intervals and body.trace.sniffer_source != 'SIMULATION':
        raise HTTPException(422, 'Ngữ cảnh sniffer của trace tổng hợp cần nguồn SIMULATION')
    if body.trace.provenance == 'live_adapter' and body.trace.sniffer_intervals:
        raise HTTPException(422, 'Replay dữ liệu thật chỉ ghép qua capture đã liên kết')
    if body.sniffer_capture_id and (
        body.trace.provenance != 'live_adapter' or body.trace.sniffer_source != 'LIVE'
        or body.trace.sniffer_session_id != body.sniffer_capture_id.hex
    ):
        raise HTTPException(422, 'Capture cần liên kết phiên thu thật, cùng nguồn với CSI')
    service = request.app.state.probe_service
    trace = body.trace
    if body.sniffer_capture_id:
        folder = service.activity_root / body.sniffer_capture_id.hex
        raw = folder / 'raw.jsonl'
        if not (folder / 'metadata.json').is_file() or not raw.is_file():
            raise HTTPException(404, 'Phiên activity không tồn tại')
        try:
            metadata = read_metadata(folder)
            if not metadata['ended_at']:
                raise HTTPException(409, 'Phiên activity chưa hoàn tất')
            intervals = await asyncio.to_thread(replay_sniffer, raw, metadata['devices'],
                                                body.sniffer_boot_id, trace.sniffer_clock)
            trace = CsiTrace.model_validate(trace.model_dump() | {'sniffer_intervals': [row.model_dump() for row in intervals]})
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise HTTPException(422, 'Bản ghi activity không hợp lệ cho replay') from error
    replay_id = uuid4().hex
    service.store.save_quality_replay(replay_id, dict(trace=trace.model_dump(), rules=body.rules.model_dump(),
                                                    sniffer_capture_id=body.sniffer_capture_id.hex if body.sniffer_capture_id else None))
    return {'id': replay_id, 'provenance': trace.provenance, 'sniffer_capture_id': body.sniffer_capture_id}


@router.get('/replays')
async def list_replays(request: Request):
    return {'replays': request.app.state.probe_service.store.quality_replays()}


@router.get('/replays/{replay_id}/timeline')
async def get_timeline(request: Request, replay_id: UUID, window_s: int = 1):
    if window_s not in (1, 10):
        raise HTTPException(422, 'Cửa sổ phải là 1 hoặc 10 giây')
    saved = request.app.state.probe_service.store.quality_replay(replay_id.hex)
    if saved is None:
        raise HTTPException(404, 'CSI replay không tồn tại')
    trace = saved_trace(saved)
    report = await asyncio.to_thread(timeline, trace,
                                     QualityRules.model_validate(saved['rules']), window_s)
    row = report['windows'][-1] if report['windows'] else None
    quality = quality_result(report, row, unavailable=None if row else 'rx_missing')
    return {'quality': quality, 'source': 'REPLAY', 'session_id': replay_id.hex, 'replay_id': replay_id.hex, 'sniffer_capture_id': saved.get('sniffer_capture_id') if trace.sniffer_source == 'LIVE' else None, **report}
