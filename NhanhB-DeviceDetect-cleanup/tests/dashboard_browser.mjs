import assert from 'node:assert/strict';
import {once} from 'node:events';
import {spawn, spawnSync} from 'node:child_process';
import {mkdir, mkdtemp, readFile, rm, unlink, writeFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {test} from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.DASHBOARD_TEST_PYTHON ?? join(root, '.venv/bin/python');
const playwright = process.env.DASHBOARD_PLAYWRIGHT_MODULE;
const screenshots = process.env.Q1_SCREENSHOT_DIR;

test('Q1 LIVE and replay work without CSI and preserve the Legacy dashboard', {timeout: 55_000}, async () => {
  const {chromium} = await import(playwright ? pathToFileURL(playwright).href : 'playwright');
  const runtime = await mkdtemp(join(tmpdir(), 'pbl3-dashboard-test-'));
  const reserve = createServer();
  reserve.listen(0, '127.0.0.1');
  await once(reserve, 'listening');
  const {port} = reserve.address();
  await new Promise(resolve => reserve.close(resolve));
  const url = `http://127.0.0.1:${port}`;
  let api, browser;
  try {
    const seed = spawnSync(python, ['-c', `
from pathlib import Path
import json, sys
from scripts.probe_fixture import generate
sys.path.insert(0, str(Path('tests').resolve()))
from test_device_csi_integration import DEVICES, sanitized_trace
from research.activity_records import Capture
folder = Path(sys.argv[1]) / 'experiments' / 'browser-replay'
generate(folder)
path = folder / 'metadata.json'
path.write_text(json.dumps(dict(json.loads(path.read_text()), id='browser-replay', synthetic=False)))
capture = Capture(Path(sys.argv[1]) / 'device-activity', DEVICES, 0)
for row in sanitized_trace():
    capture.append(row['ts_us'] / 1_000_000, packet=row)
print(capture.finish(20.1)['id'])
`, runtime], {cwd: root, encoding: 'utf8'});
    assert.equal(seed.status, 0, seed.stderr || String(seed.error));
    api = spawn(python, ['-c', `
from pathlib import Path
from serial.tools import list_ports
from threading import Thread
from types import SimpleNamespace
import json, os, pty, sys, time, uvicorn
from backend.app import main

master, slave = pty.openpty()
serial_port = os.ttyname(slave)
list_ports.comports = lambda: [SimpleNamespace(device=serial_port, description='Virtual UART', vid=None)]
rows = [json.loads(line) for line in Path('tests/fixtures/device_activity_v2.jsonl').read_text().splitlines()]

def send_activity():
    seq = tick = 0
    pause = Path(os.environ['WIFI_PROBE_DATA_DIR']) / 'pause-activity'
    while True:
        service = main.svc
        if service is not None and service.serial is not None and not pause.exists():
            end = tick * 1_000_000
            status = rows[1] | dict(ts_us=end, seq=seq + bool(tick), rx_callbacks=tick * 7,
                firmware_version='virtual-test', management_frames=0, data_frames=tick * 7, control_frames=0)
            if tick:
                sample = rows[3] | dict(ts_us=end - 1_000_000, seq=seq, duration_us=1_000_000,
                    source_mac='02:ab:cd:ef:12:34')
                os.write(master, (json.dumps(sample) + chr(10)).encode())
            os.write(master, (json.dumps(status) + chr(10)).encode())
            seq += 1 + bool(tick)
            tick += 1
        time.sleep(.15)

Thread(target=send_activity, daemon=True).start()
uvicorn.run(main.app, host='127.0.0.1', port=int(sys.argv[1]))
`, String(port)], {
      cwd: root, env: {...process.env, WIFI_PROBE_DATA_DIR: runtime, WIFI_DASHBOARD_CONFIG: ''}, stdio: 'ignore',
    });
    let healthy = false;
    for (let retry = 0; retry < 60 && !healthy; retry++) {
      healthy = await fetch(`${url}/api/health`).then(response => response.ok, () => false);
      if (!healthy) await delay(100);
    }
    assert.ok(healthy, 'FastAPI failed to start');
    browser = await chromium.launch({executablePath: process.env.DASHBOARD_TEST_CHROME ?? '/usr/bin/google-chrome'});
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    page.setDefaultTimeout(6500);
    await page.goto(url);
    const mode = page.getByTestId('csi-mode');
    const csiCalls = [];
    page.on('request', request => {
      if (/\/api\/device-csi\/(quality|reliability)\//.test(request.url())) csiCalls.push(request.url());
    });
    await page.getByText('Chưa có thiết bị đăng ký.').waitFor();
    assert.match(await mode.textContent(), /^LIVE/);
    assert.ok(await page.getByText('NOT AVAILABLE', {exact: true}).count());

    await page.getByText('Đăng ký thiết bị', {exact: true}).click();
    await page.getByLabel('Tên thiết bị').fill('Thiết bị kiểm thử');
    await page.getByLabel('Chủ thiết bị đồng ý').check();
    const mac = page.getByLabel('MAC đăng ký');
    const submit = page.getByRole('button', {name: 'Đăng ký', exact: true});
    await mac.pressSequentially('a0');
    assert.equal(await mac.inputValue(), 'A0:');
    await mac.pressSequentially('b1');
    assert.equal(await mac.inputValue(), 'A0:B1:');
    await mac.press('Backspace');
    assert.equal(await mac.inputValue(), 'A0:B');
    await mac.pressSequentially('1c2d3e4f5');
    assert.equal(await mac.inputValue(), 'A0:B1:C2:D3:E4:F5');
    await mac.evaluate(input => input.setSelectionRange(3, 3));
    await mac.press('Backspace');
    assert.equal(await mac.inputValue(), 'AB:1C:2D:3E:4F:5');
    await mac.press('0');
    assert.equal(await mac.inputValue(), 'A0:B1:C2:D3:E4:F5');

    await mac.fill('02:ab cd');
    assert.equal(await mac.inputValue(), '02:AB:CD:');
    await mac.pressSequentially('ef 12 34');
    assert.equal(await mac.inputValue(), '02:AB:CD:EF:12:34');

    for (const invalid of ['02:ab-cde:f:12:34', '02:ab:cd:ef:12:34:56', '02:ab:cd:ef:12:3g', '02112233445', '03:11:22:33:44:55', '000000000000']) {
      await mac.fill(invalid);
      await submit.click();
      assert.equal(await mac.getAttribute('aria-invalid'), 'true');
      assert.ok(await mac.evaluate(input => input === document.activeElement));
    }
    assert.equal((await (await page.request.get(`${url}/api/device-csi/registry`)).json()).devices.length, 0);
    for (const valid of ['02abcdef1234', '02-ab-cd-ef-12-34', '02:ab:cd:ef:12:34', '02:ab-cd:ef:12:34']) {
      await mac.fill(valid);
      assert.equal(await mac.inputValue(), '02:AB:CD:EF:12:34');
    }
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.evaluate(value => navigator.clipboard.writeText(value), '  02:ab:cd ef 12 34  ');
    await mac.fill('');
    await mac.press('Control+v');
    assert.equal(await mac.inputValue(), '02:AB:CD:EF:12:34');
    const registered = page.waitForResponse(response => response.url().endsWith('/api/device-csi/registry') && response.request().method() === 'POST');
    await mac.press('Enter');
    const registration = await registered;
    assert.equal(registration.request().postDataJSON().mac, '02:AB:CD:EF:12:34');
    assert.equal(registration.status(), 202);
    await page.getByRole('rowheader', {name: 'Thiết bị kiểm thử'}).waitFor();
    assert.equal(await mac.inputValue(), '');
    await page.request.post(url + '/api/device-csi/registry', {
      data: {name: 'Thiết bị sai kênh', mac: '02:ab:cd:ef:12:34', channel: 11, consent: true},
    }).then(r => r.json());

    await page.getByLabel('Tốc độ UART').selectOption('460800');
    await page.getByRole('button', {name: 'Kết nối sniffer', exact: true}).click();
    const activeDevice = page.getByRole('row').filter({hasText: 'Thiết bị kiểm thử'});
    await activeDevice.getByText('OBSERVED_ACTIVE', {exact: true}).waitFor();
    await activeDevice.getByText('-41 dBm', {exact: true}).waitFor();
    await activeDevice.getByText('100%', {exact: true}).waitFor();

    const sniffer = async () => (await page.request.get(`${url}/api/device-csi/state`)).json();
    const firstWindow = await sniffer();
    assert.equal(firstWindow.channel_frames_per_s, 7);
    if (screenshots) {
      const previousViewport = page.viewportSize();
      await mkdir(screenshots, {recursive: true});
      await page.setViewportSize({width: 1600, height: 900});
      await page.getByText('Chẩn đoán firmware và UART', {exact: true}).click();
      await page.getByText('Serial Errors', {exact: true}).waitFor();
      await page.screenshot({path: join(screenshots, 'q1-uart-1600.png'), fullPage: true, animations: 'disabled'});
      await page.getByText('Chẩn đoán firmware và UART', {exact: true}).click();
      await page.setViewportSize(previousViewport);
    }
    const historyChart = page.getByRole('region', {name: 'Q1 Device Activity Timeline'});
    const correctDevice = historyChart.getByRole('checkbox', {name: 'Thiết bị kiểm thử'});
    const wrongDevice = historyChart.getByRole('checkbox', {name: 'Thiết bị sai kênh'});
    const historyMetric = historyChart.getByLabel('Chỉ số');
    await historyChart.getByRole('img', {name: /^Frame\/s: [1-9]/}).waitFor();
    await historyChart.getByRole('button', {name: /OBSERVED_ACTIVE/}).first().hover();
    const tip = historyChart.getByRole('tooltip');
    await tip.getByText('-41 dBm', {exact: true}).waitFor();
    for (const range of [5, 15, 30, 1]) {
      const fetched = page.waitForResponse(r => r.url().includes('/activity/history?')
        && new URL(r.url()).searchParams.get('lookback_s') === String(range * 60) && r.ok());
      await historyChart.getByLabel('Khoảng thời gian').selectOption(String(range));
      await fetched;
    }
    await historyMetric.selectOption('bytes_per_s');
    await historyChart.getByRole('img', {name: /^Byte\/s: [1-9]/}).waitFor();
    await correctDevice.uncheck();
    await historyChart.getByRole('img', {name: 'Byte/s: 0 điểm, 0 đoạn'}).waitFor();
    await historyChart.getByRole('button', {name: /UNKNOWN/}).first().hover();
    await tip.getByText('NOT AVAILABLE', {exact: true}).first().waitFor();
    await correctDevice.check();
    await wrongDevice.uncheck();
    await historyMetric.selectOption('frames_per_s');
    await writeFile(join(runtime, 'pause-activity'), '');
    await activeDevice.getByText('UNKNOWN', {exact: true}).waitFor();
    await historyChart.getByRole('button', {name: /OBSERVED_ACTIVE/}).first().waitFor();
    await unlink(join(runtime, 'pause-activity'));
    await historyChart.getByRole('button', {name: /UNKNOWN/}).first().waitFor();
    await historyChart.getByRole('img', {name: /Frame\/s: .* 2 đoạn/}).waitFor();

    await page.getByRole('button', {name: 'Legacy / Probe'}).click();
    await page.getByText('Board đang thu Device Activity', {exact: true}).waitFor();
    await page.getByRole('button', {name: 'Device Activity Monitoring'}).click();
    await activeDevice.getByText('OBSERVED_ACTIVE', {exact: true}).waitFor();
    const nextWindow = await sniffer();
    assert.equal(nextWindow.boot_id, firstWindow.boot_id);
    assert.equal(nextWindow.diagnostics.port, firstWindow.diagnostics.port);
    assert.ok(nextWindow.window_end_us >= firstWindow.window_end_us);
    await page.getByLabel('Tên thực nghiệm').fill('Kiểm thử cửa sổ Q1');
    await page.getByLabel('Kịch bản').selectOption('traffic');
    await page.getByRole('button', {name: 'Bắt đầu ghi Q1'}).click();
    await page.getByText(/Đang ghi Q1/).waitFor();
    await page.getByLabel('Dấu mốc thao tác').fill('Tải thử qua UART ảo');
    await page.getByRole('button', {name: 'Ghi dấu mốc'}).click();
    await page.getByText(/s · Tải thử qua UART ảo/).waitFor();
    await page.getByRole('button', {name: 'Kết thúc Q1'}).click();
    const q1Download = page.getByRole('link', {name: 'Xuất chi tiết Q1'});
    await q1Download.waitFor();
    const csv = await page.request.get(url + await q1Download.getAttribute('href'));
    assert.equal(csv.status(), 200);
    assert.match(await csv.text(), /Tải thử qua UART ảo/);
    await page.getByRole('button', {name: 'Ngắt sniffer', exact: true}).click();
    await page.getByText(/USB · disconnected/).waitFor();

    const sourcePicker = page.getByRole('combobox', {name: 'Nguồn dữ liệu', exact: true});
    await sourcePicker.selectOption('REPLAY');
    const captureId = seed.stdout.trim();
    await page.getByLabel('Lịch sử thực nghiệm').selectOption(captureId);
    await page.getByRole('button', {name: 'Phát lại Q1'}).click();
    const activityTable = page.getByRole('region', {name: 'Bảng hoạt động thiết bị'});
    await activityTable.getByText('Device a', {exact: true}).waitFor();
    await activityTable.getByText('NO_OBSERVED_ACTIVITY', {exact: true}).first().waitFor({timeout: 25_000});
    await historyChart.getByRole('checkbox', {name: 'Device b'}).uncheck();
    await historyChart.getByRole('button', {name: /NO_OBSERVED_ACTIVITY/}).first().click();
    await tip.getByText('0', {exact: true}).first().waitFor();
    await historyMetric.selectOption('rssi_max_dbm');
    await historyChart.getByRole('img', {name: 'RSSI: 1 điểm, 1 đoạn'}).waitFor();
    await sourcePicker.selectOption('LIVE');
    assert.equal(await page.getByRole('rowheader', {name: 'Device a'}).count(), 0);
    await page.getByRole('button', {name: 'Ngắt sniffer'}).click();
    assert.match(await mode.textContent(), /^LIVE/);
    assert.deepEqual(csiCalls, []);

    await page.getByRole('button', {name: 'Legacy / Probe'}).click();
    const estimate = page.getByTestId('room-estimate');
    await estimate.waitFor();
    assert.equal(await estimate.textContent(), 'UNKNOWN');
    await page.getByText('Nguồn thu đã ngắt hoặc đang kết nối lại.').waitFor();

    const replay = async name => {
      const response = await page.request.post(`${url}/api/probe/replay`, {data: {name, speed: 100}});
      assert.ok(response.ok(), await response.text());
    };
    await replay('synthetic-probe-demo');
    await page.getByText('DEMO · Mô phỏng', {exact: true}).waitFor();
    const table = page.getByRole('region', {name: 'Bảng Device Cluster'});
    await table.waitFor();
    await page.getByLabel('Cửa sổ biểu đồ').selectOption('60');
    await page.getByRole('img', {name: /60 giây/}).waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.ok(await table.evaluate(element => element.scrollWidth > element.clientWidth));
    await table.getByText('Lý do và lịch sử').first().click();
    await table.getByText('Liên kết MAC', {exact: true}).first().waitFor();
    assert.equal(await estimate.textContent(), 'UNKNOWN');

    await page.getByRole('button', {name: 'Ngắt nguồn', exact: true}).click();
    await page.getByText('Nguồn thu đã ngắt hoặc đang kết nối lại.').waitFor();
    await replay('browser-replay');
    await page.getByText('REPLAY · Phát lại', {exact: true}).waitFor();
    await table.waitFor();
    await page.setViewportSize({width: 1280, height: 900});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));

    await page.route('**/api/probe/dashboard', route => route.abort());
    await page.getByText('Không đọc được dữ liệu phân tích', {exact: false}).waitFor();
    assert.equal(await estimate.textContent(), 'UNKNOWN');
    assert.equal(await table.count(), 0);
  } finally {
    await browser?.close();
    if (api?.exitCode === null && api?.signalCode === null) {
      api.kill();
      await once(api, 'exit');
    }
    await rm(runtime, {recursive: true, force: true});
  }
});

test('Q1 adaptive timeline and CSV agree for 0–16 selected devices', {timeout: 40_000}, async () => {
  const {chromium} = await import(playwright ? pathToFileURL(playwright).href : 'playwright');
  const runtime = await mkdtemp(join(tmpdir(), 'pbl3-pty-browser-'));
  const simulator = spawn(python, ['-m', 'scripts.simulate_hardware', '--scenario', 'S12',
    '--seed', '20261126', '--tick-delay', '.03', '--output', runtime], {cwd: root});
  let output = '';
  simulator.stdout.on('data', chunk => { output += chunk; });
  simulator.stderr.on('data', chunk => { output += chunk; });
  const stopped = once(simulator, 'exit');
  let browser;
  try {
    let url, id;
    for (let retry = 0; retry < 100 && simulator.exitCode === null && (!url || !id); retry++) {
      url = output.match(/Dashboard (http:\/\/127\.0\.0\.1:\d+)/)?.[1];
      id = output.match(/S12 PASS id=([0-9a-f]{32})/)?.[1];
      if (!url || !id) await delay(100);
    }
    assert.ok(url && id, output);
    browser = await chromium.launch({executablePath: process.env.DASHBOARD_TEST_CHROME ?? '/usr/bin/google-chrome'});
    const page = await browser.newPage({acceptDownloads: true});
    page.setDefaultTimeout(6500);
    await page.goto(url);
    const base = '/api/device-csi';
    const sessions = base + '/reliability/sessions';
    const blockedCapture = await page.request.post(url + base + '/captures/start');
    assert.equal(blockedCapture.status(), 409);
    const blockedLive = await page.request.post(url + sessions, {data: {mode: 'LIVE'}});
    assert.equal(blockedLive.status(), 409);
    const report = await page.request.get(`${url}${sessions}/${id}/timeline?window_s=10`).then(r => r.json());
    assert.equal(report.source, 'SIMULATION');

    const csiCalls = [];
    page.on('request', request => {
      if (/\/api\/device-csi\/(quality|reliability)\//.test(request.url())) csiCalls.push(request.url());
    });
    assert.equal(report.current.evidence_source, 'CSI_AND_SNIFFER');
    assert.equal(report.quality.quality, 'GOOD');

    const source = page.getByRole('combobox', {name: 'Nguồn dữ liệu', exact: true});
    const device = page.getByRole('rowheader', {name: 'Thiết bị Python PTY'});
    assert.equal(await device.count(), 0);
    await source.selectOption('SIMULATION');
    await page.getByLabel('Lịch sử thực nghiệm').selectOption(id);
    const q1Row = page.getByRole('row').filter({has: device});
    const activity = report.activity.devices[0];
    await q1Row.getByText(activity.state, {exact: true}).waitFor();
    await q1Row.getByRole('button', {name: 'Thiết bị Python PTY'}).click();
    await page.getByLabel('Chi tiết Thiết bị Python PTY')
      .getByText(String(activity.observed_frames), {exact: true}).first().waitFor();
    await page.reload();
    const history = page.getByRole('region', {name: 'Q1 Device Activity Timeline'});
    await history.getByRole('img', {name: 'Frame/s: 2 điểm, 1 đoạn'}).waitFor();
    await history.getByRole('button', {name: /OBSERVED_ACTIVE/}).last().click();
    const activityTooltip = history.getByRole('tooltip');
    assert.equal(await activityTooltip.locator('dt').filter({hasText: /^Frame$/}).locator('..').locator('dd').textContent(),
      String(activity.observed_frames));
    assert.equal(await activityTooltip.locator('dt').filter({hasText: /^Frame\/s$/}).locator('..').locator('dd').textContent(),
      String(activity.frames_per_s));
    await page.getByText('Cửa sổ đã chọn trên timeline · SIMULATION', {exact: true}).waitFor();
    await history.getByLabel('Khoảng thời gian').selectOption('30');
    await history.getByRole('img', {name: 'Frame/s: 2 điểm, 1 đoạn'}).waitFor();

    const folder = output.match(/Dữ liệu SIMULATION ([^\r\n]+)/)?.[1];
    assert.ok(folder, output);
    const seed = spawnSync(python, ['-c', [
      'import sys',
      'from pathlib import Path',
      'sys.path.insert(0, "tests")',
      'from test_registered_device_monitor import reference_capture',
      'print(reference_capture(Path(sys.argv[1]) / "device-activity"))',
    ].join('\n'), folder], {cwd: root, encoding: 'utf8'});
    assert.equal(seed.status, 0, seed.stderr);
    const referenceId = seed.stdout.trim();
    await page.reload();
    await page.getByLabel('Lịch sử thực nghiệm').selectOption(referenceId);
    const table = page.getByRole('region', {name: 'Bảng hoạt động thiết bị'});
    const reference = table.getByRole('row').filter({hasText: 'Mẫu tham chiếu 9 giây'});
    for (const value of ['199.11', '8687.44', '90%']) {
      await reference.getByRole('cell', {name: value, exact: true}).waitFor();
    }
    const detail = page.getByLabel('Chi tiết Mẫu tham chiếu 9 giây', {exact: true});
    for (const value of ['1792', '78187', '9 s', '199.11 frame/s', '8687.44 byte/s']) {
      await detail.getByText(value, {exact: true}).first().waitFor();
    }
    await page.getByRole('combobox', {name: 'Thiết bị và cấu hình'}).waitFor();
    await page.getByRole('button', {name: 'Frame/s', exact: true}).click();
    assert.equal(await table.getByRole('columnheader', {name: 'Frame/s'}).getAttribute('aria-sort'), 'ascending');
    await page.getByRole('searchbox', {name: 'Tìm trong bảng'}).fill('không có');
    await page.getByText('Không có thiết bị phù hợp bộ lọc.').waitFor();
    await page.getByRole('searchbox', {name: 'Tìm trong bảng'}).clear();
    await page.getByRole('combobox', {name: 'Kênh đăng ký', exact: true}).selectOption('6');
    await page.getByRole('combobox', {name: 'Trạng thái', exact: true}).selectOption('UNKNOWN');
    await page.getByText('Không có thiết bị phù hợp bộ lọc.').waitFor();
    await page.getByRole('combobox', {name: 'Trạng thái', exact: true}).selectOption('');
    await page.getByRole('combobox', {name: 'Kênh đăng ký', exact: true}).selectOption('');
    const detailCsv = await page.request.get(url + await page.getByRole('link', {name: 'Xuất chi tiết Q1'}).getAttribute('href'));
    assert.match(await detailCsv.text(), /199\.11111111111111,8687\.444444444445/);
    if (screenshots) {
      await mkdir(screenshots, {recursive: true});
      await page.setViewportSize({width: 1366, height: 768});
      await page.screenshot({path: join(screenshots, 'q1-console-1366.png'), fullPage: true, animations: 'disabled'});
    }

    for (let n = 1; n < 16; n++) {
      const reply = await page.request.post(url + base + '/registry', {data: {
        name: `Bộ mẫu ${String(n).padStart(2, '0')}`, mac: `02:12:34:56:78:${n.toString(16).padStart(2, '0')}`,
        channel: 6, consent: true,
      }});
      assert.ok(reply.ok(), await reply.text());
    }
    await page.getByRole('group', {name: 'Thiết bị thực nghiệm'}).getByRole('checkbox', {name: 'Bộ mẫu 15'}).waitFor();
    await page.getByLabel('Tên thực nghiệm').fill('Q1 đủ 16 thiết bị');
    await page.getByLabel('Kịch bản').selectOption('mixed');
    await page.getByRole('button', {name: 'Chạy mô phỏng Q1'}).click();
    await history.locator('.q1-timeline-row').nth(15).waitFor();
    assert.equal(await history.getAttribute('data-view'), 'heatmap');
    const toggles = history.getByRole('checkbox');
    for (const [count, mode] of [[8, 'heatmap'], [5, 'heatmap'], [4, 'multi'], [2, 'multi'], [1, 'single'], [0, 'empty']]) {
      for (let index = count; index < 16; index++) {
        if (await toggles.nth(index).isChecked()) await toggles.nth(index).uncheck();
      }
      assert.equal(await history.getAttribute('data-view'), mode);
      assert.equal(await history.locator('.q1-timeline-row').count(), count);
    }
    await history.getByRole('button', {name: 'Chọn tất cả', exact: true}).click();
    await history.getByLabel('Chỉ số').selectOption('state');
    await history.getByRole('button', {name: /OBSERVED_ACTIVE/}).first().click();
    const tooltip = history.getByRole('tooltip');
    assert.ok(await tooltip.getByText('Frame/s', {exact: true}).count());
    await page.getByText('Cửa sổ đã chọn trên timeline · SIMULATION', {exact: true}).waitFor();
    for (const [width, height] of [[1366, 768], [1600, 900], [1920, 1080]]) {
      await page.setViewportSize({width, height});
      const layout = await page.locator('.q1-columns').evaluate(element => ({
        columns: getComputedStyle(element).gridTemplateColumns.split(' ').length,
        overflow: document.documentElement.scrollWidth > window.innerWidth,
      }));
      assert.deepEqual(layout, {columns: 3, overflow: false});
      if (screenshots && width === 1920) {
        await page.screenshot({path: join(screenshots, 'q1-heatmap-1920.png'), fullPage: true, animations: 'disabled'});
      }
    }
    await page.setViewportSize({width: 390, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));

    for (const [label, filename, header] of [
      ['Xuất chi tiết Q1', 'q1_activity_detail.csv', 'window_end_us'],
      ['Xuất tổng hợp Q1', 'q1_experiment_summary.csv', 'avg_frames_per_s'],
      ['Xuất bản ghi UART Q1', 'q1_raw_capture.csv', 'record_type'],
    ]) {
      const event = page.waitForEvent('download');
      await page.getByRole('link', {name: label}).click();
      const download = await event;
      assert.equal(download.suggestedFilename(), filename);
      const file = await readFile(await download.path(), 'utf8');
      assert.match(file, new RegExp(header));
      assert.doesNotMatch(file.slice(0, file.indexOf(String.fromCharCode(10))), /csi_receive_hz|reliability_label|jitter_ms/);
      assert.match(file, /SIMULATION/);
    }
    await page.getByRole('button', {name: 'LIVE mới nhất'}).click();
    assert.equal(await source.inputValue(), 'LIVE');
    assert.equal(await device.count(), 0);
    assert.deepEqual(csiCalls, []);
  } finally {
    await browser?.close();
    if (simulator.exitCode === null && simulator.signalCode === null) {
      simulator.stdin.end('stop\n');
      await stopped;
    }
    await rm(runtime, {recursive: true, force: true});
  }
});

test('Dashboard configures the runtime registry over UART', {timeout: 25_000}, async () => {
  const {chromium} = await import(playwright ? pathToFileURL(playwright).href : 'playwright');
  const runtime = await mkdtemp(join(tmpdir(), 'pbl3-runtime-registry-browser-'));
  const reserve = createServer();
  reserve.listen(0, '127.0.0.1');
  await once(reserve, 'listening');
  const {port} = reserve.address();
  await new Promise(resolve => reserve.close(resolve));
  const url = `http://127.0.0.1:${port}`;
  const api = spawn(python, ['-c', `
import os, pty, sys, time, uvicorn
from pathlib import Path
from serial.tools import list_ports
from threading import Thread
from types import SimpleNamespace
from backend.app import main
sys.path.insert(0, str(Path('tests').resolve()))
from test_runtime_registry import RuntimeBoard

master, slave = pty.openpty()
port = os.ttyname(slave)
list_ports.comports = lambda: [SimpleNamespace(device=port, description='Runtime UART', vid=None)]
board = RuntimeBoard(master)

def emit():
    connection = None
    while True:
        service = main.svc
        if service is None or service.serial is None:
            time.sleep(.05)
            continue
        try:
            if service.serial is not connection:
                connection = service.serial
                board.heartbeat()
            command = board.command(timeout=.15)
            if command:
                board.configure(command)
            else:
                board.advance(1)
        except OSError:
            time.sleep(.05)

Thread(target=emit, daemon=True).start()
uvicorn.run(main.app, host='127.0.0.1', port=int(sys.argv[1]))
`, String(port)], {cwd: root, env: {...process.env, WIFI_PROBE_DATA_DIR: runtime, WIFI_DASHBOARD_CONFIG: ''}, stdio: 'ignore'});
  let browser;
  try {
    let healthy = false;
    for (let retry = 0; retry < 60 && !healthy; retry++) {
      healthy = await fetch(`${url}/api/health`).then(response => response.ok, () => false);
      if (!healthy) await delay(100);
    }
    assert.ok(healthy);
    browser = await chromium.launch({executablePath: process.env.DASHBOARD_TEST_CHROME ?? '/usr/bin/google-chrome'});
    const page = await browser.newPage();
    page.setDefaultTimeout(6500);
    await page.goto(url);
    await page.getByLabel('Tốc độ UART').selectOption('460800');
    await page.getByRole('button', {name: 'Kết nối sniffer', exact: true}).click();
    const syncState = page.getByTestId('registry-sync-state');
    await syncState.filter({hasText: 'SYNCED'}).waitFor();
    await page.getByText('Đăng ký thiết bị', {exact: true}).click();
    await page.getByLabel('Tên thiết bị').fill('Điện thoại đã đồng ý');
    await page.getByLabel('MAC đăng ký').fill('02aabbccddee');
    await page.getByLabel('Chủ thiết bị đồng ý').check();
    await page.getByRole('button', {name: 'Đăng ký', exact: true}).click();
    await page.getByText(/Thiết bị trên firmware 1/).waitFor();
    const search = page.getByRole('searchbox', {name: 'Tìm thiết bị'});
    await search.fill('00:00');
    await page.getByText('Không có thiết bị phù hợp.').waitFor();
    await search.fill('02:aa:bb');
    await page.getByRole('button', {name: 'Sửa Điện thoại đã đồng ý'}).click();
    await search.clear();
    assert.equal(await page.getByLabel('MAC đăng ký').inputValue(), '02:AA:BB:CC:DD:EE');
    await page.getByLabel('Tên thiết bị').fill('Điện thoại ở kênh 11');
    await page.getByLabel('MAC đăng ký').fill('02aabbccddff');
    await page.getByLabel('Kênh', {exact: true}).fill('11');
    await page.getByLabel('Chủ thiết bị đồng ý').check();
    await page.getByRole('button', {name: 'Lưu thiết bị'}).click();
    await page.getByRole('button', {name: 'Xóa Điện thoại ở kênh 11'}).waitFor();
    await page.getByLabel('Kênh thu mong muốn').fill('11');
    await page.getByRole('button', {name: 'Lưu kênh thu'}).click();
    await page.getByText(/Thiết bị trên firmware 1 · Kênh đã xác nhận 11/).waitFor();
    await syncState.filter({hasText: 'SYNCED'}).waitFor();
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', {name: 'Xóa Điện thoại ở kênh 11'}).click();
    await page.getByText(/Thiết bị trên firmware 0 · Kênh đã xác nhận 11/).waitFor();
    await page.getByText('Chưa có thiết bị đăng ký.', {exact: true}).waitFor();
    const response = page.waitForResponse(r => r.url().endsWith('/registry/sync') && r.ok());
    await page.getByRole('button', {name: 'Đồng bộ lại'}).click();
    assert.equal((await (await response).json()).state, 'SYNCED');
  } finally {
    await browser?.close();
    if (api.exitCode === null && api.signalCode === null) {
      api.kill();
      await once(api, 'exit');
    }
    await rm(runtime, {recursive: true, force: true});
  }
});
