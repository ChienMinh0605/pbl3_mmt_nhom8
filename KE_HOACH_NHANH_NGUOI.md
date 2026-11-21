# Kế hoạch nhánh người – Giám sát an toàn bằng Wi‑Fi CSI

**Cập nhật:** 21/11/2026 · **Phụ trách:** Chiến (laptop, mô hình, dashboard, mô phỏng), Tiên (firmware #1 #2, tiền xử lý)
**Đặc tả dữ liệu đi kèm:** `Dac_ta_dinh_dang_du_lieu.md` v0.2

---

## 1. Bài toán

**Giám sát an toàn cho người ở nhà một mình** (ví dụ người cao tuổi) trong một phòng, **không camera, không thiết bị
đeo**. Hệ thống dùng một cặp ESP32‑C3 (TX #1 phát, RX #2 thu CSI) và trả lời:

| # | Câu hỏi | Phạm vi |
|---|---|---|
| 1 | Có người trong phòng không? Đang **hoạt động** hay **yên** (ngồi/nằm)? | **Chính** – kế thừa bài báo 2 |
| 2 | Có **té ngã** không? Sau ngã có **nằm bất động** quá N giây không? | **Chính** |
| 3 | Khi người yên, **nhịp thở** có bất thường không (quá nhanh, quá chậm, ngưng)? | **Mở rộng** – làm nếu kịp |

Không làm: nhận dạng ai, đếm chính xác số người bằng CSI, chẩn đoán y tế (chỉ cảnh báo dấu hiệu bất thường).

**Vì sao Wi‑Fi:** giữ riêng tư hơn camera, không cần nhớ đeo như vòng tay, phần cứng rẻ (ESP32‑C3).

## 2. Khi có nhiều người (khách, người chăm sóc)

Hệ thống **không giả định nhà chỉ có một người**, nhưng một cặp TX–RX và biên độ CSI không tách được từng người,
nên mỗi chức năng bị ảnh hưởng khác nhau:

| Chức năng | Có 2–3 người | Cách xử lý |
|---|---|---|
| Có người / hoạt động / yên | Vẫn đúng | – |
| Té ngã | Độ chính xác giảm (người khác đi lại che tín hiệu ngã) | Vẫn chạy, hạ mức cảnh báo xuống **"thông báo"** vì đã có người ở đó |
| Nhịp thở | Không đo được (nhịp thở trộn lẫn) | **Tắt**, dashboard ghi "không đo được khi có nhiều người" |

**Biết có mấy người:** dùng **nhánh thiết bị (Sherlock) của Phúc** – số thiết bị đã xác nhận tăng ⇒ có khách. Dự
phòng: công tắc **"Chế độ có khách"** trên dashboard (Sherlock cần ≥ 6 phút để xác nhận thiết bị).

| Số người | Hành vi hệ thống |
|---|---|
| 0 | Phòng trống |
| 1 | Đủ chức năng, cảnh báo **khẩn** |
| ≥ 2 | Phát hiện ngã ở mức **thông báo**, tắt đo nhịp thở |

## 3. Nhãn (đặc tả mục 4.4, định nghĩa trong `laptop/nhan.py`)

| Nhãn | Phím | Ý nghĩa | Có người | Mức hoạt động |
|---|---|---|---|---|
| `EMPTY` | E | Phòng trống | 0 | 0 trống |
| `NEIGHBOR` | N | Phòng trống, có người ở phòng bên – kiểm tra báo động giả | 0 | 0 trống |
| `ACTIVE` | A / W | Đi lại, sinh hoạt | 1 | 1 hoạt động |
| `STILL` | S | Ngồi/nằm yên, thở bình thường | 1 | 2 yên |
| `FALL` | F | Khoảnh khắc ngã (1–2 giây) | 1 | – (sự kiện) |
| `DOWN` | D | Nằm bất động sau ngã | 1 | 2 yên |
| `BREATH_ABN` | B | Yên nhưng thở bất thường | 1 | 2 yên |

**Số người** là thông tin riêng, lấy từ phím `+` / `-` (`COUNT`), không dùng nhãn `MULTI` nữa.

## 4. Kiến trúc xử lý (xếp tầng)

```
CSI 100 mẫu/s ─┬─► Tầng 1: window 6 s → 4 đặc trưng/sóng mang con → RF/GB/XGB ─► Trống / Hoạt động / Yên
               │
               ├─► Tầng 2: window 2 s, trượt 0,5 s → phát hiện "dao động mạnh rồi yên hẳn" ─► Nghi ngã
               │           xác nhận: tầng 1 báo "Yên" liên tục ≥ 10 s sau đó ─────────────► CẢNH BÁO NGÃ
               │
               └─► Tầng 3 (mở rộng, chỉ khi Yên và 1 người): window 30 s, lọc 0,1–0,6 Hz, FFT ─► nhịp thở/phút
                                                                                             thở > 25, < 8, ngưng > 15 s ─► CẢNH BÁO
Nhánh thiết bị (Phúc) ─► số thiết bị ─► 1 người / có khách ─► chọn mức cảnh báo
```

- **Tầng 1** – đúng phương pháp bài báo 2, chỉ đổi từ 2 lớp sang 3 lớp (`activity`).
- **Tầng 2** – học máy trên đặc trưng window ngắn (độ phân tán, năng lượng biến thiên, tỉ lệ trước/sau) hoặc luật
  ngưỡng làm baseline. Bước xác nhận giúp phân biệt "ngã" với "ngồi phịch xuống ghế".
- **Tầng 3** – xử lý tín hiệu, không cần học máy. Chọn các sóng mang con có năng lượng dải thở lớn nhất.

Các ngưỡng (10 s, 25/8 nhịp/phút, 15 s) là **giá trị khởi đầu**, sẽ chỉnh theo dữ liệu.

## 5. Dữ liệu

**Dữ liệu thật** (logger + phím nhãn). Mỗi buổi ≥ 30 phút (để nhánh thiết bị đánh giá được), gồm:
- `EMPTY`, `NEIGHBOR` (người đi phòng bên), `ACTIVE`, `STILL` (ngồi, nằm trên giường/sofa)
- **Ngã có kiểm soát trên nệm dày**: quỳ rồi nằm hoặc ngã nghiêng xuống nệm, bấm `F` đúng lúc ngã rồi `D`, nằm 20–60 s.
  **Không ngã mạnh, không ngã trên sàn cứng.** Mỗi buổi 10–20 lần ngã, nhiều hướng, nhiều vị trí.
- "Ngồi phịch xuống ghế", "cúi nhặt đồ", "nằm xuống giường nhanh" – các động tác **dễ nhầm với ngã** (nhãn `ACTIVE`/`STILL`)
- Có **khách**: 1–2 người đi lại trong lúc chủ nhà ngồi/ngã (bấm `+`/`-`)
- Nhịp thở (mở rộng): thở theo máy đếm nhịp trên điện thoại (12 / 30 nhịp/phút, nín thở 20 s) làm đáp án

**Dữ liệu mô phỏng Sionna RT** (`laptop/mo_phong_sionna.py`, xem `laptop/README.md`): dò tia 3D trong phòng có tường
bê tông, người là khối có tính chất điện như mô cơ thể, có hành vi đi lại / ngồi thở / **ngã** / nằm / thở nhanh /
khách / người phòng bên. Dùng để:
- thử thuật toán tầng 1–3 **trước khi có dữ liệu thật**;
- sinh **nhiều mẫu ngã** (dữ liệu thật vừa hiếm vừa nguy hiểm);
- đo độ giảm chính xác khi có khách.

Dữ liệu mô phỏng **không thay** dữ liệu thật khi báo cáo kết quả (khoảng cách mô phỏng – thực tế).

## 6. Đánh giá

| Tầng | Chỉ số | Ghi chú |
|---|---|---|
| 1 | Accuracy, F1 (macro) 3 lớp; tách riêng Empty/Active/Still | Chia train/test **theo buổi thu**; so với baseline ngưỡng phương sai |
| 2 | Độ nhạy (tỉ lệ ngã phát hiện được), **số báo động giả mỗi giờ**, độ trễ cảnh báo | Báo cáo riêng **1 người** và **có khách** |
| 3 | Sai số nhịp thở (nhịp/phút) so với máy đếm nhịp | Chỉ khi 1 người, yên |
| Cả hệ thống | Báo động giả khi `NEIGHBOR` | Người phòng bên không được gây cảnh báo |

## 7. Lộ trình và phân công

| # | Việc | Người | Trạng thái |
|---|---|---|---|
| 1 | Đặc tả dữ liệu v0.2, bộ nhãn chung `nhan.py` | Chiến | ✅ |
| 2 | Logger + phím nhãn mới, kiểm tra buổi thu, train tầng 1 (2 lớp), dashboard | Chiến | ✅ (cần thêm 3 lớp) |
| 3 | Mô phỏng Sionna RT: đi lại, ngồi thở, ngã, nằm, thở nhanh, khách, phòng bên | Chiến | ✅ |
| 4 | Firmware #1 (SoftAP), #2 (ping 100 Hz, CSI, lọc MAC) | Tiên | ⬜ |
| 5 | `features.py`: tiền xử lý, window 6 s, cột `activity`, `n_people` | Tiên | ⬜ (`dac_trung.py` là bản tạm) |
| 6 | `train.py` thêm `--target activity` (3 lớp) | Chiến | ⬜ |
| 7 | Tầng 2 phát hiện ngã; chốt định dạng window ngắn (đặc tả v0.3) | Chiến + Tiên | ⬜ |
| 8 | Ghép số thiết bị từ nhánh Phúc → "có khách"; công tắc chế độ có khách | Chiến + Phúc | ⬜ |
| 9 | Dashboard: cảnh báo ngã, mức cảnh báo theo số người | Chiến | ⬜ |
| 10 | Buổi kiểm thử phần cứng tuần đầu, rồi các buổi thu dữ liệu (mục 5) | Cả nhóm | ⬜ |
| 11 | Tầng 3 nhịp thở (mở rộng) | Tiên + Chiến | ⬜ |
| 12 | Đánh giá, báo cáo, slide | Cả nhóm | ⬜ |

Thứ tự ưu tiên: 4 → 5 → 10 chặn tiến độ của cả nhóm; 6, 7 làm song song trên dữ liệu mô phỏng.

## 8. Rủi ro

| Rủi ro | Cách xử lý |
|---|---|
| Thu dữ liệu ngã gây chấn thương | Chỉ ngã có kiểm soát trên nệm dày; bổ sung bằng mô phỏng |
| Nhầm "ngã" với ngồi phịch, nằm xuống nhanh | Thu riêng các động tác dễ nhầm; bước xác nhận "yên ≥ 10 s" |
| Có khách làm giảm độ chính xác | Hạ mức cảnh báo khi có khách; báo cáo riêng hai trường hợp |
| Nhịp thở quá yếu trên ESP32 | Để ở phần mở rộng; đặt người gần đường TX–RX |
| Mô hình kém khi đổi phòng | Thu dữ liệu tại chính phòng demo; chia train/test theo buổi |
| Sherlock xác nhận chậm (≥ 6 phút) | Công tắc "Chế độ có khách" làm dự phòng |

## 9. Tài liệu nền (cần tra lại trước khi trích dẫn)

- Natarajan et al., IEEE TIM 2023 – phát hiện người bằng RSSI/CSI và học máy (bài báo 2)
- Oliveira et al., IEEE Access 2019 – phát hiện thiết bị qua Probe Request, Sherlock (bài báo 1)
- WiFall, RT-Fall (Wang và cộng sự) – phát hiện té ngã bằng Wi‑Fi CSI
- Liu và cộng sự – theo dõi nhịp thở khi ngủ bằng Wi‑Fi CSI
- NVIDIA Sionna RT – công cụ dò tia dùng cho mô phỏng
