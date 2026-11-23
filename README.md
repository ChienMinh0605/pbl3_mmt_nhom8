# pbl3_mmt_nhom8

Đề tài: Sử dụng sóng WiFi để phát hiện người và thiết bị (PBL3 Mạng máy tính – Nhóm 8).

**Bài toán:** giám sát an toàn cho người ở nhà một mình, không camera, không thiết bị đeo. Có 1 người: nhận dạng
động tác, **phát hiện té ngã**, **đo nhịp thở** khi yên. Có 2–3 người: đếm số người. Chi tiết:
[`KE_HOACH_NHANH_NGUOI.md`](KE_HOACH_NHANH_NGUOI.md).

- **Người:** 1 ESP32-C3 (TX) phát ESP-NOW broadcast, 2 ESP32-S3 (RX1, RX2) thu CSI, cắm USB vào laptop → có người
  → đếm người → động tác / ngã / nhịp thở.
- **Thiết bị:** ESP32-C3 sniffer bắt Probe Request → máy trạng thái Sherlock. Hướng ghép với nhánh người đang bàn:
  [`DE_XUAT_NHANH_THIET_BI.md`](DE_XUAT_NHANH_THIET_BI.md).

## Cấu trúc

| Thư mục / file | Nội dung | Phụ trách |
|---|---|---|
| `Dac_ta_dinh_dang_du_lieu.md` | Đặc tả định dạng dữ liệu giữa các phần (v0.3). **Đọc trước khi code.** | Cả nhóm |
| `KE_HOACH_NHANH_NGUOI.md` | Bài toán, phần cứng, kiến trúc, nhãn, dữ liệu, đánh giá, lộ trình của nhánh người | Chiến |
| `DE_XUAT_NHANH_THIET_BI.md` | Đề xuất nhánh thiết bị và cách ghép với nhánh người – **chưa chốt** | Chiến, Phúc |
| `firmware/` | Firmware TX, RX, sniffer | Tiên, Phúc |
| `laptop/` | Logger, kiểm tra buổi thu, train, dashboard, mô phỏng (xem `laptop/README.md`) | Chiến |
| `tai_lieu/`, `luu_tru/` | Bài báo tham khảo, tài liệu theo hướng cũ – chỉ để trên máy, **không đưa lên Git** | |
| `data/`, `models/`, `results/` | Dữ liệu thu, dữ liệu công khai (`data/public/`), mô hình, kết quả train – **không đưa lên Git** | |

`laptop/logger_config.json` chứa `salt` băm MAC: cả nhóm dùng chung, gửi riêng cho nhau, không commit.

Code trong `laptop/` đã theo đặc tả **v0.3** (logger nhiều RX, kiểm tra buổi thu, `features.py`, train, dashboard).

## Bắt đầu nhanh

```bash
cd laptop
python3 -m venv ~/.venvs/pbl3 && ~/.venvs/pbl3/bin/pip install -r requirements.txt
source ~/.venvs/pbl3/bin/activate
python logger.py --simulate --tag thu --duration 60   # thử khi chưa có board
```
