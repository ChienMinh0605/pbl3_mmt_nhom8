# Firmware quan sát hoạt động Wi‑Fi ESP32-C3

`DEVICE_ACTIVITY_FIXED_CHANNEL` dùng ESP32-C3 làm sniffer thụ động trên kênh chính 2,4 GHz của router. Mode này xuất JSONL v2 qua UART0 ở 460800 8N1. `PROBE_BASELINE` vẫn là mode mặc định, hỗ trợ cấu hình hopping hoặc fixed và xuất JSONL v1 cho Dashboard hiện tại. Giai đoạn này cung cấp firmware và công cụ kiểm tra UART v2. [Schema v2](../device-activity.schema.json) · [Kế hoạch MVP](../legacy/DEVICE_CSI_MVP_PLAN.md)

## Cấu hình và build

Chọn kênh chính cố định của router thử nghiệm và lấy MAC mà điện thoại đã đăng ký đang dùng trên đúng mạng Wi‑Fi đó. Dùng cấu hình UART0 GPIO21/GPIO20 dành cho board nối qua CH340 hoặc bộ chuyển USB–UART tương thích.

```bash
# Từ gốc repo, dùng ESP-IDF 5.5.4 đã cài
bash scripts/sniffer.sh build activity
```

Profile `activity` bật `DEVICE_ACTIVITY_FIXED_CHANNEL`. Kconfig dùng làm dự phòng khi chưa có cấu hình NVS hợp lệ. Có thể dùng `bash scripts/sniffer.sh menuconfig activity` để đổi mã quốc gia hoặc mặc định trước lần nạp đầu. Sau khi nạp firmware runtime, thêm/sửa/xóa thiết bị và đổi kênh từ Dashboard. Firmware giữ một kênh cho tới khi nhận thao tác cấu hình hợp lệ. [Hướng dẫn đồng bộ runtime](RUNTIME_DEVICE_REGISTRY.md)

Binary ứng dụng nằm tại `firmware/sniffer/build/activity/wifi_device_sniffer.bin`. Để build baseline trong một thư mục riêng khi cần, dùng các lệnh sau từ `firmware/sniffer`. Thêm `sdkconfig.fixed` vào cuối `SDKCONFIG_DEFAULTS` khi cần baseline fixed.

```bash
idf.py -B build/baseline -D SDKCONFIG=sdkconfig.baseline.local \
  -D SDKCONFIG_DEFAULTS=sdkconfig.defaults build
```

## Ánh xạ địa chỉ

Callback xác thực frame control và độ dài header, rồi khớp **TA** (địa chỉ phát) và **RA** (địa chỉ nhận) với danh sách đã đăng ký. **SA/DA** là địa chỉ nguồn/đích logic. Với traffic đi qua AP, endpoint logic ở phía sau AP có thể khác endpoint radio. `source_mac` trong schema biểu thị **MAC đăng ký được thống kê**, có thể ở vai trò phát hoặc nhận.

| Kiểu frame | Địa chỉ được đọc |
|---|---|
| Management, ToDS/FromDS `0/0` | `Addr1` là RA/DA, `Addr2` là TA/SA, `Addr3` thường là BSSID. |
| Data, ToDS/FromDS `0/0` | `Addr1` RA/DA, `Addr2` TA/SA. |
| Data, ToDS/FromDS `1/0` | `Addr1` RA/BSSID, `Addr2` TA/SA, `Addr3` DA. |
| Data, ToDS/FromDS `0/1` | `Addr1` RA/DA, `Addr2` TA/BSSID, `Addr3` SA. |
| Data, ToDS/FromDS `1/1` | `Addr1` RA, `Addr2` TA, `Addr3` DA, `Addr4` SA. Parser kiểm tra độ dài có Addr4 và phần QoS/HT Control nếu có. |
| ACK, CTS | Chỉ có RA (`Addr1`). Có thể đếm RX cho MAC đăng ký khớp RA. TA không xuất hiện trong header. |
| RTS, PS-Poll, Block Ack Request, Block Ack | RA hoặc BSSID nhận ở `Addr1`, TA ở `Addr2`. `block_ack_frames` chỉ đếm subtype Block Ack. |
| CF-End, CF-End + CF-Ack | RA ở `Addr1`, BSSID của AP phát ở `Addr2`. |
| `WIFI_PKT_MISC`, control layout chưa hỗ trợ, header thiếu địa chỉ có thể dùng | `attribution: "unattributed"` và `source_mac: null`. |

Firmware chỉ đọc các byte cần cho header và metadata. Callback cộng bộ đếm trong RAM, task xuất gửi thống kê qua UART. Một frame tính một lần cho mỗi thiết bị khớp. Khi hai MAC đăng ký cùng xuất hiện trên một frame, mỗi thiết bị nhận một lượt. Địa chỉ chưa đăng ký chỉ đóng góp vào bộ đếm tổng. Firmware giữ nguyên frame mã hóa trên không và không xuất payload, SSID hay nội dung ứng dụng. [ESP-IDF 5.5.4, Wi-Fi Sniffer Mode](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-guides/wifi.html#wi-fi-sniffer-mode) · [Wireshark, định nghĩa subtype](https://www.wireshark.org/docs/wsar_html/packet-ieee80211_8h_source.html)

## JSONL v2

Mỗi dòng có `v: 2`, `node: "sniffer"`, `type`, `boot_id`, `seq` và `ts_us` tính bằng µs từ boot. `seq` tăng theo thứ tự xuất UART và quay vòng uint32. Collector chung chọn parser v2 hoặc Probe v1 dựa trên heartbeat. [Parser v2](../../backend/app/device_activity_protocol.py) · [Các dòng mẫu](../../tests/fixtures/device_activity_v2.jsonl)

| `type` | Dữ liệu và ngữ nghĩa |
|---|---|
| `channel` | Thông báo khi bắt đầu thu, có `mode`, `scan_mode: "fixed"` và `channel`. |
| `status` | Heartbeat lúc bắt đầu và cuối mỗi khoảng gần 1 s. Có kênh, `capture_active`, số MAC đăng ký, số callback, lỗi nhận, callback ngoài kênh, frame không có địa chỉ dùng được, frame không khớp đăng ký và lỗi UART. Bản build mới thêm phiên bản firmware và bộ đếm Management, Data, Control trên kênh. Counter tích lũy theo boot, wrap uint32. |
| `activity_sample` | Một dòng cho mỗi cặp MAC đăng ký/`frame_kind` có dữ liệu, hoặc một dòng tổng `unattributed` cho mỗi loại frame có dữ liệu. `ts_us` là đầu khoảng, `duration_us` là độ dài thực tế. Trường gồm `source_mac`, `attribution`, `frame_kind`, `channel`, `n_frames`, `n_bytes`, `tx_frames`, `rx_frames`, `block_ack_frames`, `rssi_max_dbm`. |

`n_bytes` cộng `rx_ctrl.sig_len`, gồm FCS theo SDK ESP32-C3. `tx_frames` và `rx_frames` có thể cùng tăng nếu cùng MAC đăng ký xuất hiện ở cả hai vai trò. Với mẫu `unattributed`, cả hai bằng 0. RSSI là RSSI của tín hiệu mà sniffer thu được, nên với frame downlink nó mô tả tín hiệu từ AP. Khoảng trống có heartbeat vẫn có thể có 0 mẫu hoạt động. Khi mất heartbeat, cần xem là khoảng thiếu dữ liệu.

```bash
# Từ gốc repo
.venv/bin/python -m backend.app.device_activity_protocol tests/fixtures/device_activity_v2.jsonl
.venv/bin/python -m pytest -q tests/test_device_activity_protocol.py
```

## Thử trên router và điện thoại

1. Dùng router thử nghiệm cố định kênh 2,4 GHz, ưu tiên 20 MHz. Kết nối điện thoại, kiểm tra MAC riêng của mạng trong phần chi tiết Wi‑Fi và đăng ký trên Dashboard sau khi kết nối sniffer. Chỉ thử với thiết bị đã đồng ý tham gia.
2. Kiểm tra cổng trước và sau khi cắm SNF bằng `.venv/bin/python -m serial.tools.list_ports -v`. Xác nhận cổng USB–UART, board ESP32-C3 và cấu hình build activity. Bản build chỉ ghi file trên máy. Khi đã xác nhận cổng, dùng lệnh sau từ `firmware/sniffer`, thay `PORT` bằng cổng đúng.

   ```bash
   idf.py -B build/activity -D SDKCONFIG=sdkconfig.activity.local \
     -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.activity' \
     -p PORT -b 460800 flash
   ```

3. Đóng dashboard và tiến trình đang giữ cổng, rồi chạy `.venv/bin/python -m serial.tools.miniterm PORT 460800 --raw` từ gốc repo. Reset SNF nếu cần thấy bản ghi `channel` đầu tiên. Kiểm tra `status.channel`, `registered_devices`, `boot_id` và `seq`. Để điện thoại khóa màn hình, sau đó truyền dữ liệu theo chiều lên và xuống. So `n_frames`, `tx_frames`, `rx_frames`, `block_ack_frames` giữa các lượt và ghi nhận lưu lượng nền.
4. Lưu riêng các dòng JSONL từ UART rồi chạy validator với đường dẫn file đó. Kiểm tra `source_mac` chỉ chứa MAC đã đăng ký hoặc `null`, `frame_kind` phù hợp và `serial_errors` ổn định. Nếu không thấy Block Ack, ghi lại trạng thái thiết bị/AP và số frame control bắt được để đối chiếu.

## Giới hạn ESP32-C3 và trạng thái kiểm chứng

- Mode này quan sát một kênh chính 2,4 GHz tại một thời điểm. Traffic 5 GHz, traffic ngoài kênh và frame mà radio/driver không cung cấp nằm ngoài phép đo. Hỗ trợ promiscuous phụ thuộc PHY, chất lượng thu và bản ESP-IDF. [ESP32-C3 Wi-Fi Driver](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-guides/wifi.html#wi-fi-sniffer-mode)
- SDK mô tả một số callback, ví dụ MIMO, chỉ có metadata độ dài. Frame ACK/CTS chỉ có RA. Tần suất nhìn thấy Block Ack trong mạng demo cần đo trên phần cứng. [ESP32-C3 Wi-Fi Driver](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-guides/wifi.html#wi-fi-sniffer-mode)
- Counter đo callback hoặc frame do driver cung cấp. Retry có thể được tính thêm. Frame tổng hợp và lỗi thu ảnh hưởng phép so sánh với bộ đếm của router. Hoạt động nền và thay đổi MAC riêng của mạng ảnh hưởng kết quả quan sát từng thiết bị.
- Build ESP-IDF, native test phân tích header và test validator kiểm tra mã và hợp đồng dữ liệu. Không phát hiện ESP32 trên cổng USB–UART trong lần kiểm tra này, vì vậy chưa nạp board và chưa có capture RF thật.
