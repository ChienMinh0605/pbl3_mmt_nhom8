# Code phía laptop

| File | Việc |
|---|---|
| `logger.py` | Thu dữ liệu từ các RX và sniffer, ghi nhãn bằng phím (đặc tả v0.3) |
| `kiem_tra_buoi_thu.py` | Kiểm tra chất lượng một buổi thu: từng RX, độ khớp `rx_seq`, nhãn, động tác |
| `features.py` | Tiền xử lý + đặc trưng: window 6 s (mục 5) và window động tác 3 s (mục 5.2) |
| `train.py` | Train và đánh giá: có người, mức hoạt động, số người, động tác; so 1 RX với 2 RX |
| `dashboard.py` | Dashboard thời gian thực (Streamlit), đọc nhiều RX |
| `nhan.py` | Bộ nhãn dùng chung (trạng thái, động tác, phím, quy đổi) |
| `mo_phong_ui.py`, `mo_phong_ui.html` | **Giao diện mô phỏng 3D** trên trình duyệt: chọn kịch bản, chạy, xem, lưu |
| `mo_phong.py` | **Mô phỏng 3D theo hướng mới** (1 TX + 2 RX ở góc phòng, đặc tả v0.3) |
| `test_mo_phong.py` | Tự kiểm tra mô phỏng (cả giao diện) |
| `nhip_tho.py` | **Thuật toán nhịp thở** (tầng 2b): PCA trên 2 RX, có độ tin cậy, kiểm tra cử động |
| `doi_chieu_wifall.py` | Đối chiếu mô phỏng với CSI thật của WiFall (ESP32-S3) |

# logger.py – thu dữ liệu và ghi nhãn

Đọc dữ liệu từ các RX (CSI) và sniffer (Probe Request) qua USB, ghi nhãn bằng phím, lưu mỗi buổi thu vào
`data/raw/<session_id>/`. Định dạng theo `../Dac_ta_dinh_dang_du_lieu.md` **v0.3**: mọi RX ghi chung `csi.csv` với
cột `board` (RX1, RX2 lấy từ dòng `BOOT`), dòng `CSI` có `rx_seq` để ghép các RX theo gói.

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

Dữ liệu giả đúng định dạng v0.3: 2 RX nhận cùng gói (cùng `rx_seq`), 100 dòng/giây mỗi RX, Probe Request của vài
"điện thoại" giả. Muốn dữ liệu giống thật (người, té ngã, nhịp thở) thì dùng `mo_phong.py` / `mo_phong_ui.py`.

## Thu dữ liệu thật

1. Cắm các RX và sniffer vào laptop (qua hub USB có nguồn), tìm tên cổng:
   ```bash
   python logger.py --list-ports
   ```
   Linux thường là `/dev/ttyACM0`, `/dev/ttyACM1`; Windows là `COM5`, `COM6`...
2. Chạy:
   ```bash
   python logger.py --rx-port /dev/ttyACM0 --rx-port /dev/ttyACM1 --snf-port /dev/ttyACM2 --tag phongA \
       --room "Phong A tang 2" --distance 3 --channel 6 --members "Chien,Tien,Phuc"
   ```
   `--rx-port` lặp lại cho từng RX. Chỉ có một RX thì ghi một lần; chưa có sniffer thì bỏ `--snf-port`.
3. Bấm phím để ghi nhãn (không cần Enter):

   | Phím | Nhãn |
   |---|---|
   | `E` | Phòng trống |
   | `A` hoặc `W` | Người được giám sát đi lại, sinh hoạt |
   | `S` | Ngồi / đứng / nằm yên, thở bình thường |
   | `D` | Nằm bất động sau ngã – bấm ngay sau `F` |
   | `B` | Thở bất thường (nhanh, chậm, nín thở theo kịch bản) |
   | `N` | Phòng trống, có người ở phòng bên |
   | `P` | Tạm dừng (đoạn này bị bỏ khi train) |
   | `F` / `G` / `U` / `L` / `C` | **Động tác** (bấm lúc bắt đầu): ngã / ngồi xuống / đứng dậy / nằm xuống / cúi nhặt |
   | `+` hoặc `=` / `-` | Có người vào / ra (gồm cả khách) – số người trong phòng |
   | `R` | Nhịp thở đáp án theo máy đếm nhịp (gõ số rồi Enter, 0 = nín thở) |
   | `T` | Ghi chú (gõ xong bấm Enter) |
   | `Q` | Kết thúc |

   **Bấm nhãn ngay khi bắt đầu**, và bấm lại mỗi khi tình huống thay đổi. Bộ nhãn định nghĩa ở `nhan.py`,
   ý nghĩa và cách thu dữ liệu ngã an toàn xem `../KE_HOACH_NHANH_NGUOI.md`.

## Dòng trạng thái

```
00:03:12 | Nhãn: ACTIVE | Người: 2 | CSI 199.6/s | PRB  0.5/s | mất 0 | RX 100/99/s, drop 0/0 | SNF kênh 7
```

- `CSI .../s`: tổng của mọi RX (2 RX → gần 200). `RX a/b/s`: số gói mỗi RX nhận trong giây qua, phải gần 100.
- `mất`: số dòng bị mất (dựa trên `seq`). `drop`: số bản ghi mất ngay trên từng RX vì queue đầy.
- `sai`: số dòng sai định dạng. Khác 0 thì chạy lại với `--verbose` để xem dòng nào sai.

## Kiểm tra buổi thu: `kiem_tra_buoi_thu.py`

Chạy ngay sau mỗi buổi thu để biết dữ liệu có dùng được không:

```bash
python kiem_tra_buoi_thu.py                  # buổi thu mới nhất
python kiem_tra_buoi_thu.py ../data/raw/20261112_1430_phongA --save   # lưu report.txt
```

Báo cáo gồm:
1. **CSI, từng RX:** tốc độ thực tế (trung bình và theo từng giây), dòng mất, khoảng mất kết nối, MAC nguồn,
   độ dài CSI (104 hoặc 128), số window hợp lệ; và **tỉ lệ gói nhận được ở mọi RX** (ghép theo `rx_seq`).
2. **Probe Request:** số dòng theo kênh, các nguồn `mac_hash` và số phút mỗi nguồn xuất hiện.
3. **Nhãn:** các đoạn nhãn, tổng thời gian và số window dự kiến của mỗi nhãn, số người đếm tay, số lần mỗi động tác,
   nhịp thở đáp án; cảnh báo ngã mà không bấm `D` sau đó.

Cuối báo cáo là danh sách **LỖI / CẢNH BÁO / ĐẠT**. Có **LỖI** thì buổi thu đó không nên dùng để train.

Với buổi kiểm thử tuần đầu, chỉ cần xem mục 1 và 2 (chưa cần nhãn).

## Đặc trưng: `features.py`

```bash
python features.py                     # mọi buổi trong ../data/raw → ../data/features/ (window 6 s, mục 5)
python features.py --dong-tac          # → ../data/features_action/ (window 3 s trượt 0,5 s, mục 5.2)
```

Mỗi RX một bộ cột có tiền tố (`rx1_csi_var_07`, `rx2_rssi_mad`, …): 4 đặc trưng độ phân tán của bài báo 2 cho RSSI và
từng sóng mang con (52 khi `len` 104; 51 khi `len` 128, bỏ sóng mang con rỗng). Window 6 s có thêm `label`,
`activity`, `n_people`, `breath_rate`; window động tác có `action` (FALL… hoặc NONE) và 2 đặc trưng hình dạng mỗi RX.
Dashboard gọi đúng các hàm trong file này. Chưa khử nhiễu wavelet (`denoise: null` trong `feature_meta.json`).

## Train mô hình: `train.py`

```bash
python train.py                                  # có người / không (label)
python train.py --target activity                # trống / hoạt động / yên
python train.py --target n_people                # đếm 0–3 người
python train.py --target action                  # động tác + té ngã (dùng ../data/features_action)
python train.py --feature-set rx1                # chỉ RX1 – so với 2 RX (all), như kế hoạch mục 6
python train.py --feature-set rssi               # chỉ RSSI, để so với CSI như bài báo 2
```

Chưa có dữ liệu thật thì: `python mo_phong.py --tag sim --so-buoi 8` → `python features.py` → `python train.py`.

`train.py` làm gì:
1. Bỏ window `valid = 0`, lấy X = các cột `rssi_*`/`csi_*` (có hoặc không tiền tố RX), y = mục tiêu đã chọn.
   Mục tiêu nhiều lớp train với trọng số cân bằng lớp (lớp hiếm như FALL không bị NONE lấn át).
2. **Đánh giá theo buổi thu**: mỗi lượt để riêng một buổi làm tập kiểm tra, train trên các buổi còn lại
   (`--folds 3` để gộp thành 3 lượt khi có nhiều buổi). Không chia ngẫu nhiên theo window.
3. So sánh 5 cách: baseline ngưỡng phương sai, Random Forest, Gradient Boosting, XGBoost, bỏ phiếu mềm.
4. In báo cáo: Accuracy, F1, ma trận nhầm lẫn, tỉ lệ đúng theo từng nhãn chi tiết (EMPTY, NEIGHBOR, ACTIVE,
   STILL, DOWN, ...), kết quả từng buổi, 10 đặc trưng quan trọng nhất.
5. Lưu báo cáo vào `../results/<thời gian>_<mục tiêu>_<bộ đặc trưng>/` và mô hình vào `../models/`
   (`model_latest_<mục tiêu>.joblib`; riêng mục tiêu `label` còn ghi `model_latest.joblib` cho dashboard).

Đọc kết quả:
- **Mô hình phải thắng baseline ngưỡng**, nếu không thì học máy chưa mang lại gì.
- **Cột STILL** cho biết khả năng nhận ra người ngồi yên, phần khó nhất của đề tài.
- **Kết quả từng buổi** chênh nhau nhiều nghĩa là mô hình chưa ổn định giữa các buổi/phòng.

## Dashboard: `dashboard.py`

Chạy **song song** với logger, mỗi chương trình một terminal (cả hai đều trong thư mục `laptop/`, đã bật venv):

```bash
python logger.py --simulate --tag demo          # terminal 1 (board thật: --rx-port ... --rx-port ... --snf-port ...)
streamlit run dashboard.py                      # terminal 2, rồi mở http://localhost:8501
```

Giao diện theo phong cách [shadcn/ui](https://ui.shadcn.com/examples/dashboard): đen – trắng – xám làm nền, đỏ nhạt làm màu nhấn cho "có người" (biểu đồ, dải thời gian, thẻ trạng thái khi có người), font Inter.
Dashboard đọc phần mới của các file trong `data/raw/<buổi thu mới nhất>/` mỗi 2 giây:
- **4 thẻ số liệu:** Trạng thái phòng (kèm xác suất, đã ổn định bao lâu, nhãn đang ghi), Thiết bị gần đây,
  Tốc độ CSI (từng RX), Sniffer (kênh đang nghe, độ trễ dữ liệu, số người đếm tay).
- **Xác suất có người:** biểu đồ vùng theo thời gian (chọn 5 / 10 / 30 phút), đường nét đứt là nhãn thật,
  bên dưới là dải "Dự đoán" và "Nhãn thật" để so sánh trực tiếp.
- **Biên độ CSI:** 30 giây gần nhất của RX1, thấy rõ tín hiệu dao động khi có người.
- **Sự kiện gần đây:** đổi trạng thái, bấm nhãn, động tác, nhịp thở đáp án, đếm người, ghi chú, cảnh báo mất dữ liệu.

Cách tính:
- **Người:** 6 giây CSI gần nhất của từng RX → đặc trưng (`features.py`, giống hệt lúc train) →
  `models/model_latest.joblib`. Mô hình cũ (v0.2, cột không tiền tố) vẫn chạy được với RX đầu tiên.
- **Chống nhấp nháy** (bật/tắt ở thanh bên): trạng thái chỉ đổi khi mô hình đoán khác liên tục ≥ 6 giây.
  Tắt đi để xem kết quả thô của mô hình.
- **Thiết bị (bản tạm):** số nguồn `mac_hash` thấy trong 60 giây gần nhất. Sẽ thay bằng máy trạng thái Sherlock.

Thanh bên trái: chọn buổi thu (hoặc tự theo dõi buổi mới nhất), chống nhấp nháy, tốc độ cập nhật, mô hình đang
dùng. Tải lại trang (F5) thì lịch sử trên biểu đồ bắt đầu lại từ đầu.
File `.streamlit/config.toml` giới hạn dashboard chỉ mở trên chính laptop (`localhost`) và đặt màu sáng.

**Phần còn thiếu:**
1. Dashboard mới hiện có người / không; chưa hiện mức hoạt động, số người, động tác / cảnh báo ngã, nhịp thở
   (mô hình và `nhip_tho.py` đã có, cần thêm thẻ hiển thị).
2. Phần thiết bị chưa dùng máy trạng thái Sherlock.

## Mô phỏng 3D theo hướng mới: `mo_phong_ui.py` (giao diện) và `mo_phong.py` (dòng lệnh)

Mô phỏng bố trí 1 TX + 2 RX ở một góc phòng: người đi lại, ngồi xuống, đứng dậy, nằm xuống, cúi nhặt, té ngã (3 kiểu),
thở thường / bất thường; khách vào ra (tối đa 3 người); người ở phòng bên; người bấm phím ngồi trong phòng. Ghi ra
buổi thu **đúng định dạng v0.3** (cột `board`, `rx_seq`, `len` 104, nhãn `STATE` / `ACTION` / `COUNT` / `RATE` /
`NOTE`) để viết trước phần xử lý khi chưa có board. Chỉ cần numpy (matplotlib để lưu ảnh tổng quan).

### Giao diện (khuyên dùng)

```bash
python mo_phong_ui.py          # mở http://127.0.0.1:8502 trên trình duyệt mặc định
```

- **Bên trái**: chọn kịch bản (có sẵn / ngẫu nhiên theo seed / tự viết bằng các nút trạng thái, động tác, khách),
  seed, mức nhiễu, có người bấm phím hay không → **Chạy mô phỏng** (khoảng 1–2 giây cho 5 phút dữ liệu).
- **Giữa**: phòng nhìn từ trên xuống (người, khách, thân khi nằm, vệt đi; đường truyền dày lên khi tín hiệu lệch nhiều;
  nét đứt là sóng dội tường tới từng RX, mờ đi khi bị người che – bật / tắt ở góc trên),
  thẻ thời gian, nhãn, tư thế, số người, nhịp thở đáp án.
- **Bên phải**: biên độ trung bình và bản đồ nhiệt 52 sóng mang con của RX1, RX2 (20 giây gần nhất).
- **Dưới**: dải thời gian cả buổi (bấm / kéo để tua), chạy / dừng, tốc độ ×0,5–×16.
  Phím: **Space** chạy / dừng, **← →** tua 5 giây, **+ −** tốc độ, **Home** về đầu.
- **Lưu vào data/raw/**: ghi đúng buổi vừa xem thành buổi thu (kèm ảnh `mo_phong.png` nếu chọn).
- Server chỉ nghe trên `127.0.0.1`. Tắt bằng Ctrl+C trong terminal.

### Dòng lệnh

```bash
python mo_phong.py --tag sim1 --hinh                          # 1 người: đi, ngồi, cúi, nằm, ngã, thở (~5,5 phút)
python mo_phong.py --tag dong --kich-ban nhieu-nguoi --hinh   # khách vào / ra (tối đa 3 người)
python mo_phong.py --tag nga --kich-ban nga                   # nhiều lần ngã và động tác dễ nhầm
python mo_phong.py --tag x --plan "EMPTY:10,ACTIVE:20,SIT_DOWN,STILL:60@12,STAND_UP,ACTIVE:10"
python mo_phong.py --tag ngaunhien --so-buoi 20               # 20 buổi kịch bản ngẫu nhiên, ~5 phút mỗi buổi
python test_mo_phong.py                                       # tự kiểm tra (cả giao diện)
```

- `--plan`: `TRẠNG_THÁI:giây[@nhịp thở]`, `ĐỘNG_TÁC[:giây]`, `+` / `-` (khách vào / ra). Kịch bản sai tư thế
  (ví dụ `DOWN` khi chưa ngã, đi lại khi đang ngồi) sẽ báo lỗi.
- `--hinh`: lưu `mo_phong.png` (quỹ đạo nhìn từ trên xuống + biên độ CSI của RX1, RX2 theo thời gian).
- `--so-buoi N [--phut 5]`: N buổi kịch bản ngẫu nhiên (`tag-01`, `tag-02`, …; seed tăng dần), ~30 % buổi có khách,
  ngã chiếm tỉ lệ khá cao để đủ mẫu. Kịch bản của từng buổi ghi trong `meta.json` → `simulator.plan`.
- `--nguoi-bam`: người bấm phím ngồi yên cạnh laptop suốt buổi (thở, cử động nhẹ, **không** tính vào `COUNT`).
- `--seed`, `--noise`, `--phat-lai` (ghi theo thời gian thực). Cùng kịch bản + seed thì luôn ra cùng dữ liệu.
- Ngã có 3 kiểu chọn ngẫu nhiên: đổ thẳng, khuỵu gối rồi đổ, ngã từ ghế (khi đang ngồi); kiểu ngã ghi ở nhãn `NOTE`.
  Khách dừng lâu (≥ 4 giây) thì ngồi xuống.
- **Mỗi buổi một phòng hơi khác**: đồ đạc cố định xê dịch ±0,2 m và có thêm 3–6 vật lặt vặt (ghế, túi, chai…) ở chỗ
  ngẫu nhiên → kênh lúc phòng trống khác nhau giữa các buổi như ngoài đời (lý do phải chia train / test theo buổi).
  **Đợt nhiễu chen ngang** (Wi-Fi khác, lò vi sóng): trung bình 1 đợt / 2 phút, 1–4 s, nhiễu ×3 và mất 30 % gói; vạch đỏ
  trên giao diện. Người đi lại mượt (tăng / giảm tốc, rẽ vòng, ≤ ~1,1 m/s), ra vào đi bộ qua cửa. Các vật và tổng thời
  gian nhiễu của buổi ghi ở `meta.json` → `simulator.objects`, `simulator.bursts_s`. Tất cả suy ra từ seed.
- **Chống "kết quả đẹp ảo"**: động tác không ghi thời lượng thì mỗi lần một thời lượng ngẫu nhiên (ví dụ ngã 0,8–1,6 s,
  ngồi xuống 1,2–2,4 s) và biên độ khác nhau; nhịp thở dao động ±8 %, độ sâu ±25 %; ngồi / nằm yên lâu thì 20–40 giây
  xê dịch 3–8 cm một lần (`DOWN` – nằm sau ngã – vẫn bất động); **nhãn bấm trễ 0–0,8 s** (trung bình 0,3 s) như người
  bấm phím thật. Thời điểm thật của từng đoạn ghi ở `meta.json` → `simulator.truth` để chấm thuật toán.
  Hệ quả đã thấy: nhịp thở đo bằng FFT thô chỉ đúng ~70 % số lần; trừ trung bình trượt 4 giây trước khi FFT thì ~95 %.
- Mô hình **3D** (chi tiết ở đầu `mo_phong.py`): phòng 4 × 3,5 × 2,8 m có sàn, trần; phản xạ bậc 1–2 trên 6 mặt với hệ
  số Fresnel theo vật liệu (bê tông, thạch cao); ăng-ten cao 0,75 m; người là 9 điểm theo chiều cao cơ thể ở tư thế
  đứng / ngồi / nằm; người che sóng tính bằng nhiễu xạ Fresnel–Kirchhoff qua tấm chắn (đứng chắn giữa đường truyền
  ~9 dB, nằm dưới sàn gần như không chắn); AGC của ESP32 tự bù ~90 % sự đổi công suất. Chưa có phản xạ bậc ≥ 3 và
  người che phản xạ bậc 2. Chỉ để **thử luồng xử lý**, không dùng để báo cáo độ chính xác.
- `kiem_tra_buoi_thu.py`, `train.py`, dashboard **chưa đọc được v0.3** (sẽ trộn RX1 với RX2) – phải sửa theo v0.3.
- **Đã đối chiếu với WiFall** (`python doi_chieu_wifall.py`, kết quả ở `../results/doi_chieu_wifall/`): mức biên độ 15,
  nhiễu 0,05, AGC 0,05 lấy theo ESP32-S3 thật; dò tham số cho thấy mô phỏng khớp nhất khi **AGC bù gần hết** sự đổi công
  suất (độ lệch 0,49 → 0,29). Mức dao động khi có động tác cùng cỡ với thật (lệch trung bình ~30 %), riêng biên độ
  trung bình khi đi lại / ngồi xuống dao động gấp ~2 lần (phòng của WiFall khác phòng mô phỏng). Có buổi thu thật của
  nhóm thì đối chiếu lại bằng chính dữ liệu đó.
- Hệ quả cần biết khi viết thuật toán: đi lại chỉ làm dao động biên độ gấp ~1,8–2,3 lần phòng trống (không phải
  "rõ mồn một"); nhịp thở đo bằng thuật toán đơn giản đúng khoảng 50–80 % tuỳ chỗ ngồi → cần gộp nhiều sóng mang con,
  gộp hai RX.

## Nhịp thở: `nhip_tho.py`

```python
from nhip_tho import uoc_luong
bpm, do_noi, ly_do = uoc_luong([amp_rx1, amp_rx2], fs=100)   # biên độ (số mẫu, 52) của 2 RX, cửa sổ ~30 giây
```

Gộp 0,1 s → kiểm tra cử động (dao động chậm so với nhiễu nền) → chia mức nhiễu từng sóng mang con → cắt bỏ các lần
xê dịch tư thế → lọc 0,08–1 Hz → PCA trên 104 sóng mang con của 2 RX → đỉnh phổ trong 6–45 nhịp/phút, nội suy parabol.
Trả về `None` kèm lý do khi đang cử động (`cu-dong`) hoặc đỉnh không đủ nổi (`khong-thay`: nín thở, quá xa, nhiễu).

`python nhip_tho.py` tự đánh giá trên mô phỏng 3D (108 cửa sổ 30 s, ngồi ở chỗ ngẫu nhiên, nhịp 8–36/phút):

| | Thuật toán đơn giản (FFT 1 sóng mang con) | `nhip_tho.py` |
|---|---|---|
| Đúng ±2 nhịp/phút | 43 %, luôn trả lời, không biết khi nào sai | **69 % khi trả lời** (trả lời ~42 % số cửa sổ) |
| Nín thở 30 s bị nhầm là có thở | – | 14 % |
| Đang đi lại | đưa ra số sai | không đưa ra nhịp |

Đã thử ghép 2 cửa sổ liền nhau (cùng ra một nhịp thì nhận dù từng cửa sổ chưa đủ tin cậy): trả lời nhiều hơn (~45 %)
nhưng nín thở bị nhầm là có thở cũng tăng (vì 2 cửa sổ 30 s cách 3 s trùng nhau 27 s, không độc lập) → không dùng.

Lưu ý khi dùng: "không thấy nhịp thở" ở **một** cửa sổ chưa đủ để báo ngưng thở (thường do tín hiệu yếu). Cảnh báo ngưng
thở nên cần: người đang yên, trước đó đo được nhịp ổn định, rồi nhiều cửa sổ liên tiếp không thấy. Ngưỡng `MIN_PROM`
đổi được: thấp hơn thì trả lời nhiều hơn nhưng sai nhiều hơn (bảng ở cuối lệnh tự đánh giá).

## File `logger_config.json`

Tự tạo ở lần chạy đầu, chứa `salt` để băm MAC và `exclude_macs` (MAC cần loại trừ thêm, ví dụ laptop demo).
**Cả nhóm dùng chung một file** (để cùng một MAC cho cùng `mac_hash`), gửi cho nhau riêng, **không đưa lên Git**.
MAC của các board được loại trừ tự động từ dòng `BOOT`.
