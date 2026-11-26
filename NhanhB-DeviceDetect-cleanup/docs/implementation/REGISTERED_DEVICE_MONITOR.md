# Registered Device Activity Monitor

Giai đoạn 3 đọc JSONL v2 của sniffer `DEVICE_ACTIVITY_FIXED_CHANNEL` qua collector hiện có. FastAPI cung cấp registry, trạng thái theo thiết bị và điều khiển capture/replay tại `/api/device-csi`. Probe v1 tiếp tục đi qua `/api/probe` và Dashboard hiện tại. Một tiến trình chỉ mở một nguồn serial tại một thời điểm. [Firmware activity](DEVICE_ACTIVITY_FIRMWARE.md) · [Schema UART v2](../device-activity.schema.json)

## Cách đọc thống kê

Monitor dùng cửa sổ trượt **10 giây**, kết thúc tại heartbeat v2 mới nhất. Timestamp lấy từ đồng hồ của board trong cùng một `boot_id`. Một bản tổng hợp chỉ góp vào thống kê khi cả khoảng đo nằm trong cửa sổ. Capture cần tối thiểu **8 giây** độ phủ hợp lệ và 10 giây kể từ heartbeat đầu tiên. `frames_per_s` và `bytes_per_s` chia số đếm cho số giây phủ thực tế. `frame_types` gồm số frame `management`, `control`, `data`. `last_seen_us` là thời điểm *kết thúc khoảng firmware có frame gần nhất đã thấy* theo đồng hồ board. `rssi_max_dbm` là RSSI cao nhất của các frame nằm trong cửa sổ, có thể là tín hiệu AP với traffic downlink.

| Trạng thái | Ý nghĩa |
|---|---|
| `OBSERVED_ACTIVE` | Cửa sổ đủ độ phủ và có ít nhất một frame khớp thiết bị. |
| `NO_OBSERVED_ACTIVITY` | Cửa sổ đủ độ phủ và không thấy frame khớp. Thiết bị có thể vẫn ở nhà. |
| `UNKNOWN` | Đang khởi đầu, ngắt nguồn, sai kênh, heartbeat quá hạn, chưa xác nhận MAC có trong cấu hình firmware hoặc chất lượng không đủ. Thống kê cửa sổ khi đó là `null`, thay vì số 0. Xem `reasons` trong API. |

Firmware báo số MAC được cấu hình. Monitor cần một bản tổng hợp lành mạnh khớp MAC và kênh trước khi đánh giá im lặng cho thiết bị đó. Khởi động lại board, nối lại USB hoặc bắt đầu ghi phiên sẽ yêu cầu xác nhận lại. Nếu frame của thiết bị nằm trong một khoảng tổng hợp cắt biên cửa sổ, monitor giữ `UNKNOWN` khi chưa thấy frame nào nằm trọn trong cửa sổ.

Chất lượng bị đánh dấu thiếu khi có gap sequence, dòng JSONL sai, timestamp không khớp heartbeat, lỗi UART hoặc frame ngoài kênh. Khoảng heartbeat trên 2,5 s, hơn 10% callback lỗi nhận hoặc hơn 50% callback không gán được địa chỉ cũng làm cửa sổ chứa khoảng đó thành `UNKNOWN`. Đây là ngưỡng chất lượng ban đầu của phần mềm. Hoạt động mạng có thể đến từ tác vụ nền, nên trạng thái này chỉ mô tả traffic quan sát được. Nó không xác định ai đang dùng điện thoại hay đang tỉnh.

## API cục bộ

Chạy `./run.sh` ở gốc repo và dùng cổng được in ra. OpenAPI tương tác có tại `/docs`. Các đường dẫn dưới đây có tiền tố `/api/device-csi`.

| Method và đường dẫn | Sử dụng |
|---|---|
| `GET /registry` | Danh sách `{id, name, channel, consent_at}`. Thêm `details=true` trong giao diện cấu hình để lấy MAC đã đăng ký và trạng thái firmware. |
| `POST /registry` | Nhận `{name, mac, channel, consent: true}`. Firmware runtime đang kết nối được tự đồng bộ. Khi offline, đáp ứng 202 xác nhận đã lưu cấu hình mong muốn. Trùng MAC trên cùng kênh trả 409. |
| `PATCH /registry/{device_id}` | Nhận `{name}` để sửa nhãn hoặc payload đầy đủ như POST để sửa MAC/kênh với xác nhận đồng ý. |
| `DELETE /registry/{device_id}` | Xóa thiết bị khỏi danh sách mong muốn và đồng bộ đã áp dụng qua ACK nếu firmware hỗ trợ. |
| `PUT /registry/channel`, `POST /registry/sync` | Cấu hình kênh thu và yêu cầu đồng bộ lại. |
| `POST /connect`, `POST /disconnect` | Mở cổng SNF với `{port}`. Collector xác định profile từ heartbeat và dùng 460800 baud cho Activity. Ngắt nguồn USB hoặc replay Activity. |
| `GET /state` | Kết nối, kênh, `boot_id`, biên cửa sổ, trạng thái và thống kê các thiết bị. |
| `POST /captures/start`, `POST /captures/stop`, `GET /captures` | Bắt đầu/kết thúc ghi và liệt kê phiên. Bắt đầu ghi khởi tạo cửa sổ mới để live và replay dùng cùng dữ liệu đầu vào. |
| `POST /replay` | Nhận `{capture_id, speed}` cho phiên đã kết thúc. Trạng thái `finished` hiển thị cửa sổ cuối của bản ghi với nhãn nguồn `replay`. |

SQLite lưu MAC đã có đồng ý để cấu hình UART và HMAC-SHA256 để đối chiếu MAC/kênh. SQLite và khóa `.device-activity.key` dùng quyền tệp riêng tư `0600`. Giữ khóa cùng SQLite khi chuyển hoặc khôi phục runtime. Registry cũ chỉ có HMAC nên cần nhập lại MAC trên Dashboard để gửi xuống firmware. MAC hiển thị trong API cấu hình `details=true`; state, timeline, CSV và lỗi xác thực chỉ trả thông tin cần thiết. Capture `raw.jsonl` giữ telemetry đã đổi MAC thành ID, cùng các sự kiện `registry_pending`, `registry_applied` với snapshot công khai và revision. Capture không lưu payload Wi‑Fi, MAC thô hoặc dòng lỗi thô. [Giao thức runtime và kiểm nghiệm](RUNTIME_DEVICE_REGISTRY.md)

## Thử với Vivo Y20

1. Kết nối Vivo Y20 vào SSID thử nghiệm **2,4 GHz** có kênh cố định. Y20 hỗ trợ cả 2,4 GHz và 5 GHz, nên kiểm tra băng tần trong danh sách client của router. Xem MAC thực tế của máy trong chi tiết SSID trên điện thoại hoặc đối chiếu client đang kết nối trên router. Tên mục có thể khác theo bản Funtouch OS. Dùng MAC mà router thấy trên SSID này để đăng ký trên Dashboard. [Thông số Vivo Y20](https://www.vivo.com/vn/products/param/y20) · [Hướng dẫn firmware và xác minh cổng trước khi flash](DEVICE_ACTIVITY_FIRMWARE.md)
2. Sau khi có đồng ý của chủ thiết bị, đăng ký khi USB đang ngắt. Ví dụ dưới đây minh họa router kênh 6. Thay số kênh theo cấu hình thực tế. Prompt nhập kín giúp tránh ghi nguyên MAC vào lịch sử shell.

   ```bash
   api=http://127.0.0.1:8000/api/device-csi
   read -r -s -p 'MAC của Vivo Y20 trên SSID thử nghiệm: ' demo_mac
   printf '\n'
   printf '%s\n' "$demo_mac" | .venv/bin/python -c \
     'import json,sys; print(json.dumps(dict(name="Vivo Y20", mac=sys.stdin.readline().strip(), channel=int(sys.argv[1]), consent=True)))' 6 \
     | curl -fsS -H 'Content-Type: application/json' --data-binary @- "$api/registry"
   unset demo_mac
   ```

3. Đóng terminal monitor hoặc dashboard đang giữ cổng. Dùng cổng đã xác nhận trong `/api/ports` để gọi `/connect`. Sau đó gọi `/captures/start` nếu muốn lưu phiên.

   ```bash
   # Thay cổng bằng đường dẫn USB–UART đã xác nhận.
   curl -fsS -H 'Content-Type: application/json' -d '{"port":"/dev/ttyUSB0"}' "$api/connect"
   curl -fsS "$api/state"
   # Chờ /state báo connection là connected trước khi ghi.
   curl -fsS -X POST "$api/captures/start"
   ```

4. Tạo traffic hợp lệ trên Wi‑Fi bằng cách tải một tệp thử, rồi xem `/state` sau khi đủ 10 s. Ghi lại thời gian thao tác và thời gian khóa màn hình trong ghi chú buổi đo. `OBSERVED_ACTIVE` có thể vẫn xuất hiện sau khi khóa màn hình vì hệ điều hành có traffic nền. Nếu thiết bị luôn `UNKNOWN`, kiểm tra `reasons`, MAC thực tế của SSID, kênh router và firmware activity.
5. Gọi `POST /captures/stop` để lấy `id`, rồi phát lại qua `POST /replay` với `{capture_id, speed}`. So cửa sổ cuối của replay với lúc kết thúc phiên. Trong lượt thu riêng, rút USB và kiểm tra API chuyển về `UNKNOWN`. Khi cần đổi MAC hoặc SSID, cập nhật firmware và đăng ký binding phù hợp.

## Kiểm thử phần mềm

```bash
.venv/bin/python -m pytest -q tests/test_device_activity_protocol.py tests/test_registered_device_monitor.py
.venv/bin/python -m pytest -q
```

Test tích hợp phát lại fixture JSONL v2 của Giai đoạn 2 qua cổng UART ảo và collector thật, sau đó phát lại file capture đã loại MAC qua API. Những khoảng im lặng và lỗi được bổ sung để kiểm thử điều kiện biên. Fixture là dữ liệu kiểm thử tổng hợp. Chưa có số liệu RF hay phép đo thực tế với Vivo Y20 ở giai đoạn này.
