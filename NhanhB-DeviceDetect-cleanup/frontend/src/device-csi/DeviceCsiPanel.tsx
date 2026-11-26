import { useEffect, useRef, useState, type FormEvent} from 'react';
import {createPortal} from 'react-dom';
import {apiRequest} from '../api';
import DeviceCsiExperiments, {type Capture} from './DeviceCsiExperiments';
import DeviceActivityTimeline, {number, percent, type ActivityDevice, type ActivitySource, type ActivityState, type ActivityPoint} from './DeviceActivityTimeline';

const path = 'device-csi/';
type Mode = ActivitySource;
type ActivityWindow = {window_start_us: number | null; window_end_us: number | null; devices: ActivityDevice[];
  registry_revision?: number | null; diagnostics?: SnifferDiagnostics};
type SnifferDiagnostics = {connection: string; port: string | null; baudrate: number | null; firmware_version: string | null;
  requested_baudrate: number | null;
  capture_mode: string | null; channel: number | null; heartbeat_age_s: number | null; registered_devices: number | null;
  management_frames: number | null; data_frames: number | null; control_frames: number | null; unattributed_frames: number | null;
  activity_records_received: number | null; parsing_errors: number | null; last_received_at: string | null;
  unregistered_frames?: number | null; invalid_frames?: number | null; off_channel_frames?: number | null;
  rx_callbacks?: number | null; bytes_written?: number | null;
  error: string | null; reasons: string[]; scan_mode: string | null; queue_drops: number | null; serial_errors?: number | null};
type Activity = ActivityWindow & {source: Mode | null; session_id: string | null; channel: number | null;
  replay_capture_id: string | null; diagnostics?: SnifferDiagnostics; capture: Capture | null; capture_error: string | null;
  overview: {registered: number; synced: number | null; states: Record<ActivityState, number>}};
type RegistryStatus = 'SYNCED' | 'PENDING' | 'OFFLINE' | 'SYNC_FAILED';
type RegistryDevice = {id: string; name: string; channel: number; wifi_mac: string | null};
type RegistryConfiguration = {
  state: RegistryStatus; supported: boolean | null; desired_channel: number | null;
  applied_channel: number | null; registry_revision: number | null; firmware_count: number | null;
  channel_min: number | null; channel_max: number | null; error: string | null;
};
type Registry = {devices: RegistryDevice[]; configuration: RegistryConfiguration};
type Port = {device: string};
const states: ActivityState[] = ['OBSERVED_ACTIVE', 'NO_OBSERVED_ACTIVITY', 'UNKNOWN'];
const columns = [
  ['name', 'Thiết bị'], ['channel', 'Channel'], ['state', 'State'], ['frames_per_s', 'Frame/s'],
  ['bytes_per_s', 'Byte/s'], ['rssi_max_dbm', 'RSSI'], ['channel_coverage', 'Coverage'],
] as const;
type SortKey = (typeof columns)[number][0];


const snifferReasonText: Record<string, string> = {
  SNIFFER_DISCONNECTED: 'Chưa có kết nối USB đang hoạt động.',
  AWAITING_ACTIVITY_HEARTBEAT: 'Chờ heartbeat ở tốc độ UART đã chọn. Kiểm tra baud và firmware nếu chưa nhận bản tin.',
  FIRMWARE_MODE_UNSUPPORTED: 'Board đang chạy Probe v1. Device Activity cần firmware activity v2 trên kênh cố định.',
  HEARTBEAT_STALE: 'Heartbeat đã quá hạn.',
  NO_ACTIVITY_RECORDS: 'Đã nhận heartbeat nhưng chưa nhận bản tin activity_sample.',
  CHANNEL_MISMATCH: 'Kênh sniffer khác kênh của ít nhất một thiết bị đăng ký.',
  NO_REGISTERED_DEVICE_MATCH: 'Chưa thấy MAC Wi‑Fi đã đăng ký trên kênh đang thu. Kiểm tra MAC trên điện thoại, registry và cấu hình firmware.',
};

const deviceReasonText: Record<string, string> = {
  wrong_channel: 'Sai kênh',
  firmware_mode_unsupported: 'Cần firmware Device Activity',
  firmware_binding_unverified: 'Chưa thấy MAC đã đăng ký',
  heartbeat_stale: 'Heartbeat quá hạn',
  sniffer_disconnected: 'Chưa có kết nối sniffer',
  warming_up: 'Đang chờ đủ cửa sổ 10 s',
  awaiting_activity_heartbeat: 'Chưa nhận heartbeat Activity',
  insufficient_coverage: 'Thiếu thời gian thu hợp lệ',
  capture_errors: 'Có lỗi thu hoặc UART',
  heartbeat_gap: 'Heartbeat bị gián đoạn',
  sequence_gap: 'Thiếu bản tin UART',
  excess_unattributed_frames: 'Quá nhiều frame không gán được',
  invalid_line: 'Bản tin UART lỗi định dạng',
  capture_epoch_changed: 'Nguồn thu khởi động lại hoặc có gián đoạn',
  registry_not_synced: 'Đang chờ firmware xác nhận registry',
  registry_revision_mismatch: 'Bản tin thuộc phiên bản registry khác',
  activity_crosses_window_boundary: 'Mẫu cắt qua ranh giới cửa sổ',
};

const macSeparators = /[:\s-]/g;

function formatMacDigits(digits: string) {
  return digits.toUpperCase().replace(/(..)/g, '$1:').slice(0, 17);
}

function readMacDigits(value: string) {
  const mac = value.trim();
  if (/^[0-9a-f]{0,12}$/i.test(mac)) return mac;
  if (/^(?:[0-9a-f]{2}(?:\s*[:-]\s*|\s+)){1,5}[0-9a-f]{0,2}$/i.test(mac)) return mac.replace(macSeparators, '');
  return null;
}

function normalizeMac(value: string) {
  const digits = readMacDigits(value);
  return digits?.length === 12 ? formatMacDigits(digits) : null;
}

export default function DeviceCsiPanel() {
  const [mode, setMode] = useState<Mode>(() => {
    const source = sessionStorage.getItem('device-csi.source');
    return source === 'SIMULATION' || source === 'REPLAY' ? source : 'LIVE';
  });
  const [simulationId, setSimulationId] = useState(() => sessionStorage.getItem('device-activity.simulation') ?? '');
  const [savedSimulation, setSavedSimulation] = useState<Activity | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [selection, setSelection] = useState<{scope: string; ids: string[]} | null>(null);
  const [detailId, setDetailId] = useState('');
  const [point, setPoint] = useState<{scope: string; value: ActivityPoint} | null>(null);
  const [tableSearch, setTableSearch] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [channelFilter, setChannelFilter] = useState('');
  const [sort, setSort] = useState<{key: SortKey; ascending: boolean}>({key: 'name', ascending: true});
  const [headerStatus, setHeaderStatus] = useState<HTMLElement | null>(null);
  useEffect(() => setHeaderStatus(document.getElementById('q1-header-status')), []);
  const [search, setSearch] = useState('');
  const [ports, setPorts] = useState<Port[]>([]);
  const [port, setPort] = useState('');
  const [baud, setBaud] = useState('auto');
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [requestedChannel, setRequestedChannel] = useState<number | null>(null);
  const [savingRegistry, setSavingRegistry] = useState(false);
  const [registryError, setRegistryError] = useState(false);
  const [name, setName] = useState(''), [mac, setMac] = useState(''), [channel, setChannel] = useState(6);
  const [macError, setMacError] = useState('');
  const macInput = useRef<HTMLInputElement>(null);
  const [consent, setConsent] = useState(false);
  const [actionError, setActionError] = useState('');
  const [activityError, setActivityError] = useState(false);

  useEffect(() => {
    sessionStorage.setItem('device-csi.source', mode);
    sessionStorage.setItem('device-activity.simulation', simulationId);
  }, [mode, simulationId]);

  useEffect(() => {
    if (mode !== 'SIMULATION' || !simulationId) return;
    const abort = new AbortController();
    void apiRequest<Activity>(`${path}state?simulation_id=${simulationId}`, 'GET', undefined, abort.signal)
      .then(data => { if (!abort.signal.aborted) setSavedSimulation(data); })
      .catch(reason => { if (!abort.signal.aborted) { setSavedSimulation(null); setActionError(String(reason)); } });
    return () => abort.abort();
  }, [mode, simulationId]);

  useEffect(() => {
    const abort = new AbortController();
    let pending = false;
    async function poll() {
      if (pending) return;
      pending = true;
      const signal = abort.signal;
      const requests = [
        apiRequest<Activity>(path + 'state', 'GET', undefined, signal).then(data => {
          if (!signal.aborted) { setActivity(data); setActivityError(false); }
        }).catch(() => { if (!signal.aborted) { setActivity(null); setActivityError(true); } }),
      ];
      if (mode === 'LIVE') requests.push(apiRequest<Port[]>('ports', 'GET', undefined, signal).then(data => {
        if (!signal.aborted) { setPorts(data); setPort(value => data.some(item => item.device === value) ? value : data[0]?.device ?? ''); }
      }).catch(() => { if (!signal.aborted) setPorts([]); }));
      if (mode !== 'REPLAY') requests.push(apiRequest<Registry>(path + 'registry?details=true', 'GET', undefined, signal)
        .then(data => { if (!signal.aborted) { setRegistry(data); setRegistryError(false); } })
        .catch(() => { if (!signal.aborted) setRegistryError(true); }));
      await Promise.allSettled(requests);
      pending = false;
    }
    void poll();
    const timer = window.setInterval(poll, 1000);
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [mode]);

  async function act(operation: () => Promise<void>) {
    setActionError('');
    try { await operation(); } catch (error) { setActionError(error instanceof Error ? error.message : 'Không thực hiện được thao tác'); }
  }
  function editMac(input: HTMLInputElement, event?: InputEvent) {
    const {value} = input;
    setMacError('');
    if (event?.isComposing) {
      setMac(value);
      return;
    }

    const inputType = event?.inputType;
    const previousDigits = mac.replace(/:/g, '');
    const editedDigits = value.replace(macSeparators, '');
    const directEdit = (inputType === 'insertText' && event?.data?.length === 1) || inputType?.startsWith('delete');
    // Editing a formatted value can move its existing separators out of place.
    const maskedEdit = directEdit && mac === formatMacDigits(previousDigits) && /^[0-9a-f]{0,12}$/i.test(editedDigits);
    let digits = maskedEdit ? editedDigits : readMacDigits(value);
    if (digits === null) {
      setMac(value);
      return;
    }

    let offset = value.slice(0, input.selectionStart ?? value.length).replace(macSeparators, '').length;
    // If deletion hit a separator, remove the adjacent digit in the same direction.
    if (maskedEdit && digits === previousDigits && value.length < mac.length) {
      if (inputType === 'deleteContentBackward' && offset > 0) {
        offset--;
        digits = digits.slice(0, offset) + digits.slice(offset + 1);
      } else if (inputType === 'deleteContentForward') {
        digits = digits.slice(0, offset) + digits.slice(offset + 1);
      }
    }

    const formatted = formatMacDigits(digits);
    if (formatted !== value) {
      const caret = Math.min(offset + Math.floor(offset / 2), formatted.length);
      input.value = formatted;
      input.setSelectionRange(caret, caret);
    }
    setMac(formatted);
  }

  function clearRegistration() {
    setEditing(null);
    setName('');
    setMac('');
    setMacError('');
    setConsent(false);
  }

  async function updateRegistry(operation: () => Promise<void>) {
    setSavingRegistry(true);
    try {
      await act(async () => {
        await operation();
        setRegistry(await apiRequest<Registry>(path + 'registry?details=true'));
        setRegistryError(false);
      });
    } finally {
      setSavingRegistry(false);
    }
  }

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedMac = normalizeMac(mac);
    if (!normalizedMac || normalizedMac === '00:00:00:00:00:00' || (Number.parseInt(normalizedMac.slice(0, 2), 16) & 1) !== 0) {
      setMacError(normalizedMac
        ? 'Dùng địa chỉ MAC Wi-Fi riêng của thiết bị (unicast).'
        : 'Nhập đủ 12 ký tự từ 0–9 hoặc A–F, ví dụ 02:11:22:33:44:55.');
      macInput.current?.focus();
      return;
    }
    setMac(normalizedMac);
    await updateRegistry(async () => {
      await apiRequest(path + (editing ? `registry/${editing}` : 'registry'), editing ? 'PATCH' : 'POST',
        {name, mac: normalizedMac, channel, consent});
      clearRegistration();
    });
  }
  function chooseSource(source: Mode) {
    setMode(source);
    setActionError('');
  }

  const liveActivity = activity?.source == null || activity.source === 'LIVE' ? activity : null;
  const displayedActivity = mode === 'LIVE' ? liveActivity : mode === 'REPLAY'
    ? activity?.source === 'REPLAY' ? activity : null
    : simulationId ? savedSimulation?.session_id === simulationId ? savedSimulation : null
      : activity?.source === 'SIMULATION' ? activity : null;
  const devices = displayedActivity?.devices ?? [];
  const activitySessionId = displayedActivity?.session_id ?? null;
  const scope = `${mode}:${activitySessionId ?? ''}`;
  const selected = selection?.scope === scope ? selection.ids : devices.map(row => row.id);
  const historical = point?.scope === scope ? point.value : null;
  const windowStart = historical?.start ?? displayedActivity?.window_start_us;
  const windowEnd = historical?.end ?? displayedActivity?.window_end_us;
  const detail = historical?.device ?? devices.find(row => row.id === detailId) ?? devices[0];
  const tableRows = devices.filter(row => row.name.toLocaleLowerCase().includes(tableSearch.trim().toLocaleLowerCase())
    && (!stateFilter || row.state === stateFilter) && (!channelFilter || String(row.channel) === channelFilter))
    .sort((a, b) => {
      const left = a[sort.key], right = b[sort.key];
      if (left == null || right == null) return Number(left == null) - Number(right == null);
      const order = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right), 'vi');
      return sort.ascending ? order : -order;
    });
  const tableChannels = [...new Set(devices.map(row => row.channel))].sort((a, b) => a - b);
  const diagnostics = mode === 'LIVE' ? liveActivity?.diagnostics : displayedActivity?.diagnostics;
  const configuration = registry?.configuration;
  const registryStatus = configuration?.supported === false || diagnostics?.capture_mode === 'PROBE_BASELINE'
    ? 'UNSUPPORTED_FIRMWARE' : configuration?.state ?? 'OFFLINE';
  const canEditRegistry = !savingRegistry && activity?.source !== 'SIMULATION'
    && activity?.source !== 'REPLAY' && registryStatus !== 'UNSUPPORTED_FIRMWARE';
  const displayedChannel = requestedChannel ?? configuration?.desired_channel ?? configuration?.applied_channel ?? 6;
  const query = search.trim().toLowerCase();
  const registryRows = registry?.devices.filter(row => [row.name, row.wifi_mac ?? '', String(row.channel)]
    .some(value => value.toLowerCase().includes(query))) ?? [];
  const lastReceived = diagnostics?.last_received_at
    ? new Date(diagnostics.last_received_at).toLocaleString('vi-VN') : 'NOT AVAILABLE';
  const modeText = {LIVE: 'LIVE · Nguồn hiện tại', SIMULATION: 'SIMULATION · Mô phỏng', REPLAY: 'REPLAY · Phát lại'}[mode];
  const overview = displayedActivity?.overview;
  const connection = diagnostics?.connection ?? 'UNKNOWN';
  const actualChannel = displayedActivity?.channel;
  const currentChannel = diagnostics?.channel ?? actualChannel;
  const stale = diagnostics?.reasons.includes('HEARTBEAT_STALE');
  const latestStart = displayedActivity?.window_start_us;
  const latestEnd = displayedActivity?.window_end_us;
  const usbConnected = Boolean(activity?.diagnostics?.port);

  function syncState(row: {id: string; channel: number}) {
    if (mode !== 'LIVE') return 'NOT AVAILABLE';
    if (registryStatus === 'UNSUPPORTED_FIRMWARE') return registryStatus;
    const device = registry?.devices.find(item => item.id === row.id);
    const matching = row.channel === configuration?.applied_channel;
    if (!device?.wifi_mac && matching) return 'PENDING';
    if (configuration?.state === 'SYNCED' && !matching) return 'OFFLINE';
    return configuration?.state ?? 'OFFLINE';
  }

  return <div className="csi-dashboard">
    <h1 className="q1-screen-reader">Device Activity Monitoring</h1>
    {headerStatus && createPortal(<div className="q1-status-strip" aria-label="Trạng thái nguồn ESP32">
      <span className={`q1-board-state ${mode === 'LIVE' && connection === 'connected' && !stale ? 'online' : ''}`}>
        ESP32-C3 · {mode === 'LIVE' ? stale ? 'heartbeat quá hạn' : connection : 'ngoài LIVE'}</span>
      <strong data-testid="csi-mode">{modeText}</strong>
      <span>Kênh thu {number(currentChannel)}</span>
    </div>, headerStatus)}
    <section className="q1-kpi" aria-label="Tổng quan Q1">
      <dl>
        <div><dt>Thiết bị đăng ký</dt><dd>{number(overview?.registered)}</dd></div>
        {states.map(state => <div key={state} className={state.toLowerCase()}><dt>{state}</dt>
          <dd>{number(overview?.states[state])}</dd></div>)}
        <div><dt>Đã đồng bộ</dt><dd>{number(overview?.synced)}</dd></div>
        <div><dt>Cửa sổ hiện tại</dt><dd title="Thời gian từ đầu phiên" className="q1-kpi-window">
          {latestStart == null || latestEnd == null ? 'NOT AVAILABLE'
            : `[${number(latestStart / 1e6)}, ${number(latestEnd / 1e6)}) s`}</dd></div>
      </dl>
    </section>
    {(activityError || actionError) && <p role="alert" className="alert error">
      {activityError && 'Không kết nối được API Device Activity. '}{actionError}
    </p>}
    <div className="q1-columns">
    <div className="q1-column">
    <section className="panel csi-evidence" aria-label="Nguồn dữ liệu">
      <h2>Kết nối ESP32-C3</h2>
      <div className="csi-toolbar">
        <label>Nguồn dữ liệu<select value={mode} onChange={event => chooseSource(event.target.value as Mode)}>
          <option value="LIVE">LIVE</option><option value="REPLAY">REPLAY</option><option value="SIMULATION">SIMULATION</option>
        </select></label>
      </div>
      {mode === 'LIVE' && <>
        <div className="csi-toolbar csi-connection">
          <label>USB sniffer <select value={port} onChange={event => setPort(event.target.value)}><option value="">Chưa chọn</option>
            {ports.map(item => <option key={item.device}>{item.device}</option>)}</select></label>
          <label>Tốc độ UART<select value={baud} onChange={event => setBaud(event.target.value)}>
            <option value="auto">Tự dò</option><option value="460800">460800</option><option value="921600">921600</option>
          </select></label>
          <button className="primary" disabled={!port || !!activity?.capture || (port === diagnostics?.port &&
            (baud === 'auto' ? diagnostics.requested_baudrate === null : Number(baud) === diagnostics.requested_baudrate))} onClick={() => void act(async () => {
            await apiRequest(path + 'connect', 'POST', {port, baud: baud === 'auto' ? null : Number(baud)}); chooseSource('LIVE');
          })}>Kết nối sniffer</button>
          <button className="secondary" disabled={!!activity?.capture} onClick={() => void act(async () => { await apiRequest(path + 'disconnect', 'POST'); })}>Ngắt sniffer</button>
        </div>
        <p>USB · {connection} · Kênh thu {number(diagnostics?.channel)} · {diagnostics?.scan_mode ?? 'NOT AVAILABLE'}</p>
        <form className="csi-toolbar" onSubmit={event => {
          event.preventDefault();
          void updateRegistry(async () => {
            await apiRequest(path + 'registry/channel', 'PUT', {channel: displayedChannel});
            setRequestedChannel(null);
          });
        }}>
          <label>Kênh thu mong muốn<input type="number" required
            min={configuration?.channel_min ?? 1} max={configuration?.channel_max ?? 13}
            value={displayedChannel} onChange={event => setRequestedChannel(Number(event.target.value))} /></label>
          <button className="primary" disabled={!canEditRegistry}>Lưu kênh thu</button>
        </form>
        <details className="q1-connection-details">
        <summary>Chẩn đoán firmware và UART</summary>
        <dl>
          <div><dt>Cổng serial</dt><dd>{diagnostics?.port ?? 'NOT AVAILABLE'}</dd></div>
          <div><dt>Baudrate</dt><dd>{number(diagnostics?.baudrate)}</dd></div>
          <div><dt>Firmware version</dt><dd>{diagnostics?.firmware_version ?? 'NOT AVAILABLE'}</dd></div>
          <div><dt>Capture mode</dt><dd>{diagnostics?.capture_mode ?? 'NOT AVAILABLE'}</dd></div>
          <div><dt>Kênh hiện tại</dt><dd>{number(diagnostics?.channel)}</dd></div>
          <div><dt>Chế độ kênh</dt><dd>{diagnostics?.scan_mode ?? 'NOT AVAILABLE'}</dd></div>
          <div><dt>Heartbeat</dt><dd>{number(diagnostics?.heartbeat_age_s, ' s trước')}</dd></div>
          <div><dt>Thiết bị đã đồng bộ</dt><dd>{number(overview?.synced)}</dd></div>
          <div><dt>MAC cấu hình trên board</dt><dd>{number(diagnostics?.registered_devices)}</dd></div>
          <div><dt>Management frames</dt><dd>{number(diagnostics?.management_frames)}</dd></div>
          <div><dt>Data frames</dt><dd>{number(diagnostics?.data_frames)}</dd></div>
          <div><dt>Control frames</dt><dd>{number(diagnostics?.control_frames)}</dd></div>
          <div><dt>Unattributed frames</dt><dd>{number(diagnostics?.unattributed_frames)}</dd></div>
          <div><dt>Unregistered frames</dt><dd>{number(diagnostics?.unregistered_frames)}</dd></div>
          <div><dt>Invalid frames</dt><dd>{number(diagnostics?.invalid_frames)}</dd></div>
          <div><dt>Off-channel frames</dt><dd>{number(diagnostics?.off_channel_frames)}</dd></div>
          <div><dt>RX callbacks</dt><dd>{number(diagnostics?.rx_callbacks)}</dd></div>
          <div><dt>UART bytes written</dt><dd>{number(diagnostics?.bytes_written)}</dd></div>
          <div><dt>Activity records nhận được</dt><dd>{number(diagnostics?.activity_records_received)}</dd></div>
          <div><dt>Serial Errors</dt><dd>{number(diagnostics?.serial_errors)}</dd></div>
          <div><dt>Lỗi phân tích bản tin</dt><dd>{number(diagnostics?.parsing_errors)}</dd></div>
          <div><dt>Queue Drops</dt><dd>{number(diagnostics?.queue_drops)}</dd></div>
          <div><dt>Bản tin cuối cùng</dt><dd>{lastReceived}</dd></div>
        </dl>
        {configuration?.supported === false && <p className="hint">Firmware hiện tại không hỗ trợ đổi kênh hoặc registry qua UART.</p>}
        {diagnostics?.reasons.map(code => <p key={code}><code>{code}</code> · {snifferReasonText[code]}</p>)}
        {diagnostics?.error && <p role="alert" className="alert error">{diagnostics.error}</p>}
        </details>
      </>}
      {mode !== 'LIVE' && <p>{modeText} · {connection} · Kênh {number(displayedActivity?.channel)}</p>}
    </section>
    <section className="panel csi-devices">
      <h2>Quản lý thiết bị</h2>
      {mode === 'LIVE' && activity?.source !== 'SIMULATION' ? <>
        <p><strong className={`q1-sync ${registryStatus.toLowerCase()}`} data-testid="registry-sync-state">{registryStatus}</strong>
          {' · Thiết bị trên firmware '}{number(configuration?.firmware_count)}
          {' · Kênh đã xác nhận '}{number(configuration?.applied_channel)}
          {' · Revision '}{number(configuration?.registry_revision)}</p>
        {configuration?.error && <p role="alert" className="alert error">
          Đã lưu cấu hình mong muốn. Đồng bộ thất bại · <code>{configuration.error}</code>
        </p>}
        {configuration?.supported === false && <p className="hint">Firmware cũ chỉ đọc được bản tin Activity.
          Nạp profile nâng cấp để cập nhật trực tiếp, hoặc ngắt USB để sửa registry cục bộ.</p>}
        {registryError && <p role="alert" className="alert error">Không tải được registry.</p>}
        <div className="csi-toolbar">
          <button type="button" className="secondary" disabled={!canEditRegistry || configuration?.supported !== true}
            onClick={() => void updateRegistry(async () => { await apiRequest(path + 'registry/sync', 'POST'); })}>
            Đồng bộ lại
          </button>
        </div>
        <div className="csi-toolbar"><label>Tìm thiết bị
          <input type="search" value={search} placeholder="Tên, MAC hoặc kênh" onChange={event => setSearch(event.target.value)} />
        </label></div>
        {registryRows.length ? <ul className="q1-registry-list">
          {registryRows.map(row => <li key={row.id}>
            <div><strong>{row.name}</strong> · <code>{row.wifi_mac ?? 'Cần nhập lại MAC'}</code>
              {' · Kênh '}{row.channel} · {syncState(row)}</div>
            <div className="q1-registry-actions">
              <button className="secondary" disabled={!canEditRegistry} onClick={() => {
                setEditing(row.id); setName(row.name); setMac(row.wifi_mac?.toUpperCase() ?? '');
                setMacError(''); setChannel(row.channel); setConsent(false);
              }}>Sửa {row.name}</button>
              <button className="secondary" disabled={!canEditRegistry} onClick={() => {
                if (!window.confirm(`Xóa thiết bị “${row.name}” khỏi registry?`)) return;
                void updateRegistry(async () => {
                  await apiRequest(path + `registry/${row.id}`, 'DELETE');
                  if (editing === row.id) clearRegistration();
                });
              }}>Xóa {row.name}</button>
            </div>
          </li>)}
        </ul> : <p>{search ? 'Không có thiết bị phù hợp.' : registry ? 'Chưa có thiết bị đăng ký.' : 'Đang đọc registry…'}</p>}
      </> : devices.length ? <ul className="q1-registry-list q1-archive-device-list">
        {devices.map(device => <li key={device.id} title={device.id}><strong>{device.name}</strong><span>Kênh {device.channel}</span></li>)}
      </ul>
        : <p>Chưa có registry của nguồn đã chọn.</p>}
      {mode === 'LIVE' && activity?.source !== 'SIMULATION' && <details className="csi-registry" open={editing ? true : undefined}>
        <summary>{editing ? 'Sửa thiết bị đăng ký' : 'Đăng ký thiết bị'}</summary>
        <p className="hint">Tối đa 16 MAC trên mỗi kênh.</p>
        <form className="csi-toolbar" onSubmit={register}>
          <label>Tên thiết bị <input required maxLength={80} value={name} onChange={event => setName(event.target.value)} /></label>
          <label>MAC đăng ký <input ref={macInput} className="mono" autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false}
            required placeholder="02:11:22:33:44:55" value={mac} aria-invalid={!!macError} aria-describedby={macError ? 'csi-mac-error' : undefined}
            onChange={event => editMac(event.currentTarget, event.nativeEvent as InputEvent)}
            onCompositionEnd={event => editMac(event.currentTarget)}
            onBlur={event => setMac(normalizeMac(event.target.value) ?? event.target.value)} /></label>
          <label>Kênh <input type="number" required min={1} max={13} value={channel} onChange={event => setChannel(Number(event.target.value))} /></label>
          <label className="csi-consent"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} /> Chủ thiết bị đồng ý</label>
          <button className="primary" disabled={!consent || !canEditRegistry}>{editing ? 'Lưu thiết bị' : 'Đăng ký'}</button>
          {editing && <button type="button" className="secondary" onClick={clearRegistration}>Hủy sửa</button>}
          {macError && <p id="csi-mac-error" className="alert error csi-mac-error" role="alert">{macError}</p>}
        </form>
      </details>}
    </section>

    </div>
    <div className="q1-column">
    <section className="panel csi-devices" aria-label="Q1 Device Activity">
      <h2>Bảng hoạt động thiết bị</h2>
      <div className="csi-toolbar q1-table-filters">
        <label>Tìm trong bảng<input type="search" value={tableSearch} onChange={event => setTableSearch(event.target.value)} /></label>
        <label>Trạng thái<select value={stateFilter} onChange={event => setStateFilter(event.target.value)}>
          <option value="">Tất cả</option>{states.map(state => <option key={state}>{state}</option>)}
        </select></label>
        <label>Kênh đăng ký<select value={channelFilter} onChange={event => setChannelFilter(event.target.value)}>
          <option value="">Tất cả</option>{tableChannels.map(ch => <option key={ch}>{ch}</option>)}
        </select></label>
      </div>
      {tableRows.length ? <div className="table-scroll" role="region" aria-label="Bảng hoạt động thiết bị" tabIndex={0}>
        <table className="q1-device-table">
          <thead><tr>{columns.map(([key, label]) => <th key={key} scope="col"
            aria-sort={sort.key === key ? sort.ascending ? 'ascending' : 'descending' : undefined}>
            <button type="button" className="q1-sort" onClick={() =>
              setSort({key, ascending: sort.key === key ? !sort.ascending : true})}>
              {label}{sort.key === key && <span aria-hidden="true">{sort.ascending ? ' ↑' : ' ↓'}</span>}
            </button>
          </th>)}</tr></thead>
          <tbody>{tableRows.map(device => <tr key={device.id} className={detail?.id === device.id ? 'q1-row-selected' : ''}>
            <th scope="row"><button className="q1-device-link" type="button"
              aria-pressed={detail?.id === device.id && !historical} onClick={() => {setDetailId(device.id); setPoint(null);}}>
              {device.name}</button></th>
            <td>{device.channel}</td>
            <td><span className={`csi-device-state ${device.state.toLowerCase()}`}>{device.state}</span></td>
            <td>{number(device.frames_per_s)}</td><td>{number(device.bytes_per_s)}</td>
            <td>{number(device.rssi_max_dbm, ' dBm')}</td><td>{percent(device.channel_coverage)}</td>
          </tr>)}</tbody>
        </table>
      </div> : <p>{devices.length ? 'Không có thiết bị phù hợp bộ lọc.' : 'Chưa có dữ liệu Q1 cho nguồn đã chọn.'}</p>}
    </section>

    <DeviceActivityTimeline key={scope} source={mode} sessionId={activitySessionId} devices={devices}
      lastWindowEnd={displayedActivity?.window_end_us ?? null} selected={selected}
      onSelect={ids => setSelection({scope, ids})} onPoint={value => setPoint({scope, value})} />
    </div>
    <aside className="panel q1-detail-panel" aria-label="Chi tiết thiết bị">
      <div className="q1-panel-heading"><h2>Chi tiết thiết bị</h2>
        {(historical || mode !== 'LIVE') && <button className="secondary" type="button" onClick={() => {
          if (historical) setDetailId(historical.device.id);
          setPoint(null);
          chooseSource('LIVE');
        }}>LIVE mới nhất</button>}
      </div>
      {detail ? <div className="q1-device-detail csi-evidence" aria-label={`Chi tiết ${detail.name}`}>
        <div className="q1-detail-title">
          <h3>{detail.name}</h3>
          <span className={`csi-device-state ${detail.state.toLowerCase()}`}>{detail.state}</span>
        </div>
        <p className="hint">{historical ? 'Cửa sổ đã chọn trên timeline' : 'Cửa sổ mới nhất'} · {mode}</p>
        <dl>{[
          ['Frame Count', number(detail.observed_frames)], ['Byte Count', number(detail.observed_bytes)],
          ['Frame Rate', number(detail.frames_per_s, ' frame/s')], ['Byte Rate', number(detail.bytes_per_s, ' byte/s')],
          ['RSSI', number(detail.rssi_max_dbm, ' dBm')],
          ['Last Seen', number(detail.last_seen_us == null ? null : detail.last_seen_us / 1e6, ' s')],
          ['Registered Channel', number(detail.channel)], ['Actual Channel', number(historical ? historical.channel : actualChannel)],
          ['Last Channel', number(detail.last_observed_channel)], ['Observation Duration', number(detail.observation_time_s, ' s')],
          ['Coverage', percent(detail.channel_coverage)], ['Đồng bộ firmware', historical ? 'NOT AVAILABLE' : syncState(detail)],
          ['Window Start', number(windowStart == null ? null : windowStart / 1e6, ' s')],
          ['Window End', number(windowEnd == null ? null : windowEnd / 1e6, ' s')],
          ['Registry Revision', number(historical ? historical.registryRevision : displayedActivity?.registry_revision)],
          ['Data Source', mode],
          ['Device ID', <code>{detail.id}</code>], ['Session ID', <code>{activitySessionId ?? 'NOT AVAILABLE'}</code>],
        ].map(([label, value]) => <div className={label === 'Device ID' || label === 'Session ID' ? 'q1-wide' : undefined}
          key={String(label)}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        <section className="q1-frame-kinds" aria-label="Phân bố loại khung">
          <h4>Phân tích khung Wi‑Fi</h4>
          <ul>{(['management', 'data', 'control', 'tx', 'rx'] as const).map(kind => {
            const metric = detail.frame_analysis?.[kind];
            const type = kind === 'tx' || kind === 'rx' ? kind.toUpperCase() : kind[0].toUpperCase() + kind.slice(1);
            return <li className={kind} key={kind}>
              <div><strong>{type}</strong><span>{number(metric?.count)} · {number(metric?.frames_per_s, ' frame/s')}
                {kind !== 'tx' && kind !== 'rx' && ` · ${percent(metric?.fraction)}`}</span></div>
              {metric?.fraction != null && <progress max={1} value={metric.fraction} aria-label={`Tỷ lệ ${type}`} />}
              {(kind === 'tx' || kind === 'rx') && metric?.count != null && !!detail.observed_frames &&
                <progress max={detail.observed_frames} value={metric.count} aria-label={`Số khung ${type} trên tổng số khung quan sát`} />}
            </li>;
          })}</ul>
          <p>Block ACK Count <strong>{number(detail.block_ack_frames)}</strong></p>
          {detail.frame_analysis?.tx.count == null && detail.frame_analysis?.rx.count == null &&
            <p className="hint">Thiếu mẫu có bộ đếm TX/RX trong cửa sổ này.</p>}
          {detail.data_valid && !detail.observed_frames && <p className="hint">Tỷ lệ loại khung và RSSI cần có khung quan sát được.</p>}
        </section>
        {historical && <p className="hint">Bản ghi lưu revision. Trạng thái ACK chỉ có trên registry hiện tại.</p>}
        {detail.state === 'UNKNOWN' && <p className="q1-detail-reason">Lý do · {detail.reasons.length
          ? detail.reasons.map(code => deviceReasonText[code] ?? code).join(' · ') : 'NOT AVAILABLE'}</p>}
        <p className="hint">RSSI của khung thu tại sniffer, gồm khung downlink từ AP.</p>
      </div> : <p className="hint">Chọn thiết bị trong bảng hoặc một cửa sổ trên timeline.</p>}
    </aside>
    </div>
    <DeviceCsiExperiments capture={mode === 'LIVE' ? liveActivity?.capture : null}
      captureError={mode === 'LIVE' ? liveActivity?.capture_error : null} mode={mode} usbConnected={usbConnected}
      canRecord={mode === 'LIVE' && liveActivity?.source === 'LIVE' && diagnostics?.connection === 'connected' &&
        diagnostics.heartbeat_age_s != null && diagnostics.heartbeat_age_s <= 2.5 &&
        (configuration?.supported !== true || configuration.state === 'SYNCED')}
      devices={registry?.devices ?? devices} selected={selected} simulationId={simulationId}
      replayId={activity?.source === 'REPLAY' ? activity.replay_capture_id : null}
      onSimulation={setSimulationId} onReplay={() => chooseSource('REPLAY')} />
  </div>;
}
