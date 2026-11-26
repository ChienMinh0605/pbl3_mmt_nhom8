# Kiểm kê tái sử dụng WiFi Device Sherlock

## Phạm vi và mốc Git

- Remote `origin` trỏ tới `qphuc9405/NhanhB-DeviceDetect`. Trạng thái ban đầu là `main` theo dõi `origin/main`, cây làm việc sạch, tại `fada6128628fab20965406c8c2a079da34f931a4` (`Initial commit`). Nhánh `feature/device-csi-reliability` được tạo cục bộ từ commit đó.
- Ở lần rà soát tiếp theo, `DE_XUAT_NHANH_THIET_BI.md` đã có trong `docs/` dưới dạng file chưa được Git theo dõi. Đề xuất cung cấp cấu hình SNF trên kênh router, đo CSI tại RX và các tình huống kiểm thử với nhánh người. [Đề xuất nhánh thiết bị](DE_XUAT_NHANH_THIET_BI.md)
- Đặc tả nhóm trong repo mô tả nhiều board với các dòng `CSI,`/`PRB,`/`STAT` và logger CSV. Contract đang chạy ở commit audit là JSONL theo mã firmware và parser. Đề xuất nói tới `KE_HOACH_NHANH_NGUOI.md` và đặc tả v0.3, nhưng cây làm việc chưa có tài liệu kế hoạch nhánh người hoặc mẫu log RX để xác nhận phiên bản và ánh xạ trường. [Đặc tả định dạng dữ liệu nhóm](../../Dac_ta_dinh_dang_du_lieu%20%282%29.md)
- Nguồn đối chiếu gồm README, đặc tả, tài liệu kiến trúc, firmware, backend, mô-đun nghiên cứu, frontend, cấu hình và test. Tài liệu [VALIDATION](VALIDATION.md) ghi 921600 baud và số test từ một lần kiểm tra trước. Mã hiện tại đặt UART 460800 và kết quả chạy lại được ghi bên dưới.

## Pipeline đã xác minh

1. **ESP32-C3** chạy Wi‑Fi `WIFI_MODE_NULL` ở chế độ promiscuous, nhận Probe Request từ management frames và bỏ MAC của board. Callback chụp `esp_timer_get_time()`, MAC nguồn, RSSI, kênh RX, số thứ tự frame, retry và tối đa 24 cặp mã/độ dài IE. Queue 128 mục đưa dữ liệu sang task xuất UART. Firmware phát `status` khoảng mỗi giây và `channel` khi đổi kênh. Mặc định VN, bắt đầu kênh 6 rồi luân phiên 1–13, dwell 3000 ms. Build fixed mẫu nghe kênh 6. [Firmware](../../firmware/sniffer/main/main.c) · [Kconfig](../../firmware/sniffer/main/Kconfig.projbuild) · [UART](../../firmware/sniffer/sdkconfig.defaults)
2. **UART → collector** qua UART0 460800 8N1, TX GPIO21/RX GPIO20 theo cấu hình CH340. `ProbeService` sở hữu một cổng tại một thời điểm, đọc từng chunk, tách dòng LF với giới hạn 16000 byte, tự kết nối lại và chuyển từng bản ghi cho parser Pydantic. Sau khi parse, bản ghi đi vào `Stream`, `DashboardBuffer` và `raw.jsonl` nếu đang ghi. Cơ chế thu chạy độc lập với nhịp polling của UI. [Collector](../../research/collector.py) · [Parser](../../backend/app/protocol.py)
3. **FastAPI → React**. `Stream` duy trì heartbeat, coverage kênh, đệm MAC và bộ so sánh Sherlock/unique/timeout. `DashboardBuffer` chạy IE clustering → presence → ước lượng trong phòng có calibration. FastAPI cung cấp hai ảnh chụp qua HTTP và phục vụ `frontend/dist` khi có build. `ProbePanel` và `DeviceOverview` polling khoảng mỗi giây, ghép đúng `source_id`/`dashboard_source_id`. UI nhận diện `LIVE`, `REPLAY`, `DEMO` và khoảng thiếu quan sát. [Stream](../../research/stream.py) · [DashboardBuffer](../../research/dashboard.py) · [FastAPI](../../backend/app/main.py) · [React](../../frontend/src/main.tsx)
4. **Record/replay**. Phiên bắt đầu khi nguồn serial có heartbeat hợp lệ. SQLite lưu metadata và nhật ký sự kiện. File phiên lưu packet đã parse cùng nhãn. Replay dùng cùng collector/stream, cấu hình Probe đã lưu và đồng hồ của file. `evaluate`, `inspect` và các nghiên cứu đếm chạy offline. [Storage](../../backend/app/storage.py) · [Replay loader](../../research/evaluate.py)

Phạm vi đã triển khai là Probe Request và suy luận từ các lần quan sát. Một radio chỉ nghe một kênh tại một thời điểm. Độ phủ suy ra từ heartbeat và kênh đang nghe, số drop là drop trong đường thu đã biết. Mã firmware chưa có CSI callback, parser chưa nhận CSI, backend chưa có registry thiết bị, cửa sổ chất lượng CSI hay reliability gate. Số người có thể được ghi như nhãn thực nghiệm, còn các báo cáo hiện tại đánh giá số thiết bị.

## Đối chiếu với đề xuất nhánh thiết bị

| Đề xuất | Đã kiểm tra trong repository | Tác động lên kế hoạch |
|---|---|---|
| Q1 nghe data/control trên kênh router và đếm theo MAC đăng ký, có thể dùng Block Ack. | Firmware chỉ bật filter management và nhận Probe Request. Chế độ fixed có sẵn qua Kconfig. Chưa có callback data/control, bản ghi tổng hợp theo giây hay registry. | Mở rộng firmware SNF và kiểm tra Block Ack/MAC trên board. Giữ Probe/Sherlock để đọc lại phiên cũ và làm baseline riêng. |
| Q2 lấy số khác TX từ `STAT.n_filtered`, noise floor và tốc độ mẫu tại RX. | `status` của SNF có counter Probe và UART. `n_filtered` xuất hiện trong đặc tả nhóm, chưa có firmware RX, parser CSI hoặc adapter `STAT` trong mã nguồn audit. | Lấy telemetry từ đúng RX/kênh sensing, chuẩn hóa định dạng sau khi có log mẫu, và đối chiếu với lượt có tải đồng kênh. |
| Q3 trong đề xuất chọn người nhận cảnh báo dựa vào bằng chứng có mặt. | Mã hiện có suy luận MAC/cluster và ước lượng trong phòng có calibration. Chưa có pipeline té ngã/hô hấp, contact routing, Telegram hay xác nhận cảnh báo. | Giữ tên Q3 là CSI Reliability Engine theo mục tiêu nghiên cứu. Tư liệu hóa luồng chọn người nhận thành tích hợp riêng của nhánh người. |

## API hiện tại

OpenAPI cục bộ tại `/docs`. Các ảnh chụp trả JSON. Mã route hiện trả dict trực tiếp cho nhiều endpoint. [App](../../backend/app/main.py) · [Probe routes](../../backend/app/api/probe.py)

| Method và đường dẫn | Input và kết quả chính |
|---|---|
| `GET /api/health`, `GET /api/ports` | `{ok, scope: "probe-only", algorithm}` cho health và danh sách `{device, description}` cho ports. |
| `GET /api/probe/state` | Mode, connection, heartbeat/valid, firmware, counters, config, session/current truth, coverage và chẩn đoán MAC. `result` gồm Sherlock/unique/timeout, `null` khi nguồn thiếu hợp lệ. |
| `GET /api/probe/dashboard` | `probe-dashboard-v1` với `source_id`, `source`, `connection`, `status`, `t_s`, `analysis_window_s`, `truncated`, `calibration_status`, `metrics`, `history`, `clusters`. Có `location_ready` khi đủ điều kiện phân tích. Metric thiếu dữ liệu có thể là `null`. |
| `GET`, `PUT /api/probe/config` | Đọc/ghi `ProbeConfig`. PUT yêu cầu idle. |
| `PUT /api/probe/rssi` | `{rssi_min, split_session?}`. Trả config, session và previous_session. Có thể tách phiên khi được yêu cầu. |
| `POST /api/probe/connect`, `/api/probe/disconnect` | Connect dùng `{port, baud?}` với mặc định 460800, kiểm tra cổng hệ thống. Disconnect không cần body. Trả `{ok}`. |
| `GET /api/probe/sessions` và `POST /api/probe/sessions/start`, `/api/probe/sessions/stop`, `/api/probe/truth` | List/start/stop trả metadata. Start nhận `device_count`, `layout`, `devices`, `people_count?`, `notes?`. Truth nhận hai count và notes, trả dòng nhãn. |
| `GET /api/probe/replays` và `POST /api/probe/replay` | Danh sách `{name, synthetic}` gồm demo và phiên hoàn tất. POST nhận `{name, speed?}` với tốc độ 0,25–100×. |
| `POST /api/probe/sessions/{sid}/evaluate`, `/api/probe/sessions/{sid}/inspect` | Báo cáo đếm/timeline và phân tích khe/heatmap, yêu cầu phiên hoàn tất. |
| `GET /api/probe/sessions/{sid}/files/{kind}` | Tải theo whitelist `raw`, `truth`, `metadata`, `report`, `timeline`, `inspection`, `slots`, `heatmap`, `events`, `live-events`, `markers`, `diagnosis`, `probe-trace`. |
| `GET /api/probe/diagnostics?mac=…`, `POST /api/probe/markers` và `POST /api/probe/sessions/{sid}/diagnose` | Chẩn đoán MAC live. Thêm `{kind, mac?, notes?}` vào phiên serial. Có báo cáo lịch sử cho `{mac}`. |

## Schema và thời gian hiện tại

| Lớp | Contract đang chạy |
|---|---|
| UART JSONL v1 | Mỗi dòng có `v:1`, `type`, `node:"sniffer"`, `boot_id`, `ts_us` (µs từ boot), `seq` (thứ tự xuất UART). |
| `probe` | `source_mac` (MAC chuẩn, chữ thường sau parse), `rssi` (−127…0 dBm), `channel` (1…13), `frame_seq` (0…4095), `retry` mặc định `false`, `ie` mặc định rỗng hoặc chuỗi `mã:độ_dài` phân tách dấu phẩy. |
| `status` | `capture_active`, `own_mac`, `channel`, `probe_seen`, `probe_dropped`, `invalid`, `serial_errors`, `bytes_written`, `serial_baud:460800`, `sniffer_enabled`, `scan_mode:fixed\|hopping`, `dwell_ms`. |
| `channel` | `channel`, `dwell_ms`. Timestamp ghi sau khi đổi kênh. Probe còn trong queue có thể tới sau record chuyển kênh, nên dùng `channel` của packet Probe. |
| Raw phiên | `data/runtime/experiments/<id>/raw.jsonl`: `{packet, host_time, host_elapsed_s, source}` hoặc wrapper `control:{kind}` với `serial_connected`, `serial_disconnected`, `session_stopped`. Raw giữ MAC đầy đủ. |
| Nhãn và metadata | `truth.jsonl`: `{t_s, host_time, device_count, people_count, notes}`, nhãn dạng step function. Có `metadata.json`, `algorithm-events.jsonl`, `markers.jsonl` nếu được ghi, và các thư mục kết quả tùy thao tác. `metadata.sqlite3` có `probe_sessions(id, metadata)` và `events(at, kind, detail)`. API list đọc `metadata.json` từ thư mục phiên. |

Trong bản hiện tại, `host_elapsed_s` là thời gian monotonic tại collector so với lúc bắt đầu phiên, dùng chung mốc với `truth.t_s`. `host_time` là UTC ISO 8601 để đối chiếu. Replay giữ thứ tự file và ưu tiên thời gian host, giữ nguyên `ts_us` của board. Với file v1 không có wrapper, loader ghép mốc tương đối theo từng boot và không khôi phục được khoảng trống giữa boot. Heartbeat đính kèm lúc bắt đầu phiên được ghi tại `t=0` như snapshot trạng thái. Giao thức hiện chưa hiệu chỉnh độ trễ UART hay độ trôi board ↔ host. [Schema v1](../packet.schema.json) · [Giao thức](../architecture/PROTOCOL.md) · [Replay loader](../../research/evaluate.py)

## Phân loại module

| Nhóm | Tệp và vai trò |
|---|---|
| KEEP | Runtime FastAPI và cách phục vụ React, một chủ sở hữu serial, file phiên và SQLite. Giữ `firmware/common/common.h` (khởi tạo nền), `frontend/src/main.tsx` và toolchain React/Vite, `scripts/setup.sh`, `scripts/run.sh`, `scripts/serve.py`, `scripts/dev.mjs`, `scripts/flash.sh` và workflow CI làm đường build/chạy cơ sở. |
| EXTEND | `firmware/sniffer/main/{main.c,Kconfig.projbuild,CMakeLists.txt}` (thu data/control trên kênh router), `backend/app/protocol.py` (dispatch theo version/type, tái dùng validate), `research/collector.py` (một chủ sở hữu mỗi cổng, thêm nguồn RX, timestamp và record/replay), `backend/app/storage.py` (metadata/nhật ký và registry), `backend/app/main.py` gắn router mới, `frontend/src/Dashboard.tsx` thêm tab, `docs/PROTOCOL.md`, test hợp đồng và tích hợp cho phiên mới. |
| LEGACY | Đường Probe hiện tại giữ làm baseline và để đọc phiên cũ: `backend/app/probe_api.py`, `research/{stream,detectors,dashboard,ie_profile,ie_fingerprint,device_clustering,presence,in_room}.py`, `research/{inspect,evaluate,sweep,diagnose,experiment,experiment_report,cluster_counting,counting_accuracy,counting_report}.py`. Tái dùng loader v1 của `evaluate.py` qua adapter. `ProbePanel`, `DeviceOverview`, `ScopePanel`, `ResearchPanel` giữ giao diện cũ. `configs/{probe,demo,reference,counting-research,split.example}.json` vẫn là cấu hình Probe/đối chứng. |
| NEW | Registry và Registered Device Activity Monitor (Q1), thu/giải mã CSI và CSI Channel Quality Monitor (Q2), CSI Reliability Engine (Q3), schema v2 và đồng bộ capture time, router/React panel mới, cấu hình và fixture riêng. Danh sách tệp triển khai nằm trong [kế hoạch MVP](DEVICE_CSI_MVP_PLAN.md). |

`configs/probe.json` hiện đặt khe 60 s, AT/WT/DT 2/2/3, RSSI −127, heartbeat timeout 5 s. `reference.json` dùng 6/2/6. `demo.json` dùng khe 5 s và 2/2/2. `WIFI_PROBE_CONFIG` chọn cấu hình Probe, `WIFI_PROBE_DATA_DIR` chọn thư mục dữ liệu, `WIFI_DASHBOARD_CONFIG` tùy chọn nạp cấu hình clustering/presence/location và calibration. [Cấu hình](../../configs/probe.json) · [Dashboard](DASHBOARD_GUIDE.md)

## Test và lệnh hiện có

- Python kiểm tra parser, API guards, RSSI/session split, heartbeat, reconnect/reboot, MAC cache, IE, clustering/presence/location, serial ảo POSIX PTY, tương đương live/offline và các bộ đánh giá đếm theo phiên. `tests/dashboard_browser.mjs` kiểm tra React thật với FastAPI, demo/replay, lỗi API và bố cục mobile/desktop. Script này chạy riêng ngoài CI hiện tại. [Suite](../../tests) · [CI](../../.github/workflows/check.yml)

| Kiểm tra chạy lại | Kết quả |
|---|---|
| `.venv/bin/python -m pytest -q` (Python 3.12.16) | 142 pass, một cảnh báo deprecation của Starlette/AnyIO. Chạy ngoài sandbox để bài UART ảo có quyền truy cập PTY. |
| `npm run build` (Node 22.23.4) | TypeScript và Vite build thành công. |
| `node --test tests/dashboard_browser.mjs` (Playwright và Chrome headless) | 1 pass. Chạy với quyền bind loopback. |
| `idf.py set-target esp32c3` và `idf.py build` (ESP-IDF 5.5.4) | Build thành công trong bản sao sạch tại `/tmp`, có tải dependency cJSON. Binary Probe `0xb98f0` byte. |
| `bash -n` và `node --check` | Đạt cho các script shell chạy/cài/nạp và file test browser. |

Kết quả trên xác minh phần mềm và khả năng build firmware Probe. Kiểm chứng CSI, chất lượng RF và human sensing cần phiên thu vật lý có nhãn.

```bash
# Cài dependency, chạy build và test phần mềm từ gốc repo
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
npm run build
.venv/bin/python -m pytest -q

# Chạy ứng dụng đã build hoặc chế độ phát triển
bash run.sh
# Hoặc chạy riêng chế độ phát triển
npm run dev

# Browser test sau khi build, với Node 22 và Chrome
npm install --prefix /tmp/pbl3-dashboard-browser playwright
DASHBOARD_PLAYWRIGHT_MODULE=/tmp/pbl3-dashboard-browser/node_modules/playwright/index.mjs \
  node --test tests/dashboard_browser.mjs

# Build firmware theo CI, từ gốc repo, với ESP-IDF 5.5.4 đã cài
source ~/esp/esp-idf/export.sh
cd firmware/sniffer
idf.py set-target esp32c3
idf.py build
```
