# Dynamic Device Registry và cấu hình runtime

Registry trên Dashboard là cấu hình mong muốn. ESP32-C3 xác nhận cấu hình đã áp dụng qua UART0. Một collector quản lý một sniffer, lọc danh sách thiết bị đã đồng ý theo kênh thu mong muốn và gửi toàn bộ danh sách của kênh đó. Registry hỗ trợ tối đa 16 thiết bị trên mỗi kênh. Kênh được giữ cố định cho tới khi người dùng yêu cầu đổi.

## Giao thức UART JSONL v2

UART0 chạy 460800 baud, 8N1. Mỗi dòng kết thúc bằng LF. Lệnh cấu hình dài tối đa 767 byte trước LF, mang `request_id` là chuỗi không rỗng tối đa 64 byte. Các trường dưới đây áp dụng cho profile Activity.

```jsonl
{"v":2,"type":"config_command","request_id":"example-1","command":"set_registry","channel":6,"macs":["02:11:22:33:44:55"]}
{"v":2,"node":"sniffer","type":"config_reply","boot_id":"0123456789abcdef","request_id":"example-1","ok":true,"registry_revision":8,"channel":6,"registered_devices":1,"runtime_config":true,"channel_min":1,"channel_max":13,"macs":["02:11:22:33:44:55"]}
{"v":2,"node":"sniffer","type":"config_reply","boot_id":"0123456789abcdef","request_id":"example-2","ok":false,"error":"invalid_channel","registry_revision":8,"channel":6,"registered_devices":1,"runtime_config":true,"channel_min":1,"channel_max":13}
```

| Lệnh | Tham số và ngữ nghĩa |
|---|---|
| `get_status` | ACK trả boot, revision, kênh thực tế, số mục, capability và dải kênh. |
| `get_registry` | ACK như `get_status`, thêm `macs` hiện tại đã sắp xếp. |
| `set_registry` | `macs` là danh sách đầy đủ. `channel` tùy chọn, mặc định giữ kênh hiện tại. Backend luôn gửi cả hai để cập nhật nguyên tử. |
| `clear_registry` | Xóa toàn bộ danh sách trên firmware, giữ kênh. |
| `set_channel` | `channel` là số kênh nguyên hợp lệ, giữ danh sách MAC hiện tại. Dashboard dùng `set_registry` cho thao tác đổi kênh để gửi đúng danh sách của kênh đích. |

Firmware chuẩn hóa thứ tự MAC, từ chối mục trùng, địa chỉ multicast, địa chỉ toàn số 0, mục sai định dạng hoặc quá 16 mục. Dải kênh là giao của 1–13 và vùng Wi‑Fi do firmware báo. Một yêu cầu hợp lệ được phản hồi ACK `ok=true` hoặc NACK `ok=false` với mã `error`; các dòng sai JSON, quá dài hoặc thiếu ID hợp lệ được bỏ qua. Mã NACK gồm `invalid_registry`, `invalid_channel`, `invalid_command`, `unknown_command`, `channel_apply_failed` và `nvs_write_failed`.

ACK của lệnh thay đổi trả cấu hình thực tế, gồm danh sách MAC. Lệnh lặp với cấu hình giống hệt giữ nguyên revision và không ghi lại NVS. Một thay đổi thực sự ghi một blob NVS với kênh, danh sách và revision. Firmware khôi phục blob đã kiểm tra khi khởi động, dùng Kconfig nếu chưa có blob hợp lệ. Task UART RX đọc và xếp lệnh, task output là nơi duy nhất ghi JSONL và áp dụng cấu hình. Tra MAC, hoán đổi cấu hình và cập nhật bộ đếm có cùng khóa với callback. UART, đổi radio và NVS chạy ngoài callback. Nếu đổi kênh thất bại, firmware trả NACK và giữ hoặc khôi phục kênh cũ; driver không khôi phục được thì firmware khởi động lại để đọc cấu hình lưu.

`config_reply` không có `seq` hoặc `ts_us` và không đi vào luồng đo. `status` báo `runtime_config`, dải kênh và `registry_revision`. `channel` và `activity_sample` mang cùng revision. Trường bổ sung là tùy chọn trong parser để đọc v2 cũ. [Schema telemetry và reply](../device-activity.schema.json)

## Backend và Q1

- Dashboard theo dõi `SYNCED`, `PENDING`, `OFFLINE`, hoặc `SYNC_FAILED`, cùng kênh mong muốn, kênh/đếm/revision firmware và lý do lỗi. MAC trùng trên cùng kênh hoặc vượt giới hạn trả 409; dữ liệu sai định dạng/kênh ngoài vùng trả 422.
- Backend ghép ACK bằng `request_id`, boot, revision, kênh, số mục và danh sách MAC. Tối đa ba lần gửi cùng ID, mỗi lần chờ tối đa một giây cho reply. API đột biến trả 200/201 khi áp dụng đã được xác nhận, hoặc 202 khi cấu hình mong muốn đã được lưu mà chưa được xác nhận. `X-Registry-Sync` mô tả trạng thái. Đổi nhãn cục bộ theo API cũ vẫn trả 200 nếu thao tác không gửi xuống firmware.
- Backend gửi lại cấu hình khi gặp boot hoặc kết nối mới. Heartbeat lặp cùng cấu hình không tạo lượt gửi mới. Sau timeout/NACK, dùng **Đồng bộ lại** để thử lại. UI firmware cũ báo không hỗ trợ runtime, có thể ngắt cổng và chuẩn bị registry cục bộ. SIMULATION và REPLAY không phát lệnh UART.
- Khi chờ ACK hoặc gặp revision không khớp, Q1 không ghi telemetry chưa xác nhận. Cửa sổ chuyển tiếp thiếu bằng chứng được đánh dấu `UNKNOWN`. Giữ lưới 10 giây và kết quả đã đóng. Capture ghi revision ban đầu và sự kiện đổi registry cùng snapshot theo ID; CSV có thêm cột `registry_revision`. Timeline và Replay đọc cùng bộ kết quả. Xóa một mục trong registry hiện tại không xóa ID hoặc cửa sổ đã lưu.
- MAC chỉ được lưu để cấp cấu hình cho thiết bị đã có đồng ý. SQLite và khóa HMAC dùng quyền `0600`. MAC không xuất hiện trong capture, timeline, CSV hoặc lỗi validation. Chỉ dùng API cấu hình trên máy cục bộ. Các mục cũ chỉ có HMAC cần sửa và nhập lại MAC của đúng mạng; HMAC không thể dùng để khôi phục MAC gửi xuống board.

## Build và kiểm nghiệm trên ESP32-C3

Chạy từ gốc workspace, dùng môi trường ESP-IDF của dự án. Xác nhận đúng board, cổng UART và profile Activity trước khi chạy lệnh flash. Đóng serial monitor hoặc ngắt USB trong Dashboard để nhả cổng.

```bash
bash scripts/sniffer.sh build activity
bash scripts/sniffer.sh flash activity /dev/ttyUSB0
npm run build
bash run.sh
```

1. Chọn **LIVE**, kết nối đúng cổng ở 460800 hoặc tự dò. Xác nhận `SYNCED` và kênh thực tế. Chọn kênh thu trùng kênh chính 2,4 GHz của mạng thử nghiệm.
2. Đăng ký một thiết bị bằng MAC mà máy dùng trên SSID đó. Thêm máy thứ hai cùng kênh, rồi sửa và xóa một mục. Kiểm tra count, revision và kết quả đo Q1 mỗi lần firmware ACK.
3. Đang ghi Q1, đổi kênh hoặc MAC; so bảng, Timeline và CSV theo ID phiên, cửa sổ và revision. Đo riêng cửa sổ trước, trong và sau chuyển tiếp. Tạo lưu lượng để xác nhận binding trong epoch mới.
4. Với registry đã được xác nhận, tách backend khỏi cổng và reboot board. Đọc heartbeat với serial monitor để kiểm tra kênh/count/revision được khôi phục, rồi nhả cổng và kết nối Dashboard. Kiểm tra backend tự đồng bộ khi cắm lại hoặc khởi động lại.
5. Thử ở một kênh ngoài dải board báo và kiểm tra lỗi. Kiểm tra trường hợp mất cổng khi gửi cấu hình, sau đó kết nối lại. Dùng cố định một kênh trong từng pha đo.

## Kết quả kiểm thử

| Hạng mục | Kết quả |
|---|---|
| Build firmware ESP32-C3 | PASS · `activity`, `probe` và `probe-fixed`. |
| Pytest | PASS · 210 bài, gồm Legacy, Q1/Q2/Q3, parser/schema, CRUD qua PTY, ACK/NACK, timeout/retry, reboot/reconnect mô phỏng, backend restart, giới hạn, và cửa sổ/CSV không trộn revision. Có một cảnh báo deprecation của Starlette TestClient/AnyIO. |
| TypeScript/Vite và Chrome | PASS · Build frontend và 3 bài Chrome, gồm thêm/sửa/xóa cùng đổi kênh qua Dashboard với thiết bị PTY. |
| ESP32-C3 thật | NOT VERIFIED · Kiểm thử dùng peer PTY để mô phỏng reboot và config giữ qua reboot. Ghi/khôi phục NVS, đổi radio và thu frame trên board vật lý cần chạy các bước trên. Flash trong lượt phát triển là NOT RUN. |

## File sửa

- Firmware · `firmware/sniffer/main/{activity_capture.c,activity_capture.h,main.c,sniffer_wire.h,Kconfig.projbuild}`.
- Backend và lưu trữ · `backend/app/{main.py,device_activity_protocol.py,storage.py}`, `backend/app/api/{device_activity.py,device_csi_experiments.py}`, `research/{collector.py,device_activity.py,activity_records.py,csi_ingestion.py}`.
- Dashboard · `frontend/src/device-csi/{DeviceCsiPanel.tsx,device-csi.css}`.
- Kiểm thử · `tests/{test_runtime_registry.py,test_registered_device_monitor.py,dashboard_browser.mjs}`.
- Tài liệu · báo cáo này, `docs/{OUTPUT_SPECIFICATION.md,device-activity.schema.json,architecture/PROTOCOL.md,implementation/DEVICE_ACTIVITY_FIRMWARE.md,implementation/REGISTERED_DEVICE_MONITOR.md}`.
