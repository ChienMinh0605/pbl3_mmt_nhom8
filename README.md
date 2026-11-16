# pbl3_mmt_nhom8

Đề tài: Sử dụng sóng WiFi để phát hiện người và thiết bị (PBL3 Mạng máy tính – Nhóm 8).

- **Người:** ESP32-C3 #1 (TX) phát, #2 (RX) thu CSI → đặc trưng → mô hình Empty/Occupied.
- **Thiết bị:** ESP32-C3 #3 (sniffer) bắt Probe Request → máy trạng thái Sherlock → đếm thiết bị.

## Cấu trúc

| Thư mục / file | Nội dung | Phụ trách |
|---|---|---|
| `Dac_ta_dinh_dang_du_lieu.md` | Đặc tả định dạng dữ liệu giữa các phần. **Đọc trước khi code.** | Cả nhóm |
| `firmware/` | Firmware ESP32-C3 #1, #2, #3 | Tiên, Phúc |
| `laptop/` | Logger, kiểm tra buổi thu, train, dashboard (xem `laptop/README.md`) | Chiến |
| `laptop/features.py` | Tiền xử lý + trích đặc trưng CSI (chưa có) | Tiên |
| `data/`, `models/`, `results/` | Dữ liệu thu, mô hình, kết quả train – **không đưa lên Git** | |

`laptop/logger_config.json` chứa `salt` băm MAC: cả nhóm dùng chung, gửi riêng cho nhau, không commit.

## Bắt đầu nhanh

```bash
cd laptop
python3 -m venv ~/.venvs/pbl3 && ~/.venvs/pbl3/bin/pip install -r requirements.txt
source ~/.venvs/pbl3/bin/activate
python logger.py --simulate --tag thu --duration 60   # thử khi chưa có board
```
