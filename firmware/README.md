# Firmware ESP32

Mỗi board một thư mục, dòng in ra Serial theo đúng mục 3 của `../Dac_ta_dinh_dang_du_lieu.md` (v0.3).
TX và RX sửa từ ví dụ `csi_send` / `csi_recv` của repo Espressif **esp-csi**.

| Thư mục | Board | Việc | In ra |
|---|---|---|---|
| `tx/` | ESP32-C3 (TX) | Phát ESP-NOW broadcast ~100 gói/s trên một kênh cố định | `BOOT` |
| `rx/` | ESP32-S3 (RX1, RX2 – cùng firmware, tên board đặt trong menuconfig) | Thu CSI của gói từ TX, lọc theo MAC của TX | `BOOT`, `CSI`, `STAT` |
| `sniffer/` | ESP32-C3 (SNF) | Bắt Probe Request, quét kênh 1→13 | `BOOT`, `PRB`, `STAT` |

Làm theo bậc: 1 TX + 1 RX chạy thông trước, rồi mới nạp cho RX2.

Không commit thư mục build (`build/`, `.pio/`); đã có trong `.gitignore`.
