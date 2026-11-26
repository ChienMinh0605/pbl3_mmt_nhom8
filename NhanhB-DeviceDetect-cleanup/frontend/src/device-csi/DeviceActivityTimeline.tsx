import {useEffect, useMemo, useRef, useState} from 'react';
import {apiRequest} from '../api';

export type ActivitySource = 'LIVE' | 'SIMULATION' | 'REPLAY';
export type ActivityState = 'OBSERVED_ACTIVE' | 'NO_OBSERVED_ACTIVITY' | 'UNKNOWN';
export type ActivityDevice = {
  id: string; name: string; channel: number; state: ActivityState;
  data_valid: boolean; last_seen_us: number | null; last_observed_channel: number | null;
  observed_frames: number | null; observed_bytes: number | null; observation_time_s: number | null;
  channel_coverage: number | null; frames_per_s: number | null; bytes_per_s: number | null;
  rssi_max_dbm: number | null; reasons: string[];
  frame_types?: {management: number; data: number; control: number} | null;
  tx_frames?: number | null; rx_frames?: number | null; block_ack_frames?: number | null;
  frame_analysis?: Record<'management' | 'data' | 'control' | 'tx' | 'rx',
    {count: number | null; fraction: number | null; frames_per_s: number | null}>;
};
type ClosedWindow = {
  window_start_us: number; window_end_us: number; channel: number | null; devices: ActivityDevice[];
  boot_id?: string | null; registry_revision?: number | null;
};
export type ActivityPoint = {device: ActivityDevice; channel: number | null; start: number; end: number;
  registryRevision: number | null};
type History = {
  source: ActivitySource; session_id: string; window_start_us: number; window_end_us: number; windows: ClosedWindow[];
};
type Metric = 'frames_per_s' | 'bytes_per_s' | 'rssi_max_dbm' | 'state';
type Slot = {start: number; end: number; channel?: number | null; device?: ActivityDevice;
  epoch?: string; registryRevision?: number | null};
type Trace = {device: ActivityDevice; slots: Slot[]; color: string};
const metrics: Record<Metric, {label: string; unit: string}> = {
  frames_per_s: {label: 'Frame/s', unit: 'frame/s'},
  bytes_per_s: {label: 'Byte/s', unit: 'byte/s'},
  rssi_max_dbm: {label: 'RSSI', unit: 'dBm'},
  state: {label: 'Activity State', unit: ''},
};
const colors = ['#24717d', '#8a51a5', '#aa5f20', '#2958a9'];
const SECOND = 1_000_000;
const SLOT = 10 * SECOND;

export function number(value: number | null | undefined, unit = '') {
  return value == null || !Number.isFinite(value) ? 'NOT AVAILABLE' : `${Number(value.toFixed(2))}${unit}`;
}

export function percent(value: number | null | undefined) {
  return number(value == null ? null : value * 100, '%');
}

function timeLabel(us: number) {
  const seconds = Math.floor(us / SECOND);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

function windowLabel({start, end}: Slot) {
  return `[${timeLabel(start)}, ${timeLabel(end)})`;
}

function measured(slot: Slot, metric: Metric) {
  const row = slot.device;
  if (!row?.data_valid || row.state === 'UNKNOWN' || metric === 'state') return null;
  return row[metric];
}

function LinePlot({traces, start, end, metric, onPick}: {
  traces: Trace[]; start: number; end: number; metric: Metric;
  onPick: (point: {id: string; tick: number}) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const hitTargets = useRef<{id: string; tick: number; x: number; y: number}[]>([]);
  const lines = useMemo(() => traces.map(trace => {
    const runs: {tick: number; value: number}[][] = [];
    let previous = Number.NEGATIVE_INFINITY;
    let epoch: string | undefined;
    for (const slot of trace.slots) {
      const value = measured(slot, metric);
      if (value == null) continue;
      if (slot.start !== previous || slot.epoch !== epoch) runs.push([]);
      runs[runs.length - 1].push({tick: (slot.start + slot.end) / 2, value});
      previous = slot.end;
      epoch = slot.epoch;
    }
    return {id: trace.device.id, color: trace.color, runs};
  }), [traces, metric]);
  const points = lines.flatMap(line => line.runs.flat());
  const segments = lines.reduce((count, line) => count + line.runs.length, 0);

  useEffect(() => {
    const element = canvas.current;
    const ctx = element?.getContext('2d');
    if (!element || !ctx) return;
    const values = lines.flatMap(line => line.runs.flat().map(point => point.value));
    function draw() {
      if (!element || !ctx) return;
      const width = element.clientWidth, height = element.clientHeight;
      if (!width || !height) return;
      const dpr = window.devicePixelRatio || 1;
      element.width = width * dpr;
      element.height = height * dpr;
      ctx.scale(dpr, dpr);
      const left = 52, right = width - 12, top = 16, bottom = height - 28;
      const x = (tick: number) => left + (tick - start) * (right - left) / (end - start || 1);
      const rate = metric !== 'rssi_max_dbm';
      let low = rate ? 0 : values.length ? Math.min(...values) : -100;
      let high = values.length ? Math.max(...values) : rate ? 1 : 0;
      if (high === low) {
        high += rate ? 1 : 2;
        if (!rate) low -= 2;
      }
      const y = (value: number) => bottom - (value - low) * (bottom - top) / (high - low);
      ctx.font = '12px system-ui';
      ctx.fillStyle = '#526775';
      ctx.strokeStyle = '#d8e3e8';
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const value = low + (high - low) * i / 4;
        ctx.beginPath();
        ctx.moveTo(left, y(value));
        ctx.lineTo(right, y(value));
        ctx.stroke();
        if (values.length) ctx.fillText(number(value), left - 6, y(value), left - 10);
      }
      const slots = Math.max(1, Math.round((end - start) / SLOT));
      const tickStep = Math.ceil(slots / (width < 480 ? 2 : 5));
      for (let i = 0; i < slots; i += tickStep) {
        ctx.textAlign = i ? 'center' : 'left';
        ctx.fillText(timeLabel(start + i * SLOT), x(start + i * SLOT), bottom + 15);
      }
      ctx.textAlign = 'right';
      ctx.fillText(timeLabel(end), x(end), bottom + 15);
      ctx.lineWidth = 2;
      hitTargets.current = [];
      for (const line of lines) {
        ctx.strokeStyle = ctx.fillStyle = line.color;
        for (const run of line.runs) {
          ctx.beginPath();
          for (const [index, point] of run.entries()) {
            if (index) ctx.lineTo(x(point.tick), y(point.value));
            else ctx.moveTo(x(point.tick), y(point.value));
          }
          ctx.stroke();
          for (const point of run) {
            hitTargets.current.push({id: line.id, tick: point.tick - SLOT / 2, x: x(point.tick), y: y(point.value)});
            ctx.beginPath();
            ctx.arc(x(point.tick), y(point.value), run.length < 40 ? 2.6 : 1.4, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
    }
    const observer = new ResizeObserver(draw);
    observer.observe(element);
    draw();
    return () => observer.disconnect();
  }, [lines, start, end, metric]);

  return <canvas ref={canvas} role="img" aria-label={`${metrics[metric].label}: ${points.length} điểm, ${segments} đoạn`}
    onClick={event => {
      const bounds = event.currentTarget.getBoundingClientRect();
      let nearest: (typeof hitTargets.current)[number] | undefined;
      let distance = 16;
      for (const point of hitTargets.current) {
        const offset = Math.hypot(point.x - (event.clientX - bounds.left), point.y - (event.clientY - bounds.top));
        if (offset < distance) { nearest = point; distance = offset; }
      }
      if (nearest) onPick({id: nearest.id, tick: nearest.tick});
    }}/>;
}

export default function DeviceActivityTimeline({source, sessionId, devices, lastWindowEnd, selected, onSelect, onPoint}: {
  source: ActivitySource; sessionId: string | null; devices: ActivityDevice[]; lastWindowEnd: number | null;
  selected: string[]; onSelect: (ids: string[]) => void; onPoint: (point: ActivityPoint) => void;
}) {
  const [metric, setMetric] = useState<Metric>('frames_per_s');
  const [minutes, setMinutes] = useState(1);
  const [response, setResponse] = useState<{key: string; history: History | null} | null>(null);
  const [focused, setFocused] = useState<{id: string; tick: number} | null>(null);
  const query = sessionId && devices.length ? new URLSearchParams([
    ['source', source], ['session_id', sessionId], ['lookback_s', String(minutes * 60)],
    ...devices.map(row => ['device_ids', row.id]),
  ]).toString() : '';
  useEffect(() => {
    if (!query) return;
    const abort = new AbortController();
    void apiRequest<History>(`device-csi/activity/history?${query}`, 'GET', undefined, abort.signal)
      .then(history => { if (!abort.signal.aborted) setResponse({key: query, history}); })
      .catch(() => { if (!abort.signal.aborted) setResponse({key: query, history: null}); });
    return () => abort.abort();
  }, [query, lastWindowEnd]);
  const history = response?.key === query ? response.history : null;
  const start = history?.window_start_us ?? 0, end = history?.window_end_us ?? 0;
  const traces = useMemo(() => {
    const byStart = new Map(history?.windows.map(window => [window.window_start_us, window]));
    return devices.filter(device => selected.includes(device.id)).map((device, index): Trace => ({
      device, color: colors[index % colors.length],
      slots: Array.from({length: Math.floor((end - start) / SLOT)}, (_, slot) => {
        const tick = start + slot * SLOT;
        const window = byStart.get(tick);
        return {start: tick, end: tick + SLOT, channel: window?.channel, registryRevision: window?.registry_revision,
          epoch: window && `${window.boot_id}:${window.registry_revision}:${window.channel}`,
          device: window?.devices.find(row => row.id === device.id)};
      }),
    }));
  }, [devices, selected, history, start, end]);
  const view = !traces.length ? 'empty' : traces.length === 1 ? 'single' : traces.length < 5 ? 'multi' : 'heatmap';
  const detailTrace = traces.find(trace => trace.device.id === focused?.id);
  const detail = detailTrace?.slots.find(slot => slot.start === focused?.tick);
  const row = detail?.device;
  const values = traces.flatMap(trace => trace.slots.map(slot => measured(slot, metric)))
    .filter((value): value is number => value != null);
  const low = values.length ? Math.min(...values) : null, high = values.length ? Math.max(...values) : null;

  function pick(point: {id: string; tick: number}) {
    setFocused(point);
    const slot = traces.find(trace => trace.device.id === point.id)?.slots.find(item => item.start === point.tick);
    if (slot?.device) onPoint({device: slot.device, start: slot.start, end: slot.end, channel: slot.channel ?? null,
      registryRevision: slot.registryRevision ?? null});
  }

  return <section className="panel q1-timeline" aria-label="Q1 Device Activity Timeline" data-view={view}>
    <h2>Dòng thời gian hoạt động</h2>
    <div className="csi-toolbar q1-timeline-controls">
      <label>Chỉ số<select value={metric} onChange={event => setMetric(event.target.value as Metric)}>
        {Object.entries(metrics).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}
      </select></label>
      <label>Khoảng thời gian<select value={minutes} onChange={event => {
        setMinutes(Number(event.target.value)); setFocused(null);
      }}>{[1, 5, 15, 30].map(value => <option key={value} value={value}>{value} phút</option>)}</select></label>
      <button type="button" className="secondary" onClick={() => onSelect(devices.map(device => device.id))}>Chọn tất cả</button>
      <button type="button" className="secondary" onClick={() => onSelect([])}>Bỏ chọn tất cả</button>
    </div>
    <div className="q1-select-devices">
      {devices.map(device => <label key={device.id}>
        <input type="checkbox" checked={selected.includes(device.id)} onChange={event =>
          onSelect(event.target.checked ? [...selected, device.id] : selected.filter(id => id !== device.id))} />
        {device.name}
      </label>)}
    </div>
    {!traces.length ? <p className="hint">Chọn thiết bị để xem dòng thời gian.</p>
      : !traces[0].slots.length ? <p className="hint" role="status">{response?.key === query && !history
        ? 'Không đọc được lịch sử Q1.' : 'Chưa có cửa sổ hoàn thành.'}</p> : <>
        <p className="hint">{source} · {metrics[metric].unit || 'trạng thái'} · 10 giây mỗi cửa sổ · mm:ss từ đầu phiên</p>
        {view !== 'heatmap' && metric !== 'state' &&
          <LinePlot traces={traces} start={start} end={end} metric={metric} onPick={pick}/>}
        {view === 'heatmap' && metric !== 'state' && low != null && <p className="hint">
          Cường độ ô đo được · {number(low)} đến {number(high, ` ${metrics[metric].unit}`)}
        </p>}
        {traces.map(trace => <div className="q1-timeline-row" key={trace.device.id}>
          <span style={{borderInlineStartColor: trace.color}} title={trace.device.name}>{trace.device.name}</span>
          <div className="q1-timeline-strip" role="group" tabIndex={0}
            aria-label={`Cửa sổ của ${trace.device.name}. Dùng phím mũi tên để xem chi tiết.`}
            onKeyDown={event => {
              const index = trace.slots.findIndex(slot => slot.start === focused?.tick && focused?.id === trace.device.id);
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? trace.slots.length - 1
                : event.key === 'ArrowRight' ? Math.min(trace.slots.length - 1, index + 1)
                : event.key === 'ArrowLeft' ? Math.max(0, index - 1) : null;
              if (next != null) { event.preventDefault(); setFocused({id: trace.device.id, tick: trace.slots[next].start}); }
              if ((event.key === 'Enter' || event.key === ' ') && index >= 0) {
                event.preventDefault(); pick({id: trace.device.id, tick: trace.slots[index].start});
              }
            }}>
            {trace.slots.map(slot => {
              const value = measured(slot, metric);
              const state = slot.device?.state;
              const shade = view === 'heatmap' && state === 'OBSERVED_ACTIVE' && value != null && low != null && high != null
                ? `rgba(21, 121, 80, ${.25 + .75 * (high === low ? 1 : (value - low) / (high - low))})` : undefined;
              const chosen = focused?.id === trace.device.id && focused.tick === slot.start;
              return <button key={slot.start} type="button" tabIndex={-1}
                style={shade ? {background: shade} : undefined}
                className={`q1-slot ${state?.toLowerCase() ?? 'missing'}${chosen ? ' selected' : ''}`}
                aria-label={`${windowLabel(slot)} · ${state ?? 'NOT AVAILABLE'}`}
                onPointerEnter={() => setFocused({id: trace.device.id, tick: slot.start})}
                onClick={() => pick({id: trace.device.id, tick: slot.start})} />;
            })}
          </div>
        </div>)}
        <div className="q1-timeline-times"><span>{timeLabel(start)}</span><span>{timeLabel(end)}</span></div>
        <ul className="q1-timeline-key" aria-label="Chú giải trạng thái">
          <li className="observed_active">OBSERVED_ACTIVE</li><li className="no_observed_activity">NO_OBSERVED_ACTIVITY</li>
          <li className="unknown">UNKNOWN</li><li className="missing">NOT AVAILABLE</li>
        </ul>
        {detail && <div className="q1-timeline-tooltip" role="tooltip">
          <strong>{detailTrace?.device.name} · {windowLabel(detail)} · {row?.state ?? 'NOT AVAILABLE'}</strong>
          <dl>{[
            ['Frame', number(row?.observed_frames)], ['Byte', number(row?.observed_bytes)],
            ['Frame/s', number(row?.frames_per_s)], ['Byte/s', number(row?.bytes_per_s)],
            ['RSSI khung thu', number(row?.rssi_max_dbm, ' dBm')], ['Kênh thu', number(detail.channel)],
            ['Thời gian quan sát', number(row?.observation_time_s, ' s')], ['Độ phủ', percent(row?.channel_coverage)],
            ...(row?.frame_types ? [['Management', number(row.frame_types.management)],
              ['Data', number(row.frame_types.data)], ['Control', number(row.frame_types.control)]] : []),
          ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        </div>}
      </>}
  </section>;
}
