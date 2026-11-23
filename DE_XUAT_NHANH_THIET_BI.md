# Đề xuất nhánh thiết bị và cách ghép với nhánh người (bản nháp để bàn)

**Ngày:** 22/11/2026 · **Người soạn:** Chiến · **Trạng thái:** đề xuất, **chưa chốt** – chưa đưa vào kế hoạch hay đặc tả

---

## 0. Bối cảnh

Sau buổi báo cáo tiến độ, thầy muốn đề tài đặt trong một bài toán thực tế. Nhánh người đã chuyển sang:
**giám sát an toàn người ở một mình** bằng Wi‑Fi CSI (xem `KE_HOACH_NHANH_NGUOI.md`):

- 1 TX (ESP32‑C3) phát gói liên tục, 2 RX (ESP32‑S3) thu CSI, cắm USB vào laptop; khu demo là một góc phòng ~2,5 × 2,5 m.
- **Có 1 người:** nhận dạng động tác (đi lại, ngồi xuống, đứng dậy, nằm xuống, cúi nhặt), **phát hiện té ngã**, **đo nhịp thở** khi người yên.
- **Có 2–3 người:** chỉ đếm số người, tắt nhận dạng động tác và nhịp thở (đã có người khác bên cạnh).

Đề xuất dưới đây là để **nhánh thiết bị đóng góp trực tiếp** vào bài toán đó, thay vì chỉ đếm thiết bị riêng lẻ.

## 1. Ý chính

**CSI cho biết "có một cơ thể người ở đây". Điện thoại cho biết "đó là ai".**

CSI một mình không trả lời được ba câu hỏi rất thực tế; thông tin thiết bị trả lời được:

| Câu hỏi thực tế | CSI một mình | Có thêm thiết bị |
|---|---|---|
| Phòng trống: ông bà **đi vắng**, hay ở nhà mà **không thấy cử động**? | Không phân biệt được | Điện thoại của người ở có ở nhà không |
| Người thứ hai là **khách lạ** hay **người chăm sóc**? | Không biết | Thiết bị đã đăng ký hay thiết bị lạ |
| Mọi người đều ngồi yên – khách đã về chưa? | Phải giữ số cũ, dễ sai | Thiết bị của khách biến mất |

Ngoài ra đây là môn **Mạng máy tính**: nhánh thiết bị là chỗ đưa kiến thức mạng vào rõ nhất (khung 802.11, probe
request, MAC ngẫu nhiên, ARP/DHCP trong LAN, gửi cảnh báo qua mạng).

## 2. Hai loại thiết bị, hai cách phát hiện

Cách hệ điều hành đổi MAC quyết định cách làm:

- Khi **đã kết nối** một mạng Wi‑Fi, Android 10+ dùng MAC ngẫu nhiên **cố định cho từng mạng**; iOS 14+ mặc định cũng
  giữ MAC cố định với mạng WPA2/WPA3 (iOS 18 có thêm tuỳ chọn "xoay vòng").
- Khi **chưa kết nối** (chỉ dò mạng), điện thoại phát probe request với MAC **ngẫu nhiên, thay đổi**.

### 2a. Thiết bị đã đăng ký – người ở, người chăm sóc

- Các điện thoại này **kết nối Wi‑Fi nhà**, nên MAC trên mạng nhà cố định → **đăng ký một lần** (MAC + vai trò:
  `resident` / `caregiver`).
- Laptop phát hiện qua **mạng LAN**: quét ARP / ping theo chu kỳ (ví dụ mỗi 30 s). Không cần thêm phần cứng.
- Điện thoại khoá màn hình đôi khi không trả lời → chỉ coi là **"đi vắng" khi vắng liên tục ≥ 10 phút**
  (giá trị khởi đầu, chỉnh theo thử nghiệm).

### 2b. Thiết bị lạ – khách

- Khách thường **không** kết nối Wi‑Fi nhà → chỉ bắt được **probe request** (MAC ngẫu nhiên).
- ESP32‑C3 làm sniffer, quét kênh 1→13 (đặc tả mục 3.3). Laptop **băm MAC** trước khi ghi (đặc tả mục 4.3), bỏ các
  thiết bị đã đăng ký và board của nhóm.
- **Lọc theo RSSI** để bỏ điện thoại của hàng xóm / phòng bên (ngưỡng chỉnh ở buổi thử).
- **Máy trạng thái Sherlock** (bài báo 1, Oliveira 2019): một nguồn chỉ được tính là "đã đến" khi xuất hiện đủ lâu,
  "đã đi" khi vắng đủ lâu → ra **số thiết bị lạ đang ở gần**.
- **Nếu kịp:** gom các MAC ngẫu nhiên của cùng một điện thoại theo nội dung khung (information elements) và tốc độ
  đánh số khung – bài Uras et al. 2022 (có sẵn trong `tai_lieu/`; báo ~96% trong phòng thí nghiệm, ~75% trên xe buýt thật).

## 3. Ghép với nhánh người

### 3.1. Bảng kết hợp

| CSI (nhánh người) | Điện thoại người ở | Thiết bị khác | Kết luận | Hệ thống làm gì |
|---|---|---|---|---|
| Trống | Vắng | – | **Đi vắng** | Tắt cảnh báo bất động |
| Trống quá lâu (vd. 30 phút ban ngày) | Ở nhà | – | Ở nhà nhưng không thấy trong khu theo dõi | Cảnh báo nhẹ: "nên gọi kiểm tra" |
| Có người | Vắng | – | Có thể quên điện thoại, hoặc người lạ | Thông báo nhẹ |
| 1 người | Ở nhà | Không có | Ở một mình | **Chế độ 1 người** (ngã, nhịp thở, cảnh báo khẩn) |
| ≥ 2 người | – | Người chăm sóc đã đăng ký, hoặc thiết bị lạ | Có người bên cạnh | **Chế độ nhiều người**; ghi "người chăm sóc đang ở đây" nếu đúng |
| Yên (đang giữ số người) | – | Thiết bị lạ rời đi | Khách đã về | Giảm số người |

### 3.2. Quy tắc an toàn khi chọn chế độ

Nhầm "có khách" trong khi người già **đang ở một mình** là lỗi **nguy hiểm hơn**, vì hệ thống sẽ tắt phát hiện ngã.
Vì vậy:

- Chỉ chuyển sang **chế độ nhiều người** khi CSI đếm ≥ 2 **liên tục một khoảng thời gian**, **hoặc** có thiết bị của
  **người chăm sóc đã đăng ký**.
- Thiết bị lạ chỉ là **bằng chứng phụ** (khách có thể không mang điện thoại, hoặc là điện thoại hàng xóm), không tự
  chuyển chế độ.
- Thiết bị rời đi → quay về **chế độ 1 người ngay**.

### 3.3. Gửi cảnh báo qua mạng

Khi có ngã, ngưng thở hay bất động bất thường, laptop gửi tin tới điện thoại người chăm sóc (ví dụ Telegram bot).
Hệ thống thật nào cũng cần phần này; làm nhanh và cũng là phần mạng.

## 4. Đánh giá đề xuất

**Nhánh thiết bị:**
- Số thiết bị so với số người đếm tay: PCC, MRE (như bài báo 1; cột `people_manual` đã có ở đặc tả mục 6).
- Độ trễ phát hiện đến / đi (Sherlock cần khoảng vài phút để xác nhận).
- Độ chính xác **ở nhà / đi vắng** của thiết bị đã đăng ký.
- Số thiết bị hàng xóm bị đếm nhầm (có / không lọc RSSI).

**Phần ghép:**
- Độ chính xác chọn chế độ 1 người / nhiều người **có và không có** thông tin thiết bị – bảng cho thấy hai nhánh bổ
  trợ nhau.
- Số báo động giả trong các buổi có khách.

## 5. Phạm vi đề xuất

| Mức | Nội dung |
|---|---|
| **Chính** | Thiết bị đăng ký qua LAN (ARP/ping); probe request + lọc RSSI + Sherlock để đếm thiết bị lạ; bảng kết hợp mục 3; gửi cảnh báo |
| **Nếu kịp** | Gom MAC ngẫu nhiên theo bài Uras 2022 |
| **Không làm** | Định danh hay theo dõi khách; định vị; lưu MAC thật |

**Phần cứng và mạng cho demo:**
- 1 ESP32‑C3 làm sniffer (đã dành sẵn), cắm USB vào laptop như các RX.
- 1 mạng Wi‑Fi cho demo (router hoặc điểm phát của điện thoại) mà laptop và các điện thoại đã đăng ký cùng kết nối.
- TX của nhánh người (ESP‑NOW) nên phát trên **kênh khác** kênh của router (chọn trong 1, 6, 11) để đỡ nhiễu CSI.

**Riêng tư:** chỉ lưu MAC của thiết bị **đã đăng ký** (người dùng đồng ý). MAC của thiết bị lạ băm trước khi ghi
xuống đĩa, không lưu MAC thật (đã có trong đặc tả mục 4.3).

## 6. Đầu ra đề xuất cho file `data/device/<session_id>.csv`

Bổ sung vào đặc tả mục 6 (khe 1 phút) **nếu nhóm đồng ý** – hiện chưa sửa đặc tả:

| Cột mới | Ý nghĩa |
|---|---|
| `resident_home` | 1 nếu điện thoại người ở đang có mặt trên mạng nhà (sau trễ "đi vắng") |
| `caregiver_present` | 1 nếu có thiết bị người chăm sóc đã đăng ký |
| `n_visitor_devices` | Số thiết bị lạ ở trạng thái "đã đến" (sau lọc RSSI, Sherlock) |

Dashboard và bảng kết hợp chỉ cần ba cột này cùng kết quả CSI. Có thể cần khe ngắn hơn 1 phút (ví dụ 10 s) để kịp
chuyển chế độ – cần bàn.

## 7. Cần bàn để chốt

1. Đồng ý hướng "thiết bị = ai, CSI = có người" và bảng kết hợp mục 3 không?
2. Phát hiện thiết bị đăng ký bằng **ARP/ping trên LAN** hay để sniffer nghe khung dữ liệu trên kênh của router?
3. Ngưỡng RSSI và thông số Sherlock (AT, DT, WT) cho phòng nhỏ – có cần rút ngắn so với bài báo 1 không?
4. Khe thời gian file đầu ra: 60 s như cũ hay ngắn hơn?
5. Có làm phần gom MAC ngẫu nhiên (bài Uras) không, hay để "nếu kịp"?
6. Gửi cảnh báo bằng gì (Telegram bot, ntfy, email)?

## 8. Lưu ý

- Chưa thấy bài nào ghép đúng **CSI với probe request**; các bài tìm được làm riêng từng phần hoặc ghép CSI với RSSI.
  Đây là điểm mới của nhóm, nhưng cũng chưa có số liệu đối chiếu.
- Việc iPhone khoá màn hình ít trả lời ARP/ping là hiện tượng hay gặp, **chưa thử trên máy thật**.

## 9. Tài liệu tham khảo

- Oliveira et al., *Mobile Device Detection through WiFi Probe Request Analysis*, IEEE Access 2019 (bài báo 1, có trong `tai_lieu/`)
- Uras et al., *MAC address de-randomization for WiFi device counting*, Computer Networks 218 (2022) (có trong `tai_lieu/`)
- Android – MAC randomization behavior: https://source.android.com/docs/core/connect/wifi-mac-randomization-behavior
- Apple – Wi‑Fi privacy: https://support.apple.com/guide/security/secb9cb3140c
- IETF MADINAS – OS current practices: https://github.com/ietf-wg-madinas/draft-ietf-madinas-mac-address-randomization/blob/main/OS-current-practices.md
- Martin et al., *A Study of MAC Address Randomization in Mobile Devices and When it Fails*, PoPETs 2017: https://arxiv.org/abs/1703.02874
- *MAC Address De-Randomization Using Multi-Channel Sniffers and Two-Stage Clustering* (2024): https://arxiv.org/abs/2408.01578
- AFOROS – đếm người nơi công cộng bằng probe request: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8199860/
- *Occupancy Counting with Burst and Intermittent Signals in Smart Buildings*: https://arxiv.org/abs/1702.06423
- *RSSI-Assisted CSI-Based Passenger Counting with Multiple Wi-Fi Receivers* (2024): https://arxiv.org/abs/2410.11400
