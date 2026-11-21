# Nhánh A – Phát hiện người bằng CSI (phần của Tiên)

Bám **"Đặc tả định dạng dữ liệu" v0.1** của nhóm. Một thư mục gồm firmware, code chạy thật và code mô phỏng.

**Mọi lệnh `py ...` đều chạy từ thư mục gốc `WiFiSensing_NhanhA`.**

```
WiFiSensing_NhanhA/
├─ firmware/                    nạp vào board bằng PlatformIO
│  ├─ board1_tx/                #1 SoftAP: phát Wi-Fi, echo UDP, in BOOT
│  └─ board2_rx/                #2: đo CSI, in BOOT / CSI / STAT (mục 3)
├─ python/
│  ├─ features.py               MODULE DÙNG CHUNG: đọc dữ liệu, tiền xử lý, 4 đặc trưng (mục 5)
│  ├─ logger_tam.py             logger tạm, ghi buổi thu đúng mục 4 (chờ logger.py của Chiến)
│  ├─ kiem_tra.py               kiểm tra một buổi thu (tốc độ, mất dòng, len, nhãn...)
│  ├─ ve_bieu_do.py             vẽ biên độ CSI + nhãn + phương sai của một buổi thu
│  ├─ train.py                  huấn luyện + đánh giá theo buổi thu (để tự kiểm tra)
│  ├─ live.py                   demo thời gian thực: --rx COMx (thật) hoặc --mo-phong
│  └─ mo_phong.py               tạo buổi thu GIẢ, cùng định dạng với dữ liệu thật
├─ data/                        dữ liệu THẬT (tự tạo khi chạy logger)
│  ├─ raw/<session_id>/         csi.csv, stat.csv, boot.csv, probe.csv, labels.csv, meta.json
│  └─ features/                 <session_id>.csv + feature_meta.json  → GIAO CHO CHIẾN
├─ data_mo_phong/               dữ liệu GIẢ (cùng cấu trúc với data/) – không dùng cho báo cáo
├─ models/                      mô hình .joblib
└─ config_local.json            salt băm MAC + MAC loại trừ (tự tạo, KHÔNG đưa lên Git)
```

Cài thư viện (một lần): `py -m pip install numpy pandas PyWavelets scikit-learn xgboost joblib pyserial matplotlib`

---

## A. Chạy MÔ PHỎNG (không cần board)

```
py python/mo_phong.py
py python/features.py --raw data_mo_phong/raw --out data_mo_phong/features
py python/kiem_tra.py data_mo_phong/raw/20261109_0900_mophong1
py python/ve_bieu_do.py data_mo_phong/raw/20261109_0900_mophong1
py python/train.py --features data_mo_phong/features --out models/model_mo_phong.joblib
py python/live.py --mo-phong --model models/model_mo_phong.joblib
```
Trong cửa sổ `live`, bấm **E / W / S / M / N** để đổi tình huống. Nhớ tắt bộ gõ tiếng Việt.

Mô phỏng có đủ 5 tình huống. STATIC (ngồi yên) và NEIGHBOR (người ở phòng bên) được cố ý làm khó phân biệt, nên accuracy không đạt 100%. **Số liệu mô phỏng chỉ dùng để thử phần mềm, không đưa vào báo cáo.**

## B. Chạy THẬT

**1. Nạp firmware** (PlatformIO → Open Project):
- `firmware/board1_tx` → nạp vào board #1. Sửa `AP_CHANNEL` thành kênh ít AP nhất trước khi nạp.
- `firmware/board2_rx` → nạp vào board #2. `PRINT_CSI 1` là chạy thật. Đặt `PRINT_CSI 0` thì chỉ in BOOT và STAT, dùng khi muốn xem tốc độ bằng Serial Monitor.
- **Đóng Serial Monitor** trước khi chạy logger.

**2. Thu một buổi** (ví dụ board #2 ở COM9):
```
py python/logger_tam.py --rx COM9 --ten phongA --phong "Phòng A tầng 2" --khoang-cach 3
```
Bấm phím trong cửa sổ Terminal để ghi nhãn:
- **E** = EMPTY, **W** = WALK, **S** = STATIC, **M** = MULTI, **N** = NEIGHBOR, **P** = PAUSE
- **+ / −** = có người vào / ra
- **T** = ghi chú, **Q** = kết thúc

Logger bắt đầu ở trạng thái PAUSE.

**3. Kiểm tra, vẽ biểu đồ, xuất đặc trưng:**
```
py python/kiem_tra.py data/raw/<session_id>
py python/ve_bieu_do.py data/raw/<session_id>
py python/features.py                      # mọi buổi trong data/raw → data/features
```

**4. Tự kiểm tra mô hình và demo:**
```
py python/train.py
py python/live.py --rx COM9 --model models/model_a.joblib
```

---

## Đối chiếu với đặc tả v0.1

| Mục | Đã làm |
|---|---|
| 3.1 BOOT | #1 và #2 in khi khởi động và mỗi 30 s; #2 in thêm ngay sau khi kết nối (có `mac_ap`) |
| 3.2 CSI | Đủ 12 trường, `csi_hex` liền nhau, MAC chữ thường, lọc theo BSSID đọc sau khi kết nối |
| 3.4 STAT | Mỗi giây: `n_rx`, `n_filtered`, `n_queue_drop`, `channel` |
| 4.1–4.5 | `logger_tam.py` ghi đủ 6 file; băm MAC bằng SHA-256(salt + MAC), lấy 12 ký tự; `local_admin`; `excluded` (tự thêm MAC từ dòng BOOT và MAC trong `config_local.json`) |
| 4.4 Nhãn | Đúng bộ phím; quy đổi nhị phân WALK/STATIC/MULTI → 1, EMPTY/NEIGHBOR → 0, PAUSE bỏ |
| 5 Đặc trưng | Mỗi buổi một file; có `session_id, win_start, win_end, n_samples, valid, label_detail, label`, `rssi_*`, `csi_<var/mad/range/iqr>_<kk>` với `kk` là chỉ số gốc 0–63 viết 2 chữ số; giữ window `valid = 0`; bỏ PAUSE; có `feature_meta.json`; code nằm trong module `features.py` |

## Các điểm cần báo Chiến để sửa đặc tả (v0.2)

1. **Ping → UDP echo.** #2 gửi UDP khoảng 100 gói/giây, #1 gửi trả lại. Đã đo trên board thật: khoảng 95 gói/giây.
2. **Cổng truyền.** Board của nhóm dùng chip USB-UART ở 921600, không dùng USB Serial/JTAG (mục 2). 33 KB/giây vẫn đủ.
3. **`denoise.level`.** Mức 9 không làm được với window 6 s (khoảng 600 mẫu, db4 tách tối đa 6 mức). Code đang dùng mức 4.
4. **MAD.** Code đang dùng *median* absolute deviation. Cần chốt theo bài báo 2 (sửa `MAD_KIND` trong `features.py`).
5. **Cách chia window.** Window xếp từ đầu mỗi đoạn nhãn STATE, nên không window nào cắt ngang chỗ đổi nhãn. Phần dư cuối đoạn (dưới 6 s) bị bỏ, đúng quy tắc mục 5.
6. **Đặc trưng RSSI** tính trên RSSI thô, không khử nhiễu.
7. **Danh sách sóng mang con giữ lại** đang là 2–26 và 38–63 (51 sóng mang con). Chốt lại sau khi chạy `kiem_tra.py` trên dữ liệu C3 thật.
