# Firmware ESP32-C3

Mỗi board một thư mục, dòng in ra Serial theo đúng mục 3 của `../Dac_ta_dinh_dang_du_lieu.md`.

| Thư mục | Board | In ra | Phụ trách |
|---|---|---|---|
| `esp32_1_tx/` | #1 TX / SoftAP | `BOOT` | Tiên |
| `esp32_2_rx/` | #2 RX thu CSI | `BOOT`, `CSI`, `STAT` | Tiên |
| `esp32_3_sniffer/` | #3 sniffer Probe Request | `BOOT`, `PRB`, `STAT` | Phúc |

Không commit thư mục build (`build/`, `.pio/`); đã có trong `.gitignore`.
