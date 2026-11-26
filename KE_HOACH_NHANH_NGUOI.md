# Kế hoạch nhánh người – Giám sát an toàn người ở một mình bằng Wi‑Fi CSI

**Cập nhật:** 23/11/2026 · **Hạn báo cáo:** 26/12/2026
**Đặc tả dữ liệu đi kèm:** `Dac_ta_dinh_dang_du_lieu.md` v0.3

---

## 1. Ý tưởng

Hệ thống theo dõi người trong phòng **không dùng camera, không cần đeo thiết bị**, chỉ dựa vào việc cơ thể người làm
thay đổi sóng Wi‑Fi giữa các board ESP32. Một board phát gói tin liên tục, hai board thu thông tin kênh truyền (CSI)
và gửi về laptop. Các board đặt quanh **một góc phòng** làm khu demo (khoảng 2 × 2 m). Laptop xử lý tín hiệu, chạy
mô hình học máy và hiện kết quả lên dashboard theo thời gian thực.

Nền tảng là **phát hiện có người**. Khi có người, hệ thống **ước lượng số người (1, 2 hoặc 3)** rồi chọn chế độ:

| Chế độ | Hệ thống làm gì | Vì sao |
|---|---|---|
| **1 người** (tình huống chính) | Nhận dạng động tác: đi lại, ngồi xuống, đứng dậy, nằm xuống, cúi nhặt đồ, **té ngã**. Khi người yên: **đo nhịp thở**, cảnh báo thở quá nhanh / quá chậm / ngưng; cảnh báo **bất động quá lâu** | Nguy hiểm nhất vì không ai ở bên |
| **2–3 người** | Chỉ **đếm số người**. Tắt nhận dạng động tác, phát hiện ngã và nhịp thở | Tín hiệu nhiều người trộn lẫn, không tách được. Phân vân giữa 1 và 2 người thì chọn 1, để không tắt nhầm phát hiện ngã |

**Không làm:** nhận dạng ai, xác định vị trí trong phòng, nhận dạng động tác khi có nhiều người, chẩn đoán bệnh
(chỉ cảnh báo dấu hiệu bất thường).

**Vì sao Wi‑Fi:** riêng tư hơn camera, không cần nhớ đeo như vòng tay, phần cứng rẻ.

## 2. Phần cứng và bố trí

Nhóm có 4 ESP32‑C3 và 2 ESP32‑S3.

| Vai trò | Board | Ghi chú |
|---|---|---|
| TX | 1 C3 | Đặt ở góc phòng, phát **ESP‑NOW broadcast** khoảng 100 gói/s |
| RX1, RX2 | 2 S3 | Đặt ở hai cạnh khu demo, tạo **2 đường truyền cắt qua chỗ người hoạt động**. Cùng thu CSI của cùng một gói |
| SNF | 1 C3 | Nhánh thiết bị: nghe tiêu đề khung Wi‑Fi trên mạng nhà (`DE_XUAT_NHANH_THIET_BI.md`, chờ chốt) |
| Dự phòng | 2 C3 | Thay khi board hỏng; một con có thể làm RX3 nếu đếm người kém |

- **Vì sao ESP‑NOW broadcast** thay cho SoftAP + ping: firmware đơn giản hơn (sửa từ ví dụ `csi_send`/`csi_recv`
  của repo esp‑csi), mọi RX thu cùng một gói, và trường `rx_seq` cho phép ghép dữ liệu các RX theo từng gói.
- **Vì sao RX là S3:** hai bộ dữ liệu công khai WiFall và WiCount thu bằng ESP32‑S3 với cấu hình esp‑csi, nên dữ
  liệu của nhóm so được trực tiếp (mục 5.2).
- Laptop cần **hub USB có nguồn riêng** (RX1, RX2, SNF = 3 cổng).
- **Làm theo bậc:** 1 TX + 1 RX chạy thông từ đầu đến cuối trước, rồi mới nạp cùng firmware cho RX2. Nhiều RX có
  trục trặc thì quay về 1 đường, không mất gì.

## 3. Kiến trúc xử lý

```
CSI RX1, RX2 (~100 mẫu/s)
   │
   ├─► Tầng 0: window 6 s → đặc trưng (độ phân tán theo thời gian, bài báo 2) → Có người? (0 / ≥1)
   │            + mức hoạt động: Trống / Hoạt động / Yên
   │            + năng lượng dải thở 0,1–0,6 Hz: giúp phân biệt "phòng trống" với "người ngồi yên"
   │
   ├─► Tầng 1: Mấy người? (1 / 2 / 3) – chỉ CẬP NHẬT khi có chuyển động, phòng yên thì GIỮ số cũ
   │            (số người chỉ đổi khi có người vào/ra, mà vào/ra thì phải đi lại)
   │
   ├─ 1 người ─► Tầng 2a: window 3 s, trượt 0,5 s → động tác:
   │             đi lại / ngồi xuống / đứng dậy / nằm xuống / cúi nhặt / NGÃ / không có động tác
   │             Tư thế hiện tại suy ra từ động tác cuối (ngồi xuống → đang ngồi ...)
   │             CẢNH BÁO NGÃ = động tác "ngã" + 10 s sau đó không đứng dậy / đi lại
   │             (huỷ khi thấy đứng dậy, hoặc "Hoạt động" liên tục suốt 10 s chờ; giãy vài giây rồi nằm
   │             vẫn báo – giới hạn: giãy liên tục ≥ 10 s thì CSI không phân biệt được với đi lại)
   │             CẢNH BÁO BẤT ĐỘNG LÂU = "Yên" liên tục quá ngưỡng (demo: 5 phút)
   │
   │            Tầng 2b: khi Yên → window 30 s, lọc 0,1–0,6 Hz, FFT, chọn đường truyền có dải thở mạnh nhất
   │             → nhịp thở/phút; > 25, < 8 hoặc ngưng > 15 s → CẢNH BÁO
   │             Ngã mà không thấy cả cử động lẫn nhịp thở → mức KHẨN CẤP CAO NHẤT
   │
   └─ 2–3 người ► chỉ hiện "Có N người"
```

- **Ngã khác nằm xuống ở động tác, không ở vị trí:** ngã nhanh, năng lượng lớn, ngắn 1–2 s; nằm xuống chậm và đều
  hơn. Bước xác nhận 10 s loại các trường hợp ngồi phịch xuống rồi đứng dậy ngay.
- **Nhịp thở** là xử lý tín hiệu, không cần học máy: `laptop/nhip_tho.py` (PCA trên 2 RX, có độ tin cậy, kiểm tra cử
  động). Trên mô phỏng: đúng ±2 nhịp/phút ~70 % khi trả lời; chỉ hiện nhịp khi đủ tin cậy. Cảnh báo ngưng thở cần nhiều
  cửa sổ liên tiếp "không thấy nhịp thở" khi người đang yên và trước đó đo được nhịp – một cửa sổ chưa đủ.
- Dự phòng cho demo: công tắc **"Chế độ có khách"** bấm tay trên dashboard, ghi đè kết quả đếm người.
- Các ngưỡng (10 s, 25/8 nhịp/phút, 15 s, 5 phút) là **giá trị khởi đầu**, sẽ chỉnh theo dữ liệu.
- **Nhánh thiết bị** (đề xuất, chờ chốt) bổ trợ ở ba chỗ: đánh dấu đoạn CSI nhiễu khi kênh bị thiết bị khác chiếm,
  hoãn có giới hạn cảnh báo bất động lâu khi điện thoại trong nhà đang được dùng, chọn người nhận cảnh báo. Không bao
  giờ huỷ cảnh báo ngã. Chi tiết: `DE_XUAT_NHANH_THIET_BI.md`.

## 4. Nhãn (đặc tả mục 4.4, định nghĩa trong `laptop/nhan.py`)

**Trạng thái** (kéo dài đến lần bấm trạng thái tiếp theo):

| Nhãn | Phím | Ý nghĩa |
|---|---|---|
| `EMPTY` | E | Phòng trống |
| `NEIGHBOR` | N | Phòng trống, có người ở phòng bên (chỉ thu 1 buổi để kiểm tra báo động giả) |
| `ACTIVE` | A / W | Đi lại, sinh hoạt |
| `STILL` | S | Ngồi / đứng / nằm yên, thở bình thường |
| `DOWN` | D | Nằm bất động sau ngã |
| `BREATH_ABN` | B | Yên nhưng thở bất thường (thở nhanh, chậm, nín thở theo kịch bản) |
| `PAUSE` | P | Đang sắp xếp, bỏ đoạn này |

**Động tác** (sự kiện ngắn, bấm **lúc bắt đầu** động tác, không đổi trạng thái):

| Nhãn | Phím | Tư thế sau đó |
|---|---|---|
| `FALL` | F | Nằm |
| `SIT_DOWN` | G | Ngồi |
| `STAND_UP` | U | Đứng |
| `LIE_DOWN` | L | Nằm |
| `PICK_UP` | C | Đứng (động tác dễ nhầm với ngã) |

**Khác:** `+` / `-` số người vào/ra (gồm cả khách), `R` nhịp thở đáp án (gõ số nhịp/phút rồi Enter), `T` ghi chú.

## 5. Dữ liệu

### 5.1. Tự thu (bắt buộc – kết quả chính của báo cáo đo trên dữ liệu này)

Tất cả thu tại **cùng một khu demo**, TX/RX cố định vị trí.

- **Buổi 1 người** theo kịch bản cố định, lặp nhiều lần mỗi buổi: phòng trống → vào, đi lại → ngồi xuống, ngồi yên
  → đứng dậy → cúi nhặt đồ → nằm xuống, nằm yên → đứng dậy → **ngã có kiểm soát trên nệm dày** (bấm `F` rồi `D`,
  nằm 20–60 s) → đứng dậy → ra. **Không ngã mạnh, không ngã trên sàn cứng.**
- **Nhịp thở:** ngồi/nằm yên, thở theo app máy đếm nhịp (12 và 30 nhịp/phút), nín thở 20 s; bấm `R` ghi nhịp đáp án.
- **Buổi 2–3 người:** đi lại, ngồi, ra vào; bấm `+` / `-` mỗi lần có người vào/ra.
- 1 buổi `NEIGHBOR`: phòng trống, có người đi lại phòng bên.

### 5.2. Dữ liệu công khai (đã tải vào `data/public/`, không đưa lên Git)

| Bộ | Nội dung thật (đã kiểm tra) | Dùng để |
|---|---|---|
| **WiFall** | ESP32‑S3, esp‑csi, 52 sóng mang con (`len` 104, LLTF), ~84 mẫu/s. 928 đoạn **3 giây**: fall 464, sit 116, stand 114, walk 118, jump 116 (~46 phút). Lệch người: ID2 chiếm 640/928 đoạn | Viết trước bộ phân loại động tác/ngã khi chưa có firmware; làm benchmark công khai trong báo cáo; thử pretrain |
| **WiCount** | Cùng cấu hình. 15 file × 60 s: 0 người 1, 1 người 7, 2 người 6, 3 người 1 (~15 phút) | **Chỉ để thử code đếm người** – quá ít để train hoặc báo cáo |

Lưu ý: WiFall không có phòng trống, ngồi yên, nằm xuống, cúi nhặt – vẫn phải tự thu. Script `process1.py` đi kèm
ghép sai cặp số phức (`x[2i]` với `x[2i-1]`), **không dùng lại**.

### 5.3. Mô phỏng

- **`laptop/mo_phong.py`** + giao diện `mo_phong_ui.py` (mô phỏng 3D, đặc tả v0.3): đúng bố trí 1 TX + 2 RX ở góc phòng, đủ động tác, té ngã,
  nhịp thở, khách vào / ra. Dùng để viết trước toàn bộ phần xử lý khi chưa có board. Không đưa vào kết quả.
  Tham số phần cứng (nhiễu, AGC, mức biên độ) đã hiệu chỉnh theo WiFall (`laptop/doi_chieu_wifall.py`); khi có dữ liệu
  thật của nhóm thì hiệu chỉnh lại.

## 6. Đánh giá

| Phần | Chỉ số | Ghi chú |
|---|---|---|
| Có người | Accuracy, F1; tách Trống / Hoạt động / Yên | Chia train/test **theo buổi thu**; so với baseline ngưỡng phương sai |
| Đếm người | Ma trận nhầm lẫn 1/2/3 | Tách **lúc có chuyển động** và **lúc giữ số** |
| Động tác | F1 từng lớp | Thêm kết quả trên WiFall làm benchmark |
| Ngã | Độ nhạy, **số báo động giả mỗi giờ**, độ trễ cảnh báo | |
| Nhịp thở | Sai số (nhịp/phút) so với máy đếm nhịp | Chỉ khi 1 người, yên |
| Cả hệ thống | Báo động giả khi `NEIGHBOR`; so **1 RX với 2 RX** | Cùng dữ liệu, không phải thu thêm |

## 7. Phạm vi

| Mức | Nội dung |
|---|---|
| **Chính** | Có người; đếm 1/2/3; chế độ 1 người: đi lại / yên, **ngã có xác nhận**, **nhịp thở khi yên**, **bất động quá lâu** |
| **Chính, mức nhẹ** | Ngồi xuống, đứng dậy, nằm xuống, cúi nhặt (đằng nào cũng phải thu làm dữ liệu dễ nhầm với ngã); tư thế suy ra từ động tác cuối |
| **Cắt** | Phân khu / vị trí; động tác, ngã, nhịp thở khi ≥ 2 người |

## 8. Lộ trình

| Thời gian | Việc |
|---|---|
| 23–29/11 | Firmware TX/RX từ esp‑csi (ESP‑NOW, dòng `CSI` theo đặc tả v0.3); **1 TX + 1 RX chạy thông**; buổi kiểm thử phần cứng cuối tuần |
| 23–29/11 | `nhan.py`, `logger.py` theo v0.3 (nhiều RX, nhãn động tác, `R`); đọc WiFall/WiCount; thử bộ phân loại động tác trên WiFall |
| 30/11–06/12 | Thêm RX2; `features.py` v0.3 (window 6 s và window động tác 3 s); thu các buổi 1 người |
| 07–13/12 | Thu buổi 2–3 người; train tầng 0, đếm người, động tác/ngã; nhịp thở |
| 14–20/12 | Dashboard theo chế độ (1 người / nhiều người, cảnh báo ngã, nhịp thở); đánh giá; thu bổ sung nếu thiếu |
| 21–26/12 | Báo cáo, slide, chạy thử demo |

Firmware chạy thông (tuần đầu) chặn mọi việc phía sau; phần laptop làm song song bằng `logger.py --simulate` và WiFall.

**Tiến độ 23/11:** phần laptop đã theo đặc tả v0.3 (`nhan.py`, `logger.py`, `kiem_tra_buoi_thu.py`, `features.py`,
`train.py` 4 mục tiêu, dashboard nhiều RX), có mô phỏng 3D + giao diện, thuật toán nhịp thở `nhip_tho.py`. Luồng
mô phỏng → đặc trưng → train → dashboard chạy thông. Trên mô phỏng: có người ~96 %, mức hoạt động ~87 %, đếm người
~72 % (2–3 người hay bị đoán thành 1), động tác / ngã còn yếu (bắt được ~30 % cú ngã) → việc tiếp theo của tầng 1, 2a.

## 9. Rủi ro

| Rủi ro | Cách xử lý |
|---|---|
| Firmware trễ | Dựa sát ví dụ esp‑csi; phần laptop làm trước trên dữ liệu giả và WiFall |
| Nhiều RX trục trặc (USB, mất dòng, `rx_seq` không như mong đợi) | Làm theo bậc, quay về 1 RX; hub USB có nguồn, cáp tốt |
| Thu dữ liệu ngã gây chấn thương | Chỉ ngã có kiểm soát trên nệm dày |
| Nhầm ngã với ngồi phịch, nằm xuống nhanh, cúi nhặt | Thu riêng các động tác này; bước xác nhận 10 s (không đứng dậy / đi lại) |
| Đếm sai khi mọi người ngồi yên | Giữ số khi phòng yên; công tắc "Chế độ có khách"; báo cáo riêng hai trường hợp |
| Nhịp thở quá yếu | Người ngồi/nằm trong khu demo gần đường truyền; chọn RX có dải thở mạnh nhất |
| Mô hình kém khi đổi chỗ | Thu và demo tại cùng một khu; chia train/test theo buổi |

## 10. Tài liệu nền (cần tra lại trước khi trích dẫn)

- Natarajan et al., IEEE TIM 2023 – phát hiện người bằng RSSI/CSI và học máy trên ESP32 (bài báo 2, nền của tầng 0)
- Oliveira et al., IEEE Access 2019 – phát hiện thiết bị qua Probe Request, Sherlock (bài báo 1, nhánh thiết bị)
- Zhao et al., KNN‑MMD (arXiv 2412.04783) – bộ WiFall, ESP32‑S3, chuyển miền với ít mẫu
- Zhao et al., CSI‑BERT2 (arXiv 2412.06861, IEEE TMC 2025) – bộ WiCount, đếm 0–3 người
- Amritha et al., arXiv 2611.15532 (2026) – phát hiện ngã bằng ESP32, thử nghiệm nhỏ
- COVID‑Beat (JCDE 2022); Applied Sciences 14(15):6458 (2024) – đo nhịp thở bằng CSI của ESP32
- WiFall, RT‑Fall, FallDeFi – phát hiện ngã bằng Wi‑Fi CSI (Intel 5300)
- Espressif esp‑csi – firmware mẫu `csi_send` / `csi_recv`
