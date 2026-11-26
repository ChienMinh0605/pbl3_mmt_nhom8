# Báo cáo kiểm chứng MVP

Báo cáo ghi lại lần kiểm chứng trước cleanup. Tên file và mốc Git trong phần lịch sử thuộc lần chạy đó. [Kiểm chứng sau tái cấu trúc](../MIGRATION_NOTES.md)

## Git và phạm vi

- Branch `feature/device-csi-reliability`, HEAD `fada6128628fab20965406c8c2a079da34f931a4`, remote `qphuc9405/NhanhB-DeviceDetect`. Giai đoạn 1–4 đã có sửa đổi chưa commit khi audit. Baseline trước Giai đoạn 5 đạt 176 bài pytest. Các thay đổi nằm trong working tree cục bộ.
- Final verification dùng Python 3.12.16, Node 22.23.4, Chrome/Playwright, ESP-IDF 5.5.4. Firmware build trong bản sao tạm của thư mục `firmware`. Vòng này không nạp board, không đổi kênh, không push hoặc merge.

## Chức năng Q1/Q2/Q3

| Module | Đường đã kiểm tra | Phạm vi |
|---|---|---|
| Q1 Device Activity | Native firmware parser + UART v2 qua PTY → parser → trạng thái/registry → capture đã giảm thiểu MAC → phát lại/API/Dashboard | LIVE từ USB nếu có SNF v2. REPLAY đã thử bằng fixture. Sherlock Probe v1 vẫn chạy qua Legacy với API và dữ liệu cũ. |
| Q2 CSI Quality | Metadata synthetic → clock alignment → timeline 1 s/10 s → SQLite → API. Kết hợp được với capture Q1 chọn đúng boot. | RX vật lý chưa có log xác minh. Loss cần sequence TX hoặc expected TX. Chỉ báo kênh dựa trên mật độ frame quan sát. |
| Q3 Reliability | Q2 và context Q1 đúng kênh/thời gian → heuristic → phiên lưu SQLite → API/Dashboard. | DEMO/REPLAY được gắn nhãn. Hợp đồng LIVE với batch chuẩn hóa, freshness, timestamps và config đã test. CSI-only hoạt động khi Q1 thiếu hoặc API Q1 mất. |

## File Giai đoạn 5–7

| Nhóm | File |
|---|---|
| Backend | `backend/app/{main,storage,device_activity_api,csi_reliability_api}.py`, `research/{collector,csi_ingestion,csi_quality,csi_reliability,reliability_demo,reliability_evaluation}.py` |
| Frontend | `frontend/src/{Dashboard,ProbePanel,DeviceCsiPanel}.tsx`, `frontend/src/api.ts`, `frontend/src/device-csi.css` |
| Test | `tests/test_csi_reliability.py`, `tests/test_device_csi_integration.py`, `tests/test_reliability_evaluation.py`, `tests/dashboard_browser.mjs` |
| Tài liệu | `README.md`, `docs/{CSI_RELIABILITY_DESIGN,DASHBOARD_DEVICE_CSI,MVP_IMPLEMENTATION_STATUS,EXPERIMENT_PLAN,KNOWN_LIMITATIONS,UBUNTU_RUNBOOK,FINAL_VERIFICATION_REPORT}.md` |

## Test cuối

| Hạng mục | Trạng thái | Kết quả |
|---|---|---|
| Pytest toàn bộ | PASS | 193 bài, một cảnh báo deprecation của Starlette TestClient/AnyIO. |
| Frontend | PASS | `tsc --noEmit` riêng và Vite production build. Một bài Playwright chạy qua LIVE trống, DEMO, REPLAY Q1/Q2/Q3, lỗi API, mobile/desktop và Legacy. |
| Lint frontend | NOT RUN | Repo chưa có lint script hoặc dependency lint. |
| ESP32-C3 firmware | PASS | ESP-IDF 5.5.4 build đủ Probe hopping, Probe fixed, `DEVICE_ACTIVITY_FIXED_CHANNEL`. |
| API, schema, dependency và import | PASS | OpenAPI có route legacy/Q1/Q2/Q3. Validator UART nhận 7 dòng fixture, CSI adapter nhận fixture synthetic. `pip check`, `git diff --check` và shell syntax đạt. |
| Timestamp, config và session isolation | PASS | Kiểm tra anchor, lệch kênh, mẫu UART đến trễ, freshness, batch tương lai/chồng lấn, retry và quy tắc giữ theo session. |
| Privacy | PASS | Test SQLite HMAC, key `0600`, capture Q1 không xuất MAC, UI dùng ID rút gọn và input MAC được che. Raw Probe v1 vẫn mang định dạng lịch sử. |
| RF LIVE, CSI RX thật và luồng cảnh báo | NOT VERIFIED | Không thấy ESP32/USB-UART hoặc capture RX thật. Ứng dụng cảnh báo của nhánh người chưa tích hợp. |

### Ma trận tích hợp

Kết quả PASS dưới đây là kiểm tra phần mềm từ fixture, PTY hoặc test hợp đồng. Các lượt vật lý tương ứng chưa chạy.

| Ca | Kết quả |
|---|---|
| T01 · Im lặng sau khi đã xác nhận binding | PASS · `NO_OBSERVED_ACTIVITY`; chưa xác nhận binding trả `UNKNOWN`. |
| T02 · Điện thoại đăng ký có traffic | PASS · PTY/Q1 trả `OBSERVED_ACTIVE`. |
| T03 · Hai thiết bị cùng hoạt động | PASS · Tách ID và giữ cả hai trong cửa sổ Q1/Q3 replay. |
| T04 · Sau khi nguồn thiết bị im lặng hoặc ngắt Wi‑Fi | PASS · Replay mô phỏng im lặng trả `NO_OBSERVED_ACTIVITY`. NOT VERIFIED thao tác ngắt Wi‑Fi trên điện thoại thật. |
| T05 · Loss thấp | PASS · CSI ổn định giữ `GOOD`. |
| T06 · Loss cao | PASS · `DEGRADED` với reason code loss. |
| T07 · Traffic cao, CSI ổn định | PASS · `GOOD` và có cờ mật độ frame cao. |
| T08 · Traffic cao, CSI suy giảm | PASS · Context hợp lệ, `DEGRADED`, lý do CSI xuất hiện. |
| T09 · Mất sniffer | PASS · Q1 `UNKNOWN`, CSI-only vẫn chạy. |
| T10 · Mất CSI RX | PASS · `UNKNOWN` và số liệu CSI hiện tại trống. |
| T11 · Mất đồng bộ | PASS · Lỗi clock RX trả `UNKNOWN`; lỗi ghép SNF giữ CSI-only. |
| T12 · Replay đã ghi | PASS · Capture Q1 vào Q2/Q3, UI chọn source đúng ID. |
| T13 · Fallback CSI-only | PASS · Thiếu hoặc lỗi API Q1 không làm mất kết quả CSI. |
| T14 · Cảnh báo ngã | PASS ở mức hợp đồng read-only. API từ chối đầu vào điều khiển cảnh báo. NOT RUN với hệ thống cảnh báo thực. |

## Lỗi đã sửa và vấn đề còn lại

- Đã sửa kiểu TypeScript cho trường kênh và kiểm tra lại layout mobile. Đã lọc số CSI ngoài thời lượng phiên, giữ batch retry không ghi đè, ẩn chỉ số CSI stale ở LIVE và phân biệt lỗi Q1 với lỗi Q3. Các khoảng trống giữa batch được đánh dấu trên biểu đồ.
- Chưa có kết quả A/B/C trên dữ liệu thật. Runner khóa ngưỡng từ development và từ chối session/group/hash trùng trước khi đánh giá test. [Kế hoạch thực nghiệm](../experiments/EXPERIMENT_PLAN.md)
- Cần thử trên ESP32 thật với điện thoại đã đăng ký, kiểm tra khả năng bắt Block Ack, channel/heartbeat, tìm MAC theo SSID, thay đổi lưu lượng, reboot và ngắt USB. Cần capture RX thật để xác nhận định dạng, TX sequence, latency/clock anchors, `noise_floor` và `n_filtered`. [Giới hạn](KNOWN_LIMITATIONS.md)

## Demo và lệnh Ubuntu

```bash
bash scripts/setup.sh
./run.sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
npm run build
```

Trong tab **Device & CSI**, chạy DEMO, đổi 1/10 s và CSI-only/CSI+Device, xem reason codes rồi trở về LIVE trống. Có thể tạo REPLAY từ fixture Q2 và xem capture thiết bị đúng ID. Tab **Legacy / Probe** có demo và replay cũ. Lệnh firmware build/flash thủ công và Playwright có trong [Runbook Ubuntu](../UBUNTU_RUNBOOK.md).

MVP phần mềm đủ cơ sở để chuyển sang refactor và dọn repository có kiểm soát. Giữ fixture, test, calibration, dữ liệu cũ và khả năng replay khi thay đổi cấu trúc. Mốc thực nghiệm và kiểm thử RF vẫn cần chứng minh riêng.
