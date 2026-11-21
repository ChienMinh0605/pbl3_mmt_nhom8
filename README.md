# pbl3_mmt_nhom8

Đề tài: Sử dụng sóng WiFi để phát hiện người và thiết bị (PBL3 Mạng máy tính – Nhóm 8).

**Bài toán:** giám sát an toàn cho người ở nhà một mình, không camera, không thiết bị đeo – phát hiện có người và
trạng thái hoạt động, **té ngã**, (mở rộng) **nhịp thở bất thường**; vẫn chạy khi có khách. Chi tiết:
[`KE_HOACH_NHANH_NGUOI.md`](KE_HOACH_NHANH_NGUOI.md).

- **Người:** ESP32-C3 #1 (TX) phát, #2 (RX) thu CSI → đặc trưng → trống / hoạt động / yên → phát hiện ngã.
- **Thiết bị:** ESP32-C3 #3 (sniffer) bắt Probe Request → máy trạng thái Sherlock → số thiết bị → biết có khách
  để điều chỉnh mức cảnh báo.

## Cấu trúc

| Thư mục / file | Nội dung | Phụ trách |
|---|---|---|
| `Dac_ta_dinh_dang_du_lieu.md` | Đặc tả định dạng dữ liệu giữa các phần. **Đọc trước khi code.** | Cả nhóm |
| `KE_HOACH_NHANH_NGUOI.md` | Bài toán, nhãn, kiến trúc, đánh giá, lộ trình của nhánh người | Chiến, Tiên |
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
