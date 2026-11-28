# Firmware ESP32

Mỗi board một thư mục, dòng in ra Serial theo đúng mục 3 của `../Dac_ta_dinh_dang_du_lieu.md` (v0.3).
TX và RX sửa từ ví dụ `csi_send` / `csi_recv` của repo Espressif **esp-csi**.

| Thư mục | Board | Việc | In ra |
|---|---|---|---|
| `tx/` | ESP32-C3 (TX) | Phát ESP-NOW broadcast ~100 gói/s trên một kênh cố định | `BOOT` |
| `rx/` | ESP32-S3 (RX1, RX2 – cùng firmware, tên board đặt trong menuconfig) | Thu CSI của gói từ TX, lọc theo MAC của TX | `BOOT`, `CSI`, `STAT` |
| `sniffer/` | ESP32-C3 (SNF) | Bắt Probe Request, quét kênh 1→13 | `BOOT`, `PRB`, `STAT` |
| `thu_mo_hinh/` | ESP32-S3 | Thử chạy mô hình động tác ngay trên board (cách B): tốc độ, bộ nhớ, khớp với Python | Kết quả đo |

Làm theo bậc: 1 TX + 1 RX chạy thông trước, rồi mới nạp cho RX2.

Không commit thư mục build (`build/`, `.pio/`); đã có trong `.gitignore`.

## Nạp TX và RX

```bash
. ~/.espressif/tools/activate_idf_v6.1.sh
cd firmware/tx && idf.py menuconfig    # PBL3 CSI: kênh, MAC phát, số gói/s (mặc định 6, 1a:00:00:00:00:00, 100)
idf.py -p /dev/ttyUSB0 flash           # C3 qua cổng CH340 hay cổng USB gốc đều được (console UART0 + USB-JTAG phụ)
cd ../rx && idf.py menuconfig          # PBL3 CSI: tên board (RX1/RX2), kênh, MAC của TX – phải giống TX
idf.py -p /dev/ttyACM0 flash           # S3: phải cắm cổng USB gốc (USB Serial/JTAG), dòng CSI không đi qua CH340
```

Đổi `sdkconfig.defaults` thì xoá `sdkconfig` rồi build lại. Mỗi RX một tên: nạp RX2 thì đổi tên trong menuconfig.

Kiểm tra: `python laptop/logger.py --rx-port /dev/ttyACM0 --tag thu --duration 20`, rồi `kiem_tra_buoi_thu.py`.

**Đo 26/11/2026** (1 TX C3 + 1 RX S3 cắm cùng laptop, kênh 6): RX nhận 99–100 dòng `CSI`/s, `n_queue_drop` 0,
logger không mất dòng; `len` 128, `sig_mode` 1, `cwb` 0, RSSI khoảng −44 dBm. Ban đầu `n_filtered`
luôn 0 kể cả trên kênh có router: thiếu `esp_wifi_set_promiscuous_filter(MASK_ALL)` thì CSI không báo khung data của
máy khác. Sửa xong: kênh 4 (router nhà) 6–24 khung/s, kênh 6 2–22 khung/s, `n_rx` vẫn ~99.
Chưa thử: RX2 cùng lúc (`rx_seq` hai RX có khớp không), chạy lâu, khoảng cách xa.
