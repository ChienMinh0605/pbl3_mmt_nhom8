import {useEffect, useState} from 'react';
import {apiRequest} from '../api';
import {number, percent, type ActivitySource} from './DeviceActivityTimeline';

const base = 'device-csi/';
const scenarios = {
  baseline: 'Đối chứng', traffic: 'Tạo lưu lượng', mixed: 'Hoạt động và yên lặng',
  channel: 'Kiểm tra kênh', other: 'Khác',
};
type Device = {id: string; name: string};
export type Capture = {
  id: string; started_at: string; ended_at: string | null; records: number | null; source?: 'LIVE' | 'SIMULATION';
  title?: string | null; scenario?: keyof typeof scenarios | null; devices?: Device[];
  device_ids?: string[] | null; has_raw?: boolean;
};
type SummaryRow = {
  device_id: string; device_name: string; boot_id: string | null; registry_revision: number | null;
  actual_channel: number | null; duration_s: number; observation_time_s: number | null; total_windows: number;
  observed_frames: number | null; observed_bytes: number | null; channel_coverage: number | null;
  avg_frames_per_s: number | null; avg_bytes_per_s: number | null; max_frames_per_s: number | null; max_bytes_per_s: number | null;
  stddev_frames_per_s: number | null; stddev_bytes_per_s: number | null;
  active_windows: number; quiet_windows: number; unknown_windows: number;
  active_fraction: number; quiet_fraction: number; unknown_fraction: number;
};
type ExperimentSummary = {source: ActivitySource; session_id: string; devices: SummaryRow[]};
type Marker = {id: number; elapsed_s: number; label: string};

export default function DeviceCsiExperiments({capture, captureError, mode, usbConnected, canRecord, devices,
  selected, simulationId, replayId, onSimulation, onReplay}: {
  capture: Capture | null | undefined; captureError: string | null | undefined; mode: ActivitySource;
  usbConnected: boolean; canRecord: boolean; devices: Device[]; selected: string[];
  simulationId: string; replayId?: string | null; onSimulation: (id: string) => void; onReplay: () => void;
}) {
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [savedId, setSavedId] = useState('');
  const [title, setTitle] = useState('');
  const [scenario, setScenario] = useState<keyof typeof scenarios>('baseline');
  const [experimentIds, setExperimentIds] = useState<string[] | null>(null);
  const [exportGroup, setExportGroup] = useState('experiment');
  const [label, setLabel] = useState('');
  const [markers, setMarkers] = useState<Marker[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [summary, setSummary] = useState<{key: string; data: ExperimentSummary | null} | null>(null);
  const [summaryIndex, setSummaryIndex] = useState(0);

  async function refresh() {
    const reply = await apiRequest<{captures: Capture[]}>(base + 'captures');
    setCaptures(reply.captures);
  }

  useEffect(() => { void refresh().catch(reason => setError(String(reason))); }, [capture?.id]);

  const available = captures.filter(item => !!item.ended_at
    && (mode === 'SIMULATION' ? item.source === 'SIMULATION' : item.source !== 'SIMULATION'));
  const selectedId = mode === 'SIMULATION' ? simulationId : savedId || (mode === 'REPLAY' ? replayId ?? '' : '');
  const saved = available.find(item => item.id === selectedId);
  const savedDevices = saved?.devices ?? [];
  const availableIds = new Set(savedDevices.map(row => row.id));
  const included = (experimentIds ?? devices.map(row => row.id)).filter(id => devices.some(row => row.id === id));
  const markerPath = capture ? `${base}experiments/q1/${capture.id}/markers` : '';
  useEffect(() => {
    setMarkers([]);
    if (!markerPath) return;
    const abort = new AbortController();
    void apiRequest<{markers: Marker[]}>(markerPath, 'GET', undefined, abort.signal)
      .then(data => { if (!abort.signal.aborted) setMarkers(data.markers); })
      .catch(reason => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => abort.abort();
  }, [markerPath]);

  async function run(operation: () => Promise<void>) {
    setError('');
    setPending(true);
    try { await operation(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setPending(false); }
  }

  const target = exportGroup === 'selected' ? selected.filter(id => availableIds.has(id))
    : availableIds.has(exportGroup) ? [exportGroup] : [];
  const canExport = Boolean(saved && (exportGroup === 'experiment' || exportGroup === 'all' || target.length));
  const params = new URLSearchParams();
  if (mode === 'REPLAY') params.set('replay', 'true');
  if (exportGroup === 'all') params.set('all_devices', 'true');
  for (const id of target) params.append('device_ids', id);
  const sessionPath = saved ? `${base}experiments/q1/${saved.id}` : '';
  const summaryPath = canExport ? `${sessionPath}/summary?${params}` : '';
  useEffect(() => {
    if (!summaryPath) return;
    const abort = new AbortController();
    void apiRequest<ExperimentSummary>(summaryPath, 'GET', undefined, abort.signal)
      .then(data => { if (!abort.signal.aborted) {setSummary({key: summaryPath, data}); setSummaryIndex(0);} })
      .catch(() => { if (!abort.signal.aborted) setSummary({key: summaryPath, data: null}); });
    return () => abort.abort();
  }, [summaryPath]);
  const currentSummary = summary?.key === summaryPath ? summary.data : null;
  const row = currentSummary?.devices[summaryIndex];

  function exportPath(format: string) {
    return `/api/${sessionPath}/export.csv?${new URLSearchParams([...params, ['format', format]])}`;
  }

  return <section className="panel csi-experiments" aria-label="Phiên thực nghiệm">
    <h2>Thực nghiệm và xuất CSV</h2>
    <div className="q1-experiment-columns">
    <section className="q1-experiment-config">
    <h3>Cấu hình</h3>
    {mode !== 'REPLAY' && <form className="q1-experiment-form" onSubmit={event => {
      event.preventDefault();
      void run(async () => {
        const payload = {title, scenario, device_ids: included};
        if (mode === 'SIMULATION') {
          const item = await apiRequest<Capture>(base + 'captures/simulate', 'POST', payload);
          await refresh();
          onSimulation(item.id);
        } else {
          await apiRequest<Capture>(base + 'captures/start', 'POST', payload);
        }
      });
    }}>
      <div className="csi-toolbar">
        <label>Tên thực nghiệm<input value={title} maxLength={100} required disabled={!!capture}
          onChange={event => setTitle(event.target.value)} /></label>
        <label>Kịch bản<select value={scenario} disabled={!!capture} onChange={event => setScenario(event.target.value as keyof typeof scenarios)}>
          {Object.entries(scenarios).map(([value, text]) => <option value={value} key={value}>{text}</option>)}
        </select></label>
        <button className="primary" disabled={pending || !!capture || (devices.length > 0 && !included.length)
          || (mode === 'LIVE' ? !canRecord || !included.length : usbConnected)}>
          {mode === 'LIVE' ? 'Bắt đầu ghi Q1' : 'Chạy mô phỏng Q1'}
        </button>
        {mode === 'LIVE' && <button type="button" className="secondary" disabled={pending || !capture}
          onClick={() => void run(async () => {
            const closed = await apiRequest<Capture>(base + 'captures/stop', 'POST');
            await refresh(); setSavedId(closed.id); setExportGroup('experiment');
          })}>Kết thúc Q1</button>}
      </div>
      {devices.length > 0 && <fieldset className="q1-select-devices" disabled={!!capture}>
        <legend>Thiết bị thực nghiệm</legend>
        {devices.map(row => <label key={row.id}>
          <input type="checkbox" checked={included.includes(row.id)} onChange={event =>
            setExperimentIds(event.target.checked ? [...included, row.id] : included.filter(id => id !== row.id))} />
          {row.name}
        </label>)}
      </fieldset>}
    </form>}
    {capture && <form className="csi-toolbar" onSubmit={event => {
      event.preventDefault();
      void run(async () => {
        const marker = await apiRequest<Marker>(markerPath, 'POST', {label});
        setMarkers(rows => [...rows, marker]); setLabel('');
      });
    }}>
      <p role="status">Đang ghi Q1 · {capture.records} bản tin</p>
      <label>Dấu mốc thao tác<input value={label} onChange={event => setLabel(event.target.value)} maxLength={120} /></label>
      <button className="secondary" disabled={pending || !label.trim()}>Ghi dấu mốc</button>
    </form>}
    {markers.length > 0 && <ul>{markers.map(marker => <li key={marker.id}>{marker.elapsed_s.toFixed(2)} s · {marker.label}</li>)}</ul>}
    {mode === 'REPLAY' && <p className="hint">Chọn một bản ghi để phát lại. Chọn LIVE để bắt đầu ghi mới.</p>}
    </section>
    <section className="q1-experiment-summary">
      <h3>Thống kê</h3>
      {!saved ? <p className="hint">Chọn một phiên đã kết thúc để xem tổng hợp.</p>
        : !canExport ? <p className="hint">Nhóm đang chọn không có thiết bị trong bản ghi.</p>
        : !currentSummary ? <p className="hint">{summary?.key === summaryPath
          ? 'NOT AVAILABLE · Không tải được tổng hợp.' : 'Đang đọc kết quả…'}</p>
        : !row ? <p className="hint">NOT AVAILABLE · Chưa có cửa sổ trong nhóm xuất.</p> : <>
          <p className="hint">Cửa sổ đã đóng · {currentSummary.source}</p>
          <label>Thiết bị và cấu hình<select value={summaryIndex} onChange={event => setSummaryIndex(Number(event.target.value))}>
            {currentSummary.devices.map((item, index) => <option key={index} value={index}>
              {item.device_name} · Kênh {number(item.actual_channel)} · Rev {number(item.registry_revision)}
              {item.boot_id ? ` · Boot ${item.boot_id.slice(-6)}` : ''}
            </option>)}
          </select></label>
          <dl>{[
            ['Thời lượng cửa sổ', number(row.duration_s, ' s')], ['Quan sát hợp lệ', number(row.observation_time_s, ' s')],
            ['Số cửa sổ', number(row.total_windows)], ['Coverage', percent(row.channel_coverage)],
            ['Tổng Frame', number(row.observed_frames)], ['Tổng Byte', number(row.observed_bytes)],
            ['TB Frame/s · Byte/s', `${number(row.avg_frames_per_s)} · ${number(row.avg_bytes_per_s)}`],
            ['Max Frame/s · Byte/s', `${number(row.max_frames_per_s)} · ${number(row.max_bytes_per_s)}`],
            ['Độ lệch chuẩn Frame/s · Byte/s', `${number(row.stddev_frames_per_s)} · ${number(row.stddev_bytes_per_s)}`],
            ['OBSERVED_ACTIVE', `${row.active_windows} · ${percent(row.active_fraction)}`],
            ['NO_OBSERVED_ACTIVITY', `${row.quiet_windows} · ${percent(row.quiet_fraction)}`],
            ['UNKNOWN', `${row.unknown_windows} · ${percent(row.unknown_fraction)}`],
          ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        </>}
    </section>
    <section className="q1-experiment-export">
    <h3>Xuất dữ liệu</h3>
    <div className="csi-toolbar">
      <label>Lịch sử thực nghiệm<select value={selectedId} disabled={!!capture || pending} onChange={event => {
        const id = event.target.value;
        if (mode === 'SIMULATION') onSimulation(id); else setSavedId(id);
        setExportGroup('experiment');
      }}>
        <option value="">Chọn phiên Q1</option>
        {available.map(item => <option key={item.id} value={item.id}>
          {item.title || item.started_at} · {item.id.slice(0, 8)}
        </option>)}
      </select></label>
      {mode !== 'SIMULATION' && <button type="button" className="secondary" disabled={!saved || !!capture || usbConnected || pending}
        onClick={() => void run(async () => {
          await apiRequest(base + 'replay', 'POST', {capture_id: saved!.id, speed: 4});
          onReplay();
        })}>Phát lại Q1</button>}
      {saved && <label>Thiết bị xuất CSV<select value={exportGroup} onChange={event => setExportGroup(event.target.value)}>
        <option value="experiment">Theo thiết bị thực nghiệm</option>
        <option value="all">Tất cả thiết bị trong bản ghi</option>
        <option value="selected">Nhóm đang chọn trên timeline</option>
        {savedDevices.map(row => <option value={row.id} key={row.id}>{row.name}</option>)}
      </select></label>}
    </div>
    {saved?.scenario && <p className="hint">Kịch bản {scenarios[saved.scenario]} · Nguồn bản ghi {saved.source ?? 'LIVE'}</p>}
    {canExport && <div className="csi-toolbar q1-csv-links">
      <a href={exportPath('detail')} download>Xuất chi tiết Q1</a>
      <a href={exportPath('summary')} download>Xuất tổng hợp Q1</a>
      {saved?.has_raw && <a href={exportPath('raw')} download>Xuất bản ghi UART Q1</a>}
    </div>}
    </section>
    </div>
    {error && <p role="alert" className="alert error">{error}</p>}
    {captureError && <p role="alert" className="alert error">Lỗi ghi Q1 · {captureError}</p>}
  </section>;
}
