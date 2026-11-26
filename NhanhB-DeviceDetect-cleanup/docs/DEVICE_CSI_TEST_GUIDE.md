# Hướng dẫn thực nghiệm Device & CSI

## Chuẩn bị

Chạy từ `~/PBL3/NhanhB-DeviceDetect-cleanup`. Dùng URL mà terminal in ra. Khi cổng 8000 đã được dùng, script có thể chọn cổng khác. Dùng một dashboard để giữ USB và đóng serial monitor trước khi kết nối.

```bash
npm run build
bash run.sh
.venv/bin/python -m serial.tools.list_ports -v
```

Mở **Device & CSI** và chọn **Nguồn hiện tại**. Chọn Serial Port và để UART **Tự dò** hoặc chọn **460800** cho firmware Activity. Bấm **Kết nối sniffer**. Tab này kết nối trực tiếp với collector chung và không cần khởi động Legacy / Probe.

### Xác nhận đúng profile firmware

Trong **Kết nối và chẩn đoán sniffer**, tìm `DEVICE_ACTIVITY_FIXED_CHANNEL`, `fixed`, kênh router, phiên bản firmware, heartbeat cập nhật và 460800 baud. Bản firmware cũ có thể thiếu phiên bản hoặc một số bộ đếm. Queue Drops chỉ hiển thị số khi firmware xuất bộ đếm đó. Capture Activity hiện tổng hợp bằng bộ đếm trong RAM và chưa có trường queue drop riêng.

`PROBE_BASELINE` hoặc `FIRMWARE_MODE_UNSUPPORTED` cho biết board đang chạy profile Probe, kể cả khi đã nạp thành công ở 460800. Firmware Activity hiện dùng kênh được biên dịch vào image. Đổi kênh bằng menuconfig, build và flash profile Activity sau khi tự xác nhận board và cổng. Mỗi board chạy một profile tại một thời điểm. Chuyển tab không đổi firmware hoặc đóng serial.

```bash
bash scripts/sniffer.sh menuconfig activity
bash scripts/sniffer.sh build activity
# Chỉ chạy sau khi xác nhận đúng board và đã nhả USB
bash scripts/sniffer.sh flash activity /dev/ttyUSB0
```

Trong **WiFi research sniffer**, chọn `DEVICE_ACTIVITY_FIXED_CHANNEL`, đặt kênh chính 2,4 GHz của router và điền MAC Wi‑Fi của thiết bị đã đồng ý vào **Registered MACs**. Mặc định profile Activity là kênh 6. Firmware kiểm tra kênh theo vùng được cấu hình khi khởi động. Tên file cấu hình local là `firmware/sniffer/sdkconfig.activity.local`.

## Q1 trên Vivo Y20, chưa cần CSI RX

1. Đặt router ở kênh 6 cố định, hoặc dùng đúng kênh đã build vào firmware. Kiểm tra điện thoại nối mạng 2,4 GHz và lấy MAC riêng mà nó dùng trên SSID này. Khi USB đang ngắt, đăng ký cùng MAC và kênh trong **Thiết bị đăng ký**. Nếu mục VIVO đã có đúng MAC và kênh, dùng mục hiện tại.
2. Kết nối sniffer, xác nhận `fixed`, đúng kênh và heartbeat hoạt động. Để điện thoại ở trạng thái nền khoảng 20 giây. Khi đã thấy hoạt động của thiết bị ít nhất một lần trong boot hiện tại và có đủ coverage, các cửa sổ yên lặng có thể báo `NO_OBSERVED_ACTIVITY`.
3. Bấm **Bắt đầu ghi Q1**, ghi dấu mốc `Bắt đầu tải xuống` ngay trước khi tạo lưu lượng trên Vivo. Tải dữ liệu qua Wi‑Fi trong 20–30 giây, thêm dấu mốc `Kết thúc tải xuống`, rồi để yên ít nhất 15 giây và kết thúc capture. Có thể làm thêm lượt tải lên để đối chiếu.
4. Xem bảng `OBSERVED_ACTIVE`, Frames/s, Bytes/s, RSSI và Last Seen của VIVO. Trong **Hoạt động thiết bị · Q1**, chọn VIVO để xem chuỗi cửa sổ 10 giây. Trục thời gian biểu đồ tính từ boot board, còn dấu mốc Q1 tính từ lúc bắt đầu capture theo đồng hồ máy chủ. RSSI là giá trị cực đại quan sát được trong cửa sổ và có thể đến từ AP ở chiều downlink. CSI Reliability có thể vẫn `UNKNOWN` với `CSI_NOT_CONNECTED`.
5. Bấm **Kết thúc Q1** trước khi xuất **Q1 CSV**. Để kiểm tra phát lại, ngắt sniffer, chọn capture đã lưu rồi bấm **Phát lại Q1**. Chọn chế độ LIVE và kết nối USB để quay lại lượt đo thật.

## Q2 và Q3

### Phiên LIVE với CSI RX adapter

1. Bấm **Bắt đầu ghi Q2/Q3 LIVE**. Chọn phiên trên dashboard và lấy ID đầy đủ qua API danh sách hoặc URL tải CSV. Dùng cùng phiên để lưu các báo cáo Q2 và Q3 trên cùng batch. Q1 vẫn ghi độc lập khi chưa có adapter CSI.
2. Chuẩn hóa dữ liệu CSI RX thành `csi-quality-input-v1` theo hợp đồng hiện có. Mỗi batch gửi `{ "offset_us": ..., "trace": ... }` với `trace.provenance=live_adapter`, duration chia hết cho 10 giây và offset tính từ đầu phiên. Chỉ gửi cửa sổ đã kết thúc theo đồng hồ phiên. API từ chối batch chồng lấn hoặc dữ liệu `synthetic` trên LIVE. Q2 dùng metadata RX và nguồn phát tham chiếu nếu có. Q3 chỉ dùng bằng chứng CSI và Activity đã đồng bộ theo báo cáo hiện hành. [Hợp đồng CSI Quality](implementation/CSI_CHANNEL_QUALITY.md)
3. Chọn tệp JSON và bấm **Nạp batch LIVE**, hoặc gửi từ adapter vào `POST /api/device-csi/reliability/sessions/<id>/batches`. Dùng cửa sổ 1 hoặc 10 giây. Nếu cần đối chiếu CSI với Q1 trong các phép tính Q2/Q3, batch phải có các khoảng sniffer đã chuẩn hóa và mốc đồng hồ phù hợp. Việc mở USB Q1 không tự đồng bộ hai đồng hồ.
4. Ghi dấu mốc khi thao tác. Với phiên LIVE dùng chung, dấu mốc xuất hiện ở cả Q2 CSV và Q3 CSV. Chọn Q2 hoặc Q3 tại **Nguồn dấu mốc và CSV** để tải bảng tương ứng. Bấm **Kết thúc Q2/Q3 LIVE** sau batch cuối. Phiên đã kết thúc vẫn cho đọc và xuất CSV.

### REPLAY và DEMO

- **REPLAY Q1** phát lại capture UART đã lưu. Không cần USB hoặc CSI RX để xem dữ liệu đã ghi.
- **REPLAY Q2/Q3** nhập trace Q2 theo hợp đồng replay hiện có, chọn trace và bấm **Phân tích Q3 Replay** nếu cần kết quả Q3. Q2 replay hiện nhận provenance `synthetic`; không gán dữ liệu chưa xác minh thành LIVE. Với replay hoặc demo, nhập mốc giây của phiên khi ghi dấu mốc.
- **DEMO** chạy bằng nút **Chạy demo Device & CSI**. Dữ liệu tổng hợp dùng để thử giao diện và luồng phân tích. Kiểm tra cột `mode` và `provenance` khi so sánh CSV.

## CSV và chẩn đoán

CSV UTF‑8 có dòng `session`, dòng `window` và dòng `marker`. Dòng window Q1 ghi ID thiết bị, boot ID, kênh, độ phủ, chỉ số và lý do thiếu dữ liệu. Q2 ghi các bộ đo CSI Availability/Quality và lý do thiếu báo cáo loss hoặc activity. Q3 ghi nhãn, mã lý do, phiên bản cấu hình và nguồn bằng chứng. Ô thiếu dữ liệu để trống. Q1 CSV giữ chế độ nguồn ghi là `LIVE` và ghi provenance `recorded_uart`; việc mở lại capture trên dashboard được gắn `REPLAY`. CSV dùng ID thiết bị và tên đăng ký, dữ liệu capture đã thay MAC bằng ID.

| Dấu hiệu | Kiểm tra |
| --- | --- |
| `SNIFFER_DISCONNECTED` | Cắm USB, dùng đúng dashboard giữ cổng và kiểm tra tiến trình bằng `fuser -v /dev/ttyUSB0`. |
| `AWAITING_ACTIVITY_HEARTBEAT` hoặc `HEARTBEAT_STALE` | Đối chiếu tốc độ UART, cable, cổng serial và tiến trình số hóa. |
| `FIRMWARE_MODE_UNSUPPORTED` | Đối chiếu capture mode. Nạp đúng profile Activity nếu thực hiện Q1. |
| `CHANNEL_MISMATCH` | So kênh router, firmware và registry thiết bị. |
| `NO_ACTIVITY_RECORDS` | Heartbeat có mặt và chưa có bản tin `activity_sample`. Tạo lưu lượng kiểm thử và kiểm tra bộ đếm theo loại. |
| `NO_REGISTERED_DEVICE_MATCH` | So MAC của đúng SSID với cả cấu hình firmware và registry. Chờ khung có địa chỉ gán được. |
| Thiếu coverage, `invalid_line`, `sequence_gap` | Chờ đủ cửa sổ 10 giây và xem Parsing Errors, heartbeat và bộ đếm UART. |
| `CSI_NOT_CONNECTED` | Adapter CSI chưa có dữ liệu. Q1 vẫn có thể nhận thiết bị và hiển thị thông lượng. |

## Kiểm thử và trạng thái nghiệm thu

```bash
.venv/bin/python -m pytest -q
npm run build
.venv/bin/python -m backend.app.device_activity_protocol tests/fixtures/device_activity_v2.jsonl
# Với Playwright được cài riêng
DASHBOARD_PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node --test tests/dashboard_browser.mjs
```

| Hạng mục | Trạng thái | Bằng chứng |
| --- | --- | --- |
| Backend, schema UART, route và CSV Q1/Q2/Q3 | PASS | API và PTY xác nhận dữ liệu Q1, dấu mốc, CSV và luồng CSI đã chuẩn hóa với dữ liệu kiểm thử. |
| TypeScript và build frontend | PASS | `npm run build`. |
| Q1 chưa có CSI, biểu đồ và giữ kết nối khi chuyển tab | PASS | Kiểm thử Chrome dùng UART ảo và backend thật. |
| Profile Activity của board đang cắm | FAIL | `/dev/ttyUSB0` gửi heartbeat `PROBE_BASELINE`, 460800 baud, kênh hopping và 0 bản tin Activity. |
| VIVO, thông lượng/RSSI và các loại frame trên phần cứng Activity | NOT VERIFIED | Board đang chạy Probe. Đợt triển khai này không flash. |
| CSI RX vật lý, Q2/Q3 LIVE trên radio thật | NOT VERIFIED | Cần adapter CSI và lượt đo thực. |
