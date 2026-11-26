# Sửa luồng Device Activity trên ESP32-C3

## Nguyên nhân gốc

Dashboard đang nhận bản tin Probe JSONL v1 từ CH340 tại `/dev/ttyUSB0`. API Probe đã trả heartbeat hợp lệ, `scan_mode=hopping` và `serial_baud=921600`. Cùng thời điểm đó, registry Device & CSI có thiết bị `VIVO` ở kênh 6, nhưng API Device Activity có `source=null`, thiếu heartbeat v2, cửa sổ và dữ liệu khớp thiết bị. Phiên CSI hiện có trong danh sách là demo. Thiếu CSI RX giải thích trạng thái CSI Reliability, còn số liệu hoạt động Wi-Fi thiếu vì board đang chạy firmware Probe.

Hai profile được chọn lúc biên dịch. `CMakeLists.txt` của component chỉ đưa `activity_capture.c` và `activity_frame.c` vào build Activity. `app_main()` chỉ gọi `activity_capture_start()` với profile đó. Trước thay đổi, script flash dùng cấu hình mặc định Probe hoặc `sdkconfig` thuận tiện đang có. Việc thấy filter Data và Control trong source hoặc thiếu file tên chính xác `sdkconfig` không xác định được firmware đang chạy. Heartbeat đọc từ board mới là bằng chứng cho trường hợp này.

Backend trước đây định tuyến theo API đã bấm và màn hình Device & CSI lấy chỉ số lưu lượng kênh từ báo cáo CSI Reliability. Khi board phát Probe v1, dashboard Device & CSI vì vậy không phân biệt được firmware sai với kết nối vắng mặt. Ngay cả khi Q1 đã có bản tin, thẻ lưu lượng vẫn phụ thuộc báo cáo CSI.

## Đường dữ liệu sau thay đổi

```text
Một ESP32-C3, một profile firmware, một cổng UART
  └─ ProbeService mở serial độc quyền
     ├─ Heartbeat v1 → parser Probe → Stream/Sherlock → Legacy / Probe
     └─ Heartbeat v2 → parser Activity → HMAC(MAC, kênh) → ActivityMonitor
                                               └─ cửa sổ 10 s → API Device & CSI
CSI RX → pipeline CSI Quality / Reliability riêng
```

Trong chế độ tự dò, collector thử 460800 rồi 921600 và xác nhận từ `status` hợp lệ có `serial_baud` trùng tốc độ cổng. Parser v2 hiện yêu cầu 460800. Parser v1 tiếp tục nhận firmware cũ ở 921600. `POST /api/probe/connect` với `baud` chỉ định vẫn dùng đường kết nối Probe ở tốc độ cố định. Cả hai màn hình dùng chung dịch vụ và cổng. Yêu cầu nối lại cùng cổng ở chế độ tự dò giữ nguyên phiên serial. Chuyển tab chỉ thay màn hình và truy vấn trạng thái.

Activity thu thống kê một giây từ callback Wi-Fi. `Addr1` và `Addr2` là endpoint radio RA/TA khi layout cung cấp chúng. `activity_frame_addresses()` xử lý SA/DA theo ToDS/FromDS và header bốn địa chỉ, nhưng bộ đếm thiết bị dùng RA/TA quan sát trực tiếp. ACK/CTS chỉ cung cấp RA. Các loại thiếu endpoint có thể dùng góp vào `unattributed`. Mỗi thiết bị khớp được tính tối đa một lượt cho mỗi frame. Firmware xử lý header và metadata, xuất bộ đếm và RSSI, không xuất payload hoặc nội dung giải mã. [Tài liệu Sniffer ESP-IDF 5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-guides/wifi.html#wi-fi-sniffer-mode)

MAC đăng ký viết dạng dấu `:` và chuyển chữ thường trước khi tính HMAC-SHA256 theo MAC và kênh. Firmware cần cấu hình riêng MAC Wi-Fi của mạng thử nghiệm trước khi build. Registry SQLite giữ HMAC, nên không thể lấy lại MAC gốc để tự cấu hình board. Khi nhận mẫu, backend đối chiếu HMAC, thay MAC bằng `device_id` trước khi ghi capture và giữ metadata tối thiểu cho bản tin bị bỏ.

Heartbeat đóng khoảng đo và cung cấp chênh lệch bộ đếm. Monitor xuất Frames/s và Bytes/s theo phần cửa sổ 10 giây có coverage đủ. RSSI là cực đại trong cửa sổ. Last seen là cuối khoảng board đã xác nhận có mẫu. Lưu lượng kênh dùng chênh lệch số callback hợp lệ trên kênh, kể cả frame không khớp registry. Các dữ liệu Q1 có thể hiển thị khi CSI Reliability vẫn `UNKNOWN`. `NO_OBSERVED_ACTIVITY` yêu cầu đã xác minh được binding trong boot đó và cửa sổ hợp lệ không có mẫu khớp. Thiếu heartbeat, thiếu coverage, sai kênh hoặc chưa xác minh binding dẫn tới `UNKNOWN`. Số liệu quan sát không xác định thiết bị đã rời nhà.

## File và hàm sửa

| Phần | Thay đổi |
| --- | --- |
| `firmware/sniffer/main/main.c`, `main/CMakeLists.txt` | `app_main()` và `sniffer_add_uart_status()` dùng cùng baud từ sdkconfig và báo phiên bản app. Component thêm `esp_app_format`. |
| `firmware/sniffer/main/activity_capture.c` | `receive_activity()` cộng tổng Management, Data, Control theo loại. `emit_status()` xuất các bộ đếm. |
| `firmware/sniffer/main/Kconfig.projbuild`, `sdkconfig.defaults`, `sdkconfig.activity`, `scripts/sniffer.sh`, `scripts/flash.sh` | Profile riêng, target ESP32-C3, thông tin kênh vùng và lệnh build/flash tách rõ. |
| `backend/app/protocol.py`, `backend/app/device_activity_protocol.py`, `docs/packet.schema.json`, `docs/device-activity.schema.json` | Phiên bản firmware tùy chọn, parser v2 nhận thêm bộ đếm mới và tiếp tục đọc bản tin cũ. |
| `research/collector.py`, `research/device_activity.py` | `detect_serial_status()`, `ingest()`, `activity_snapshot()` và `ActivityMonitor.snapshot()` định tuyến theo heartbeat, đưa chẩn đoán và lưu lượng kênh ra API. |
| `backend/app/api/device_activity.py`, `backend/app/api/probe.py` | Hai API dùng chung nguồn serial. Có kiểm tra phiên đang ghi trước khi đổi hoặc ngắt nguồn từ tab còn lại. |
| `frontend/src/device-csi/DeviceCsiPanel.tsx`, `device-csi.css`, `frontend/src/legacy-probe/ProbePanel.tsx` | Chẩn đoán kết nối và firmware, lý do `UNKNOWN`, lưu lượng Q1 độc lập với CSI, thông báo firmware Activity trong Legacy. |
| `tests/test_api_protocol.py`, `tests/test_registered_device_monitor.py`, `tests/dashboard_browser.mjs` | Kiểm thử UART ảo, registry và HMAC, tách pipeline và chuyển tab. |

## Cấu hình firmware

| Profile script | Target | Mode | Kênh mặc định | UART |
| --- | --- | --- | --- | --- |
| `activity` | `esp32c3` | `DEVICE_ACTIVITY_FIXED_CHANNEL`, JSONL v2 | 6 cố định, chọn 1–13 rồi kiểm tra theo vùng lúc khởi động | 460800, 8N1 |
| `probe` | `esp32c3` | `PROBE_BASELINE`, JSONL v1 | Hopping, cấu hình vùng `VN` | 460800, 8N1 |
| `probe-fixed` | `esp32c3` | `PROBE_BASELINE`, JSONL v1 | 6 cố định | 460800, 8N1 |

`bash scripts/sniffer.sh build` mặc định chọn `activity`. `idf.py build` ở mức thấp vẫn dùng mặc định Kconfig Probe. Script chọn riêng `build/<profile>` và `sdkconfig.<profile>.local`, với `sdkconfig.defaults` và overlay tương ứng. Lần build sạch tạo các config local từ file được version control. Các profile đã được build với ESP-IDF 5.5.4. Bản Activity kiểm thử dùng registry firmware rỗng, mặc định cho phép quan sát tổng kênh. Bản dùng cho VIVO cần cấu hình MAC đã được đồng ý tham gia.

## Schema UART và chẩn đoán

| Bản tin Q1 | Nội dung |
| --- | --- |
| `channel` | `v=2`, `node=sniffer`, `seq`, `boot_id`, `ts_us`, `channel`, `mode=DEVICE_ACTIVITY_FIXED_CHANNEL`, `scan_mode=fixed`. |
| `status` | Heartbeat gần mỗi giây, capture mode, channel, baud, số MAC trên board, tổng callback, lỗi, frame không gán được và frame chưa đăng ký. Field mới tùy chọn cho firmware cũ gồm `firmware_version`, `management_frames`, `data_frames`, `control_frames`. |
| `activity_sample` | MAC đăng ký hoặc `null`, loại frame, `n_frames`, `n_bytes`, `tx_frames`, `rx_frames`, `block_ack_frames`, `rssi_max_dbm`, kênh và thời lượng. `ts_us` là đầu khoảng đo theo đồng hồ board. |

`GET /api/device-csi/state` trả `channel_frames_per_s`, trạng thái thiết bị và `diagnostics`. Chẩn đoán có thời điểm máy chủ nhận bản tin cuối theo UTC, tuổi heartbeat theo đồng hồ monotonic, phiên bản, mode, baud, kênh, bộ đếm và số lỗi parser sau khi chốt giao thức. Dashboard hiện mã `SNIFFER_DISCONNECTED`, `FIRMWARE_MODE_UNSUPPORTED`, `CHANNEL_MISMATCH`, `NO_ACTIVITY_RECORDS`, `NO_REGISTERED_DEVICE_MATCH` và `HEARTBEAT_STALE` khi phù hợp. CSI RX báo `CSI_NOT_CONNECTED` riêng.

## Build và kiểm tra

| Hạng mục | Kết quả | Bằng chứng |
| --- | --- | --- |
| ESP-IDF và ba profile ESP32-C3 | PASS | ESP-IDF 5.5.4. Build `activity`, `probe`, `probe-fixed` thành công và đối chiếu profile thực trong các sdkconfig local. |
| UART schema, parser và C parser header | PASS | Validator nhận 7/7 dòng fixture v2. Suite kiểm Python schema mới và chạy bộ test C cho địa chỉ 802.11. |
| Backend và Legacy backward compatibility | PASS | 196 bài kiểm thử, gồm UART ảo v1 460800/921600, route v1/v2, HMAC matching, dữ liệu thiếu và bảo vệ phiên ghi. |
| API qua PTY | PASS | `/api/ports`, `/api/probe/connect`, `/api/probe/state`, `/api/probe/disconnect`, `/api/device-csi/connect`, `/api/device-csi/state`, `/api/device-csi/disconnect`, registry, capture/replay và CSI Reliability. |
| TypeScript và production build | PASS | `npm run build` chạy `tsc --noEmit` và Vite. |
| Dashboard Chrome | PASS | Kết nối qua UART ảo. Q1 hiển thị thiết bị hoạt động, RSSI và lưu lượng kênh khi CSI `UNKNOWN`. Chuyển tab giữ boot ID, cổng và cửa sổ. Demo, Replay và bố cục mobile đều qua kiểm thử. |
| Board thật trước thay đổi | PASS | Heartbeat v1 ở 921600, hopping. `/dev/ttyUSB0` trỏ từ `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`, USB–UART CH340. Tiến trình dashboard PID 34792 đang giữ cổng lúc đo đầu. Thiết bị USB biến mất ở lần kiểm tra sau. |
| Flash firmware Activity | NOT RUN | Chờ chủ thiết bị xác nhận và thực hiện lệnh flash. |
| VIVO phát Data/Control thật và khớp registry trên board đã flash | NOT RUN | Cần board Activity, router và điện thoại. Fixture gắn nhãn chỉ kiểm thử pipeline phần mềm. |
| CSI RX thật, độ nhạy RSSI và Block Ack trên board | NOT RUN | Chưa có CSI RX hoặc trace phần cứng Activity để kiểm chứng. |

## Chạy dashboard và thực nghiệm với Vivo Y20

Từ workspace hiện tại, build web rồi chạy backend. Nếu server đã chạy, dừng và khởi động lại để nạp mã Python mới.

```bash
npm run build
bash run.sh
```

1. Cố định router thử nghiệm ở **2,4 GHz, kênh 6** và kết nối Vivo Y20. Xem MAC Wi-Fi đang dùng trong chi tiết mạng trên điện thoại. Nếu điện thoại bật MAC riêng theo SSID, dùng MAC của mạng này. Đối chiếu MAC và kênh với mục `VIVO` trong registry. Đăng ký lại nếu MAC đã thay đổi.
2. Mở menuconfig và vào **WiFi research sniffer**. Chọn profile `DEVICE_ACTIVITY_FIXED_CHANNEL`, kênh 6 và điền MAC đã đồng ý vào `Registered MACs`. Lưu cấu hình local rồi build.

   ```bash
   bash scripts/sniffer.sh menuconfig activity
   bash scripts/sniffer.sh build activity
   ```

3. Xác nhận board ESP32-C3 và cổng sau khi cắm lại. Kiểm tra cổng bằng lệnh dưới. Bấm **Ngắt sniffer** hoặc **Ngắt nguồn** để nhả cổng. Đóng chương trình serial monitor nếu đang mở.

   ```bash
   .venv/bin/python -m serial.tools.list_ports -v
   fuser -v /dev/ttyUSB0
   ```

4. Sau khi xác nhận đúng board và port, chạy lệnh flash Activity sau. Nếu path thay đổi, thay `/dev/ttyUSB0` bằng path vừa xác nhận.

   ```bash
   bash scripts/sniffer.sh flash activity /dev/ttyUSB0
   ```

5. Mở **Device & CSI**, chọn **Nguồn hiện tại**, chọn cổng và bấm **Kết nối sniffer**. Xác nhận `DEVICE_ACTIVITY_FIXED_CHANNEL`, 460800, kênh 6, firmware version và heartbeat cập nhật. Tạo lưu lượng Wi-Fi chủ động trên điện thoại và chờ ít nhất 10 giây. Kiểm tra `VIVO` có `OBSERVED_ACTIVE`, Frames/s và Bytes/s tăng, cùng RSSI khi driver cung cấp. Lưu lượng kênh có thể lên trước khi thấy thiết bị khớp. Khi CSI RX chưa kết nối, CSI Reliability vẫn `UNKNOWN`.
6. Khi cần quay lại đối chứng, ngắt kết nối serial rồi nạp `bash scripts/sniffer.sh flash probe /dev/ttyUSB0`. Dùng `probe-fixed` nếu thực nghiệm Probe cần kênh 6 cố định.

## Giới hạn kiểm chứng phần cứng

ESP32-C3 quan sát 2,4 GHz trên một kênh chính trong profile Activity. Firmware bật Data, Management và Control mà driver cung cấp. Một số frame PHY chỉ có độ dài, ACK/CTS không cung cấp TA, và RSSI của downlink có thể là tín hiệu AP. Retry và hành vi driver với frame tổng hợp ảnh hưởng việc so sánh với router. Chưa đo tỷ lệ bắt Control hoặc Block Ack, mức rơi UART, sai số RSSI, flash ID hoặc dung lượng flash thật của board. Log build xác nhận image vừa phân vùng cấu hình, còn nghiệm thu RF cần chạy quy trình thực nghiệm trên board. [API Wi-Fi ESP-IDF 5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-reference/network/esp_wifi.html)
