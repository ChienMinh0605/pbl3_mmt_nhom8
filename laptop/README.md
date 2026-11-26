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
| `canh_bao.py`, `test_canh_bao.py` | **Bộ ra quyết định cảnh báo**: ngã (xác nhận 10 s), bất động lâu, nhịp thở, cờ kênh nhiễu, đếm người "phân vân thì chọn 1" |
| `danh_gia_canh_bao.py` | Đánh giá cảnh báo **theo sự kiện** trên buổi mô phỏng: độ nhạy ngã, báo giả mỗi giờ, độ trễ |
| `wifall_dong_tac.py` | Kiểm chứng đặc trưng động tác trên WiFall (ngã / không ngã, chia theo người) |

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
`activity`, `n_people`, `breath_rate`; window động tác có `action` (FALL… hoặc NONE) và các đặc trưng hình dạng mỗi RX:
`shape_peak`, `shape_ratio` và 13 đặc trưng chuyển động trên thành phần chính PC1 của các sóng mang con
(`shape_pc1`, `cvmed`, `cvmax`, năng lượng 5 dải `b0`…`b4` từ 0,3 tới 40 Hz, `slope`, `pos`, `after`, `before`, `busy`
– ý nghĩa ở docstring). Trên mô phỏng 40 buổi chúng nâng F1 của FALL từ 0,49 lên 0,65; trên WiFall (dữ liệu thật,
`python wifall_dong_tac.py`) không làm xấu đi. Dashboard gọi đúng các hàm trong file này. Chưa khử nhiễu wavelet (`denoise: null` trong `feature_meta.json`).

## Train mô hình: `train.py`

```bash
python train.py                                  # có người / không (label)
python train.py --target activity                # trống / hoạt động / yên
python train.py --target n_people                # đếm 0–3 người
python train.py --target action                  # động tác + té ngã (dùng ../data/features_action)
python train.py --feature-set rx1                # chỉ RX1 – so với 2 RX (all), như kế hoạch mục 6
python train.py --feature-set rssi               # chỉ RSSI, để so với CSI như bài báo 2
python train.py --feature-set gon                # bỏ cột từng sóng mang con (dễ "học vị trí")
```

- `--target n_people` in thêm bảng **"phân vân thì chọn 1"**: chỉ nhận ≥ 2 người khi P(≥2) ≥ τ, kèm tỉ lệ lỗi nguy
  hiểm (thật 1 người → đoán ≥ 2, hệ thống sẽ tắt phát hiện ngã). τ mặc định lưu vào mô hình (`uu_tien_1_nguong`, hiện
  0,8: lỗi nguy hiểm 1,3 % trên mô phỏng, đổi lại chỉ nhận ra ~11 % lúc thật có 2–3 người).
- `--target action` in thêm bảng ngưỡng P(FALL) và lưu ngưỡng ưu tiên bắt ngã (`fall_nguong`, chọn theo F2).

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

Mô phỏng bố trí 1 TX + 2 RX ở một góc phòng: người đi lại, ngồi xuống, đứng dậy, nằm xuống, cúi nhặt, té ngã (3 kiểu;
sau ngã nằm bất động hoặc còn giãy, cố nhổm dậy), thở thường / bất thường, ngồi yên lâu; khách vào ra (tối đa 3
người); người ở phòng bên; người bấm phím ngồi trong phòng; Wi‑Fi khác chiếm kênh, lò vi sóng. Ghi ra buổi thu
**đúng định dạng v0.3** (cột `board`, `rx_seq`, `len` 104, nhãn `STATE` / `ACTION` / `COUNT` / `RATE` /
`NOTE`) để viết trước phần xử lý khi chưa có board. Chỉ cần numpy (matplotlib để lưu ảnh tổng quan).

### Giao diện (khuyên dùng)

```bash
python mo_phong_ui.py          # mở http://127.0.0.1:8502 trên trình duyệt mặc định
```

- **Bên trái**: chọn kịch bản (có sẵn, kể cả `bat-dong` / ngẫu nhiên theo seed / tự viết bằng các nút trạng thái,
  động tác, khách; nút **Nằm sau ngã, cử động** thêm `DOWN:30@15~`),
  seed, mức nhiễu, có người bấm phím hay không → **Chạy mô phỏng** (khoảng 1–2 giây cho 5 phút dữ liệu).
- **Giữa**: phòng nhìn từ trên xuống (người, khách, thân khi nằm, vệt đi; đường truyền dày lên khi tín hiệu lệch nhiều;
  nét đứt là sóng dội tường tới từng RX, mờ đi khi bị người che – bật / tắt ở góc trên),
  thẻ thời gian, nhãn, tư thế, số người, nhịp thở đáp án.
- **Bên phải**: biên độ trung bình và bản đồ nhiệt 52 sóng mang con của RX1, RX2 (20 giây gần nhất).
- **Dưới**: dải thời gian cả buổi (bấm / kéo để tua), chạy / dừng, tốc độ ×0,5–×16. Đoạn nằm sau ngã có cử động có
  sọc chéo; vạch dưới đáy là đợt nhiễu: đỏ = Wi‑Fi khác chiếm kênh, cam = nhiễu không phải Wi‑Fi.
  Phím: **Space** chạy / dừng, **← →** tua 5 giây, **+ −** tốc độ, **Home** về đầu.
- **Lưu vào data/raw/**: ghi đúng buổi vừa xem thành buổi thu (kèm ảnh `mo_phong.png` nếu chọn).
- Server chỉ nghe trên `127.0.0.1`. Tắt bằng Ctrl+C trong terminal.

### Dòng lệnh

```bash
python mo_phong.py --tag sim1 --hinh                          # 1 người: đi, ngồi, cúi, nằm, ngã, thở (~5,5 phút)
python mo_phong.py --tag dong --kich-ban nhieu-nguoi --hinh   # khách vào / ra (tối đa 3 người)
python mo_phong.py --tag nga --kich-ban nga                   # nhiều lần ngã và động tác dễ nhầm
python mo_phong.py --tag x --plan "EMPTY:10,ACTIVE:20,SIT_DOWN,STILL:60@12,STAND_UP,ACTIVE:10"
python mo_phong.py --tag nga2 --plan "EMPTY:10,ACTIVE:20,FALL,DOWN:40@18~,STAND_UP,ACTIVE:10"   # ngã rồi giãy
python mo_phong.py --tag yen --kich-ban bat-dong              # nằm yên 4 phút, ngồi yên 7 phút (~13 phút)
python mo_phong.py --tag kenh --nhieu "wifi@60:30,khac@200:3" # ép thêm đợt nhiễu
python mo_phong.py --tag ngaunhien --so-buoi 20               # 20 buổi kịch bản ngẫu nhiên, ~5 phút mỗi buổi
python mo_phong.py --tag lau --so-buoi 20 --yen-lau 0.3       # như trên, 30 % số buổi có một đoạn yên 4–8 phút
python test_mo_phong.py                                       # tự kiểm tra (cả giao diện)
```

- `--plan`: `TRẠNG_THÁI:giây[@nhịp thở]`, `ĐỘNG_TÁC[:giây]`, `+` / `-` (khách vào / ra). Kịch bản sai tư thế
  (ví dụ `DOWN` khi chưa ngã, đi lại khi đang ngồi) sẽ báo lỗi.
- `DOWN:giây@nhịp~` (hậu tố `~`, chỉ cho `DOWN`): ngã rồi không tự dậy được nhưng còn cử động – từng đợt 1–5 s, nghỉ
  2–12 s: giãy tay chân 3–20 cm, lăn / xoay người, cố nhổm dậy (độ cao tư thế lên 0,2–0,35 rồi tụt lại); vẫn thở,
  **không bao giờ đứng lên**. Nhãn vẫn `STATE DOWN`, thêm `NOTE` `DOWN cu-dong`. Dùng để thử "giãy vẫn phải cảnh báo
  ngã". Trên CSI: giãy tay chân sát sàn chỉ hơi nổi trên nhiễu (cửa sổ 1 s dao động gấp ~1,2 lần nằm bất động), lúc
  cố nhổm dậy thì rõ (~2–3 lần).
- `--nhieu "wifi@60:30,khac@200:3"`: ép thêm đợt nhiễu (`loại@giây bắt đầu:thời lượng`), cộng với các đợt ngẫu nhiên;
  thêm mục `tat` (ví dụ `"tat,wifi@60:30"`) để bỏ các đợt ngẫu nhiên. Sai cú pháp thì báo lỗi ngay.
- `--hinh`: lưu `mo_phong.png` (quỹ đạo nhìn từ trên xuống + biên độ CSI của RX1, RX2 theo thời gian).
- `--so-buoi N [--phut 5]`: N buổi kịch bản ngẫu nhiên (`tag-01`, `tag-02`, …; seed tăng dần), ~30 % buổi có khách,
  ngã chiếm tỉ lệ khá cao để đủ mẫu, ~35 % lần ngã có cử động (`DOWN~`). `--yen-lau 0.3`: 30 % số buổi có một đoạn
  ngồi / nằm yên 4–8 phút (mặc định 0 – bộ dữ liệu cũ giữ phân bố). Kịch bản của từng buổi ghi trong `meta.json` →
  `simulator.plan`.
- `--nguoi-bam`: người bấm phím ngồi yên cạnh laptop suốt buổi (thở, cử động nhẹ, **không** tính vào `COUNT`).
- `--seed`, `--noise`, `--phat-lai` (ghi theo thời gian thực). Cùng kịch bản + seed thì luôn ra cùng dữ liệu.
- Ngã có 3 kiểu chọn ngẫu nhiên: đổ thẳng, khuỵu gối rồi đổ, ngã từ ghế (khi đang ngồi); kiểu ngã ghi ở nhãn `NOTE`.
  Khách dừng lâu (≥ 4 giây) thì ngồi xuống.
- **Mỗi buổi một phòng hơi khác**: đồ đạc cố định xê dịch ±0,2 m và có thêm 3–6 vật lặt vặt (ghế, túi, chai…) ở chỗ
  ngẫu nhiên → kênh lúc phòng trống khác nhau giữa các buổi như ngoài đời (lý do phải chia train / test theo buổi).
  Người đi lại mượt (tăng / giảm tốc, rẽ vòng, ≤ ~1,1 m/s), ra vào đi bộ qua cửa. Các vật ghi ở `meta.json` →
  `simulator.objects`. Tất cả suy ra từ seed.
- **Đợt nhiễu chen ngang**, hai loại (giá trị khởi đầu, chưa đo trên board):
  - `wifi` – thiết bị Wi‑Fi khác chiếm kênh CSI (tải dữ liệu): đợt ngắn 1–4 s (cùng các đợt `khac`: trung bình 1 đợt /
    2 phút, 70 % là Wi‑Fi) và đợt dài 10–60 s (trung bình 1 đợt / 5 phút). Trong đợt: `n_filtered` của dòng `STAT`
    50–400 khung/giây (lúc thường 0–5), mất 5–40 % gói của TX (kênh càng bận mất càng nhiều), nhiễu CSI ×1,5, 1–3 % gói
    CSI hỏng (biên độ cả gói nhảy ×/÷ 2–4). Đây là tín hiệu để nhánh thiết bị (Q2) đánh dấu đoạn CSI kém tin cậy.
  - `khac` – nhiễu không phải Wi‑Fi (lò vi sóng): `n_filtered` không tăng, `noise_floor` trong dòng `CSI` -95 → -85,
    nhiễu ×3, mất 30 % gói.
- **Đáp án trong `meta.json` → `simulator`** (giây tính từ đầu mô phỏng): `truth` = `[[nhãn, đầu, cuối], …]` mọi đoạn,
  `down_cu_dong` = `[[đầu, cuối], …]` các đoạn `DOWN~`, `interference` = `[[loại, đầu, cuối], …]` các đợt nhiễu,
  `bursts_s` = tổng số giây có nhiễu, `nhieu` = chuỗi `--nhieu` đã dùng; `t0_host` = `host_time` của giây 0, nên
  `host_time = t0_host + giây`.
- **Chống "kết quả đẹp ảo"**: động tác không ghi thời lượng thì mỗi lần một thời lượng ngẫu nhiên (ví dụ ngã 0,8–1,6 s,
  ngồi xuống 1,2–2,4 s) và biên độ khác nhau; nhịp thở dao động ±8 %, độ sâu ±25 %; ngồi / nằm yên lâu thì 20–40 giây
  xê dịch 3–8 cm một lần (`DOWN` bất động, `DOWN~` cử động như trên); **nhãn bấm trễ 0–0,8 s** (trung bình 0,3 s) như
  người bấm phím thật – chấm thuật toán theo `simulator.truth`, không theo `labels.csv`.
  Hệ quả đã thấy: nhịp thở đo bằng FFT thô chỉ đúng ~70 % số lần; trừ trung bình trượt 4 giây trước khi FFT thì ~95 %.
- Mô hình **3D** (chi tiết ở đầu `mo_phong.py`): phòng 4 × 3,5 × 2,8 m có sàn, trần; phản xạ bậc 1–2 trên 6 mặt với hệ
  số Fresnel theo vật liệu (bê tông, thạch cao); ăng-ten cao 0,75 m; người là 9 điểm theo chiều cao cơ thể ở tư thế
  đứng / ngồi / nằm; người che sóng tính bằng nhiễu xạ Fresnel–Kirchhoff qua tấm chắn (đứng chắn giữa đường truyền
  ~9 dB, nằm dưới sàn gần như không chắn); AGC của ESP32 tự bù ~90 % sự đổi công suất. Chưa có phản xạ bậc ≥ 3 và
  người che phản xạ bậc 2. Chỉ để **thử luồng xử lý**, không dùng để báo cáo độ chính xác.
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
Từ khi mô phỏng có đợt Wi‑Fi chiếm kênh (gói CSI hỏng), tỉ lệ trả lời giảm (~0,53 → ~0,39): nên bỏ các giây kênh bận
trước khi đo – `canh_bao.py` đã không dùng kết quả nhịp thở chồng lên giây kênh bận.

## Cảnh báo: `canh_bao.py` và đánh giá theo sự kiện `danh_gia_canh_bao.py`

`canh_bao.py` biến dự đoán của các tầng thành **sự kiện cảnh báo** theo đúng quy tắc của kế hoạch (mục 3): `NGA` (ngã +
10 s chờ; biến thể b – mặc định – huỷ khi thấy đứng dậy hoặc Hoạt động suốt 10 s, giãy ngắn vẫn báo), `NGA_KHAN_CAP` (ngã mà không thấy cử động lẫn nhịp thở), `BAT_DONG_LAU`
(Yên ≥ 300 s), `THO_BAT_THUONG` (> 25 hoặc < 8 nhịp/phút), `NGUNG_THO` (nhiều cửa sổ liên tiếp không thấy nhịp, sau khi
đã đo được). Đếm người: phân vân thì chọn 1, và chỉ sang chế độ nhiều người khi thấy ≥ 2 người ở nhiều window liên tiếp.
Cờ kênh: giây kênh bận (`n_filtered` > 30 hoặc `n_rx` < 85 gói/s) không dùng để kết luận; ngã phát hiện lúc kênh bận
thì chờ kênh sạch rồi mới xác nhận. Mọi ngưỡng nằm trong `ThamSo`; dashboard gọi `CanhBao.cap_nhat()` mỗi lần có dự
đoán mới (chưa ghép). Kiểm tra: `python test_canh_bao.py`.

```bash
python mo_phong.py --tag v2 --so-buoi 40 --yen-lau 0.3 --data-dir ../data/sim2      # dữ liệu giả, tách khỏi data/raw
python features.py ../data/sim2/raw/* --out ../data/sim2/features
python features.py --dong-tac ../data/sim2/raw/* --out ../data/sim2/features_action
python danh_gia_canh_bao.py --data ../data/sim2 --folds 5 --jobs 5                 # mặc định cách B, ~15 phút
python danh_gia_canh_bao.py --du-doan ../results/<...>_canh_bao/du_doan.joblib --tau-nga 0.3 --tham-so so_window_nga=1
```

Chia theo buổi (GroupKFold), mỗi lượt train mức hoạt động, ≥ 2 người (window 6 s trượt, nhãn lúc cuối window –
`--tang0 cuoi`), động tác (25 cột `mot`/`mon` mỗi board, XGBoost sâu 5) trên buổi train; buổi test tính đặc trưng
**trượt từ dữ liệu thô, không dùng nhãn** (như lúc chạy thật; nhịp thở trên lưới thời gian, gói mất = NaN), chạy
`canh_bao`, so với thời điểm thật (`meta.json → simulator.truth`). So 4 cấu hình: biến thể huỷ ngã a / b × có / không cờ
kênh. `--du-doan` chấm lại trong vài giây với tham số khác, không train lại.

Kết quả trên 40 buổi `data/sim2` (4,3 giờ, có giãy sau ngã, nhiễu kênh, ngồi yên lâu), **cách B, biến thể b, có cờ
kênh**, ngưỡng P(FALL) 0,4 – **dữ liệu giả, chỉ để thử luồng**. Báo cáo: `../results/20261126_092749_canh_bao/`.

| | Vòng 1 | Vòng 2 | **Vòng 3 (26/11)** |
|---|---|---|---|
| Ngã bắt được (trong 30 s) | 34/53 | 39/53 | **44/53 (83 %)**, trễ TB 13,6 s; ngã có giãy 17/18 |
| Báo ngã giả (lần/giờ) | ~14 | 6,7 | **5,1** – còn lại sinh từ lúc đi lại và ngồi yên |
| Báo giả khác (lần/giờ): khẩn cấp / thở bất thường / ngưng thở / bất động lâu | 3,5 / 16,7 / 0,7 / – | 1,9 / 1,9 / 1,9 / 0,7 | 1,2 / 2,1 / 2,6 / 0,7 |
| Bất động lâu bắt được | 3/8 | 5/8 | 5/8 |
| Thở nhanh/chậm / nín thở bắt được | 8/21, 5/12 | 2/21, 1/12 | 6/21, 1/12 – tín hiệu thở trên mô phỏng sát nhiễu; nín thở 15–36 s ngắn so với quy tắc 3 cửa sổ |
| Đếm người: lỗi nguy hiểm / nhận ra 2–3 người | 0,3 % / 9 % | 0,4 % / ~9 % | **0,1 %** / 10 % |
| Mỗi board: cột (6 s + 3 s), nút cây | 212 + 227 | 212 + 25 | **19 + 25**, ~32 + ~69 nghìn nút (~1–1,5 MB) |

Vòng 3: cột gọn `g6` cho window 6 s (4 loại đặc trưng của bài báo 2 × RSSI, mức chung, PC1, PC2 + năng lượng dải thở
+ tỉ lệ gói hỏng), cờ kênh chỉ lùi hạn khi giây bận có thể che dấu hiệu đứng dậy / đi lại, `nhip_tho` cân bằng lại.
Quy tắc "Trống liên tục 4 s sau ngã thì huỷ" (`huy_trong_s`) đang TẮT, chờ kiểm trên dữ liệu thật.

**Gộp hai RX (`--gop`).** `chung` = một mô hình trên cột của cả hai RX (gộp sớm, cách A); `muon` = mỗi RX một mô hình
chỉ trên cột của nó, như mỗi board tự chạy, rồi gộp kết quả (gộp muộn, cách B – hướng chính vì mục tiêu chạy trên
board, mặc định): ngã lấy max P(FALL) (một board thấy là đủ), nhiều người lấy min P(≥2) (cả hai cùng thấy), mức hoạt
động / động tác lấy trung bình, nhịp thở lấy board có đỉnh nổi nhất. So sánh A/B vòng 1 (trước khi có bộ 25 cột): trên 40 buổi `data/sim2` (biến thể b, có cờ kênh), so ở cùng
mức báo ngã giả: A ngưỡng P(FALL) 0,3 → 31/53 ngã, 9,0 lần/giờ; B ngưỡng 0,5 → 30/53, 8,1 lần/giờ – **ngang nhau**. B tốt
hơn ở nhịp thở (thở nhanh/chậm 13/21 so với 8/21, ngưng thở giả 3 so với 6,7 lần/giờ), kém hơn ở thở bất thường giả
(16,7 so với 10,9 lần/giờ) và nín thở. Mỗi board của B: 212 cột (6 s) + 227 cột (3 s), ~64 nghìn nút cây XGBoost.

## File `logger_config.json`

Tự tạo ở lần chạy đầu, chứa `salt` để băm MAC và `exclude_macs` (MAC cần loại trừ thêm, ví dụ laptop demo).
**Cả nhóm dùng chung một file** (để cùng một MAC cho cùng `mac_hash`), gửi cho nhau riêng, **không đưa lên Git**.
MAC của các board được loại trừ tự động từ dòng `BOOT`.
