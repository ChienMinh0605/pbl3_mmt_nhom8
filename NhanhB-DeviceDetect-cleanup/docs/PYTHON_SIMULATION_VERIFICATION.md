# Kiểm nghiệm Device & CSI bằng Python

Lượt kiểm nghiệm dùng Linux PTY và dữ liệu CSI tổng hợp. Chuẩn đánh giá là [OUTPUT_SPECIFICATION.md](OUTPUT_SPECIFICATION.md). Giới hạn vật lý tiếp tục áp dụng theo [báo cáo Giai đoạn 2](STAGE_2_VERIFICATION.md).

## Chạy Dashboard và simulator

Chạy các lệnh từ `~/PBL3/NhanhB-DeviceDetect-cleanup`. Dùng Python trong `.venv` và frontend đã build.

```bash
npm run build
.venv/bin/python -m scripts.simulate_hardware --scenario S12 --seed 20261126
```

Lệnh thứ hai mở PTY, khởi động **backend và Dashboard hiện có** qua `scripts.serve` và in URL. Ví dụ chọn cổng cố định bằng `--port 8765`. Có thể chạy cấu hình Dashboard thông thường riêng bằng `bash run.sh`. Phiên PTY được lưu vào instance do simulator khởi động.

Để chọn một kịch bản cụ thể, thay `S12` bằng mã trong bảng. Các mã hợp lệ là `S01 S02 S03 S04 S05 S06 S07 S08 S09 S10 S11 S12`.

```bash
.venv/bin/python -m scripts.simulate_hardware --scenario S04
.venv/bin/python -m scripts.simulate_hardware --all --seed 20261126 --tick-delay .03
.venv/bin/python -m scripts.simulate_hardware --all --seed 20261126 --tick-delay .03 --exit-after-run
```

Lệnh thứ hai giữ Dashboard mở sau khi chạy hết. Lệnh thứ ba dùng để kiểm nghiệm tự động và trả exit code 1 nếu có ca FAIL. Mỗi lượt sử dụng hai cửa sổ virtual 10 giây. `--tick-delay` điều chỉnh thời gian chờ thật giữa hai tick 1 giây; timeout heartbeat vẫn chạy theo đồng hồ collector. Seed lặp lại các mẫu RSSI, khoảng đến và vị trí bỏ gói.

Trong prompt `simulation>` sau khi cửa sổ đã đóng:

| Lệnh | Tác dụng |
|---|---|
| `run S01` … `run S12` | Chọn và chạy kịch bản chuẩn, in ID phiên và kết quả. |
| `device on` / `device off` | Đặt thiết bị tạo hoặc ngừng phát dữ liệu ở lượt tiếp theo. Dùng S02 để thấy im lặng **sau khi đã xác minh binding**. |
| `channel 11` / `csi-channel 11` | Đặt kênh sniffer hoặc kênh CSI từ 1 đến 13 cho lượt tiếp theo. Registry của thiết bị mẫu dùng kênh 6. |
| `traffic low` / `traffic high` | Đặt tổng lưu lượng kênh 40 hoặc 180 frame/s. |
| `csi good` / `csi loss` / `csi jitter` / `csi off` | Chọn RX ổn định, mất gói, khoảng đến bất thường hoặc mất RX. |
| `disconnect on` / `disconnect off` | Bật hoặc tắt việc đóng PTY sau cửa sổ đầu. |
| `start` | Chạy lại với cấu hình đang chọn. Lượt có chỉnh thông số hiện `RUN` để phân biệt với phép kiểm preset. |
| `stop` hoặc Ctrl+C | Dừng simulator và backend do simulator mở. Ctrl+C cũng dừng khi đang phát. |

## Xem kết quả và xuất CSV

1. Mở URL in trong Terminal. Trong **Device & CSI**, chọn **SIMULATION** ở **Nguồn dữ liệu**.
2. Chọn **Phiên CSI** theo 8 ký tự đầu của ID in sau `id=`. Chọn **Cửa sổ CSI → 10 giây** và **Bằng chứng → CSI + sniffer hợp lệ** để đối chiếu cùng biên với Q1.
3. Đọc trạng thái, số khung, byte, RSSI và độ phủ ở **Q1 Device Activity**. Đọc RX/TX rate, loss, jitter, noise floor và callback bị lọc ở **Q2 CSI Quality**. Đọc reliability, alignment, coverage và evidence source ở **Q3 CSI Reliability**. Khi mất dữ liệu, xem mã lý do cùng `UNKNOWN` hoặc `NOT AVAILABLE`.
4. Tại **Phiên thực nghiệm**, chọn Q1, Q2 hoặc Q3 trong **Nguồn dấu mốc và CSV**, rồi bấm **Xuất Q… CSV**. S12 cũng tự tải và lưu cả ba CSV trong thư mục lượt đó. Các dòng cửa sổ có `source=SIMULATION` và cùng ID phiên. Q1 xuất các cửa sổ UART đã đóng. Khi S11 ngắt PTY, Dashboard hiển thị snapshot mất nguồn còn CSV Q1 giữ cửa sổ đã thu trước lúc ngắt.

## Tái sử dụng và cách ly dữ liệu

| Thành phần | Cách kiểm nghiệm |
|---|---|
| Simulation Mode | Dùng phiên `SIMULATION`, báo cáo timeline và route xuất CSV hiện có. Nút mô phỏng tích hợp sẵn vẫn phục vụ fixture ngắn. |
| Virtual UART | Dùng cùng cơ chế PTY với kiểm thử trước. Simulator phát JSONL v2 gồm `channel`, `status` và `activity_sample` với phiên bản `python-pty-v2`, profile fixed, RSSI, số frame/byte, sequence và counter. UART Activity hiện cấu hình kênh khi khởi động; không có lệnh đổi kênh UART hay ACK/NACK ở lớp điều khiển serial. |
| Serial Collector, parser và Q1 | pySerial đọc đầu slave PTY. Parser v2 kiểm tra bản tin, collector dùng registry/HMAC, còn `ActivityMonitor` tính độ phủ và kết quả cửa sổ. Mất heartbeat và tháo PTY đi qua các nhánh lỗi thật của collector. |
| CSI fixture và adapter | Sinh các dòng theo cột `csi.csv` của logger, đưa qua `import_logger_csi`, ghép counter TX của bộ phát ảo vào mẫu đã nhận và dùng `csi-quality-input-v1`. Q2 tính loss và jitter từ đầu vào. Đồng hồ CSI và PTY dùng mốc virtual chung. |
| Q3, Dashboard và CSV | Backend xây cửa sổ đối chiếu từ các khoảng SNF hợp lệ do collector quan sát. Request CSI ảo không được tự cung cấp số liệu sniffer để bypass PTY. Q3 dùng engine hiện tại, Dashboard và CSV đọc cùng kết quả. Kỳ vọng kịch bản chỉ được đối chiếu sau khi nhận output API. |
| Cách ly | Backend PTY chỉ nhận đường PTY được cấu hình, khóa ghi capture LIVE và tạo phiên CSI LIVE. Dữ liệu mặc định nằm trong `data/python-simulation/run-*`, tách khỏi runtime thông thường. Simulator dùng cùng ID cho snapshot Q1, Q2/Q3 và CSV của lượt. CLI từ chối `--output` nằm dưới thư mục LIVE trước khi tạo file. |

## Kết quả chạy thực tế

Lượt `--all --seed 20261126 --tick-delay .03 --exit-after-run` trả mã 0. Bằng chứng của lượt này nằm ở `data/python-simulation/run-0j14scm3`, với ID S12 `5115727bc24e4aa89bd3f0241342d6f3`. Kết quả dưới đây lấy cửa sổ cuối của CSI 10 giây và trạng thái Q1 tương ứng.

| Ca | Đã quan sát | Trạng thái |
|---|---|---|
| S01 | Q1 `OBSERVED_ACTIVE`, 120 frame, 14.400 byte và độ phủ 1. | PASS |
| S02 | Q1 `NO_OBSERVED_ACTIVITY`, 0 frame, RSSI `null`, độ phủ 1. | PASS |
| S03 | Q1 `UNKNOWN` với `wrong_channel`, số frame `null`. | PASS |
| S04 | Collector phát hiện `HEARTBEAT_STALE`. Cửa sổ Q1 sau đó là `UNKNOWN` với `heartbeat_gap`. Q3 dùng `CSI_ONLY`. | PASS |
| S05 | Q2 `GOOD`, RX 10 gói/s, loss 0, jitter khoảng 2,54 ms, `n_filtered=40`. | PASS |
| S06 | Q2/Q3 `DEGRADED`, RX 7,5 gói/s, TX 10 gói/s, loss 0,25 và jitter khoảng 60,29 ms. | PASS |
| S07 | Q3 `GOOD`, `MATCHED`, độ phủ 1 và `CSI_AND_SNIFFER`. | PASS |
| S08 | Q3 `GOOD` theo CSI, `MISMATCH` và `CSI_ONLY`. | PASS |
| S09 | Kênh quan sát 180 frame/s. CSI ổn định và Q3 vẫn `GOOD`. | PASS |
| S10 | Q2/Q3 `UNKNOWN`, RX rate `null`, `INSUFFICIENT_DATA`. | PASS |
| S11 | Collector phát hiện mất đầu PTY, Q1 `UNKNOWN`, Q2 `GOOD`, Q3 dùng `CSI_ONLY`. | PASS |
| S12 | API, Dashboard và ba file CSV cùng phiên. Q1 120 frame, Q2 jitter khoảng 2,62 ms và Q3 dùng `CSI_AND_SNIFFER` trên cửa sổ `[10,20)` giây. | PASS |

| Kiểm thử | Kết quả |
|---|---|
| Python CLI, 12 kịch bản và điều khiển Terminal | **PASS**. Chạy cả suite, sau đó chạy lại bằng stdin để đổi thiết bị/kênh/lưu lượng/jitter, ngắt PTY, chuyển sang S02 và dừng bằng `stop`. |
| Backend unit/integration và Legacy regression | **PASS**. `.venv/bin/python -m pytest -q` cho 205 bài đạt, một cảnh báo deprecation của Starlette TestClient/AnyIO. |
| TypeScript và Vite | **PASS**. `npm run build` thành công. |
| Chrome/Playwright | **PASS**. 2 bài đạt, gồm Dashboard hiện có và ca S12 qua CLI Python. S12 tải ba CSV từ UI, đối chiếu số liệu API và kiểm nghiệm chặn ghi LIVE trong backend PTY. |
| ESP32/RF và giao thức UART CSI của RX vật lý | **NOT RUN**. Mô phỏng chỉ xác minh schema đầu vào phần mềm, clock ảo và các đường xử lý backend. Phần cứng vẫn **NOT VERIFIED**. |


Lệnh chạy lại kiểm thử phần mềm:

```bash
.venv/bin/python -m pytest -q
npm run build
DASHBOARD_PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node --test tests/dashboard_browser.mjs
```

Có thể bỏ `DASHBOARD_PLAYWRIGHT_MODULE` nếu Node đã tìm được package Playwright trong môi trường đang dùng. Kiểm thử dùng Chrome tại `/usr/bin/google-chrome` hoặc đường dẫn đặt qua `DASHBOARD_TEST_CHROME`.
