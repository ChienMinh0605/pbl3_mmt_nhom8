# Code phía laptop

| File | Việc |
|---|---|
| `logger.py` | Thu dữ liệu từ #2, #3 và ghi nhãn bằng phím |
| `kiem_tra_buoi_thu.py` | Kiểm tra chất lượng một buổi thu |
| `train.py` | Train và đánh giá mô hình Empty/Occupied |
| `tao_dac_trung_gia.py` | Sinh file đặc trưng giả để thử `train.py` |
| `dashboard.py` | Dashboard thời gian thực (Streamlit) |
| `dac_trung.py` | Hàm tính đặc trưng cho một window – **bản tạm**, chờ `features.py` của Tiên |

# logger.py – thu dữ liệu và ghi nhãn

Đọc dữ liệu từ ESP32-C3 #2 (CSI) và #3 (Probe Request) qua USB, ghi nhãn bằng phím, lưu mỗi buổi thu vào
`data/raw/<session_id>/`. Định dạng theo `../Dac_ta_dinh_dang_du_lieu.md` (v0.1).

## Cài đặt (một lần)

Dùng môi trường ảo (venv), đặt ngoài thư mục project (project nằm trên ổ NTFS, venv ở đó dễ lỗi):

```bash
python3 -m venv ~/.venvs/pbl3          # Ubuntu báo thiếu ensurepip: sudo apt install python3-venv
~/.venvs/pbl3/bin/pip install -r requirements.txt
```

Mỗi lần mở terminal mới: `source ~/.venvs/pbl3/bin/activate`, sau đó dùng `python` như bình thường.

Windows: `py -m venv %USERPROFILE%\venvs\pbl3`, rồi `%USERPROFILE%\venvs\pbl3\Scripts\pip install -r requirements.txt`.

Linux: tài khoản phải thuộc nhóm `dialout` mới đọc được cổng USB (`groups` để kiểm tra).

## Chạy thử khi chưa có firmware

```bash
python logger.py --simulate --tag thu --duration 60
```

Dữ liệu giả đúng định dạng đặc tả: CSI 100 dòng/giây, Probe Request của vài "điện thoại" giả.

## Thu dữ liệu thật

1. Cắm #2 và #3 vào laptop, tìm tên cổng:
   ```bash
   python logger.py --list-ports
   ```
   Linux thường là `/dev/ttyACM0`, `/dev/ttyACM1`; Windows là `COM5`, `COM6`...
2. Chạy:
   ```bash
   python logger.py --rx-port /dev/ttyACM0 --snf-port /dev/ttyACM1 --tag phongA \
       --room "Phong A tang 2" --distance 3 --channel 6 --members "Chien,Tien,Phuc"
   ```
   Chỉ có một board thì bỏ cổng còn lại.
3. Bấm phím để ghi nhãn (không cần Enter):

   | Phím | Nhãn |
   |---|---|
   | `E` | Phòng trống |
   | `W` | Có người đi lại |
   | `S` | Có người ngồi / đứng yên |
   | `M` | Có 2–3 người |
   | `N` | Phòng trống, có người ở phòng bên |
   | `P` | Tạm dừng (đoạn này bị bỏ khi train) |
   | `+` hoặc `=` / `-` | Có người vào / ra |
   | `T` | Ghi chú (gõ xong bấm Enter) |
   | `Q` | Kết thúc |

   **Bấm nhãn ngay khi bắt đầu**, và bấm lại mỗi khi tình huống thay đổi.

## Dòng trạng thái

```
00:03:12 | Nhãn: WALK | Người: 2 | CSI  99.8/s | PRB  0.5/s | mất 0 | RX drop 0 | SNF kênh 7
```

- `CSI .../s`: phải gần 100. Thấp hơn nhiều là firmware #2 hoặc kết nối Wi-Fi có vấn đề.
- `mất`: số dòng bị mất (dựa trên `seq`). `RX drop`: số bản ghi mất ngay trên ESP vì queue đầy.
- `sai`: số dòng sai định dạng. Khác 0 thì chạy lại với `--verbose` để xem dòng nào sai.

## Kiểm tra buổi thu: `kiem_tra_buoi_thu.py`

Chạy ngay sau mỗi buổi thu để biết dữ liệu có dùng được không:

```bash
python kiem_tra_buoi_thu.py                  # buổi thu mới nhất
python kiem_tra_buoi_thu.py ../data/raw/20261112_1430_phongA --save   # lưu report.txt
```

Báo cáo gồm:
1. **CSI:** tốc độ thực tế (trung bình và theo từng giây), dòng mất, khoảng mất kết nối, MAC nguồn,
   độ dài CSI, số window hợp lệ.
2. **Probe Request:** số dòng theo kênh, các nguồn `mac_hash` và số phút mỗi nguồn xuất hiện.
3. **Nhãn:** các đoạn nhãn, tổng thời gian và số window dự kiến của mỗi nhãn, số người đếm tay.

Cuối báo cáo là danh sách **LỖI / CẢNH BÁO / ĐẠT**. Có **LỖI** thì buổi thu đó không nên dùng để train.

Với buổi kiểm thử tuần đầu, chỉ cần xem mục 1 và 2 (chưa cần nhãn).

## Train mô hình: `train.py`

Đầu vào là các file đặc trưng của Tiên trong `../data/features/` (định dạng mục 5 của đặc tả).

```bash
python train.py                                  # dữ liệu thật
python train.py --feature-set rssi               # chỉ RSSI, để so với CSI như bài báo 2
python train.py --final bophieu                  # chọn mô hình lưu lại (mặc định: mô hình có F1 cao nhất)
```

Chưa có dữ liệu thật thì thử bằng dữ liệu giả:

```bash
python tao_dac_trung_gia.py                      # ghi vào ../data/features_gia/
python train.py --features-dir ../data/features_gia
```

`train.py` làm gì:
1. Bỏ window `valid = 0`, lấy X = các cột `rssi_*`/`csi_*`, y = `label`.
2. **Đánh giá theo buổi thu**: mỗi lượt để riêng một buổi làm tập kiểm tra, train trên các buổi còn lại
   (`--folds 3` để gộp thành 3 lượt khi có nhiều buổi). Không chia ngẫu nhiên theo window.
3. So sánh 5 cách: baseline ngưỡng phương sai, Random Forest, Gradient Boosting, XGBoost, bỏ phiếu mềm.
4. In báo cáo: Accuracy, F1, ma trận nhầm lẫn, tỉ lệ đúng theo từng nhãn chi tiết (EMPTY, NEIGHBOR, STATIC,
   WALK, MULTI), kết quả từng buổi, 10 đặc trưng quan trọng nhất.
5. Lưu báo cáo vào `../results/<thời gian>_<bộ đặc trưng>/` và mô hình vào `../models/`
   (`model_latest.joblib` là bản mới nhất, dashboard sẽ đọc file này).

Đọc kết quả:
- **Mô hình phải thắng baseline ngưỡng**, nếu không thì học máy chưa mang lại gì.
- **Cột STATIC** cho biết khả năng nhận ra người ngồi yên, phần khó nhất của đề tài.
- **Kết quả từng buổi** chênh nhau nhiều nghĩa là mô hình chưa ổn định giữa các buổi/phòng.

## Dashboard: `dashboard.py`

Chạy **song song** với logger, mỗi chương trình một terminal (cả hai đều trong thư mục `laptop/`, đã bật venv):

```bash
python logger.py --simulate --tag demo          # terminal 1 (board thật: --rx-port ... --snf-port ...)
streamlit run dashboard.py                      # terminal 2, rồi mở http://localhost:8501
```

Giao diện theo phong cách [shadcn/ui](https://ui.shadcn.com/examples/dashboard): đen – trắng – xám làm nền, đỏ nhạt làm màu nhấn cho "có người" (biểu đồ, dải thời gian, thẻ trạng thái khi có người), font Inter.
Dashboard đọc phần mới của các file trong `data/raw/<buổi thu mới nhất>/` mỗi 2 giây:
- **4 thẻ số liệu:** Trạng thái phòng (kèm xác suất, đã ổn định bao lâu, nhãn đang ghi), Thiết bị gần đây,
  Tốc độ CSI, Sniffer (kênh đang nghe, độ trễ dữ liệu, số người đếm tay).
- **Xác suất có người:** biểu đồ vùng theo thời gian (chọn 5 / 10 / 30 phút), đường nét đứt là nhãn thật,
  bên dưới là dải "Dự đoán" và "Nhãn thật" để so sánh trực tiếp.
- **Biên độ CSI:** 30 giây gần nhất, thấy rõ tín hiệu dao động khi có người.
- **Sự kiện gần đây:** đổi trạng thái, bấm nhãn, đếm người, ghi chú, cảnh báo mất dữ liệu.

Cách tính:
- **Người:** 6 giây CSI gần nhất → đặc trưng (`dac_trung.py`) → `models/model_latest.joblib`.
- **Chống nhấp nháy** (bật/tắt ở thanh bên): trạng thái chỉ đổi khi mô hình đoán khác liên tục ≥ 6 giây.
  Tắt đi để xem kết quả thô của mô hình.
- **Thiết bị (bản tạm):** số nguồn `mac_hash` thấy trong 60 giây gần nhất. Sẽ thay bằng máy trạng thái Sherlock.

Thanh bên trái: chọn buổi thu (hoặc tự theo dõi buổi mới nhất), chống nhấp nháy, tốc độ cập nhật, mô hình đang
dùng. Tải lại trang (F5) thì lịch sử trên biểu đồ bắt đầu lại từ đầu.
File `.streamlit/config.toml` giới hạn dashboard chỉ mở trên chính laptop (`localhost`) và đặt màu sáng.

**Hai phần còn tạm:**
1. `dac_trung.py` chưa khử nhiễu wavelet. Khi Tiên xong `features.py`, dashboard phải gọi đúng hàm đó để đặc trưng
   lúc chạy giống hệt lúc train.
2. Phần thiết bị chưa dùng máy trạng thái Sherlock.

## File `logger_config.json`

Tự tạo ở lần chạy đầu, chứa `salt` để băm MAC và `exclude_macs` (MAC cần loại trừ thêm, ví dụ laptop demo).
**Cả nhóm dùng chung một file** (để cùng một MAC cho cùng `mac_hash`), gửi cho nhau riêng, **không đưa lên Git**.
MAC của các board được loại trừ tự động từ dòng `BOOT`.
