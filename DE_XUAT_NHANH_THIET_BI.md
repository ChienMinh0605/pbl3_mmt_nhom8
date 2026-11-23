# Đề xuất nhánh thiết bị và cách ghép với nhánh người

**Trạng thái:** ý tưởng đã thống nhất ở mức đề xuất, chờ người phụ trách xem và chốt. **Đặc tả dữ liệu chưa sửa**
(mục 10 ghi những chỗ cần sửa).

## 1. Bối cảnh: nhánh người làm gì

Bài toán chung: **giám sát an toàn người ở nhà một mình**, không camera, không thiết bị đeo (chi tiết:
`KE_HOACH_NHANH_NGUOI.md`). 1 TX + 2 RX ESP32 ở một góc phòng thu CSI → laptop:

- Có người không, mấy người (tối đa 3).
- **1 người:** động tác, **té ngã** (ngã mà không đứng dậy / đi lại được trong 10 s thì cảnh báo), **nhịp thở** khi
  yên, **bất động quá lâu**.
- **2–3 người:** chỉ đếm người. Phân vân giữa 1 và 2 thì chọn 1, để không tắt nhầm phát hiện ngã.

## 2. Ý tưởng nhánh thiết bị

Nhánh người dùng CSI để thấy cử động, nhưng CSI có hai điểm yếu. Người ngồi yên đọc điện thoại trông giống hệt người
bất động. Còn các thiết bị Wi‑Fi khác chen vào kênh thì làm CSI nhiễu, gây báo ngã nhầm.

Nhánh thiết bị dùng một ESP32‑C3 làm sniffer, nghe **phần tiêu đề** các khung Wi‑Fi trên mạng 2,4 GHz của nhà: thiết
bị nào đang gửi, gửi bao nhiêu. Sniffer không đọc nội dung (đã mã hoá). Điện thoại của các thành viên trong nhà được
**đăng ký một lần** bằng địa chỉ MAC mà máy dùng trên mạng nhà. Hệ thống trả lời ba câu hỏi:

| # | Câu hỏi | Dùng để |
|---|---|---|
| Q1 | **Thiết bị trong nhà có đang được dùng không?** | Có hoạt động mạng → nhiều khả năng có người đang tỉnh → hoãn cảnh báo "bất động quá lâu" trong một khoảng giới hạn. Im lặng thì không suy ra gì |
| Q2 | **Sóng đo có sạch không?** | Kênh CSI bị thiết bị khác chiếm → đánh dấu đoạn CSI kém tin cậy, gợi ý đổi kênh |
| Q3 | **Trong nhà còn ai khác không?** | Điện thoại của thành viên khác hoặc thiết bị lạ ở gần → chọn **người nhận cảnh báo** |

**Nguyên tắc an toàn:** thông tin thiết bị chỉ giảm báo động giả cho cảnh báo nhẹ và chọn người nhận cảnh báo. Nó
**không bao giờ huỷ cảnh báo ngã**, cũng **không tự tắt chế độ giám sát 1 người**.

**Không có vai trò** "người già / người chăm sóc": không khẳng định được ai là ai, và người trẻ cũng có thể ngã, đột quỵ,
ngưng thở. Ai ở một mình trong khu theo dõi thì người đó được giám sát; mọi thành viên đã đăng ký đều có thể nhận cảnh báo.

## 3. Ghép với nhánh người

Laptop nhận dữ liệu của cả hai nhánh và xử lý mỗi tình huống qua ba bước:

1. **Tín hiệu có đáng tin không? (Q2)** Kênh đang bị chiếm thì một dao động giống cú ngã chưa đủ để kết luận. Hệ thống
   chờ tín hiệu sạch trở lại rồi mới xác nhận người có đứng dậy, đi lại hay không. Ngã thật thì người vẫn nằm đó nên vẫn
   bị phát hiện, chỉ chậm vài giây; nhiễu thì bị loại.
2. **Có thật sự nguy hiểm không? (Q1)** Nhánh người báo ngã, thở bất thường hay bất động lâu. Nếu chỉ là bất động lâu
   mà một điện thoại trong nhà đang được dùng thì hoãn cảnh báo, **tối đa 15–30 phút** (giá trị khởi đầu). Ngã và thở
   bất thường thì không bao giờ hoãn.
3. **Báo cho ai? (Q3)** Gửi tin nhắn qua app. Trong nhà còn thành viên khác thì nhắn cho họ trước; họ bấm
   "Tôi đã xử lý" thì dừng. Không ai xác nhận sau N giây, hoặc người đó đang ở nhà một mình, thì nhắn ngay cho người
   thân ở xa.

Ví dụ:
- Một người ngồi yên lướt điện thoại suốt một giờ. CSI thấy bất động, nhưng điện thoại đang hoạt động → không báo.
- Một máy khác tải dữ liệu cùng kênh làm sóng dao động giống cú ngã. Kênh bị đánh dấu nhiễu, sau đó người vẫn đi lại
  bình thường → không báo.
- Một người ngã khi người nhà đang ở phòng bên. Điện thoại người nhà nhận tin ngay; không ai xác nhận thì tin được gửi
  tiếp cho người thân ở xa.

**Nhánh người quyết định có nguy hiểm hay không; nhánh thiết bị giúp quyết định chắc hơn và báo đúng người.**

## 4. Cách làm từng câu hỏi

### Q1 – Thiết bị có đang được dùng

- **Đăng ký:** Android 10+ và iOS 14+ dùng MAC ngẫu nhiên **cố định riêng cho từng mạng** khi đã kết nối. Kết nối điện
  thoại vào mạng demo một lần, lấy MAC ở Cài đặt → Wi‑Fi → chi tiết mạng (hoặc danh sách máy trên router), ghi vào file
  cấu hình kèm tài khoản nhận tin của người đó (ví dụ Telegram).
  - Mạng demo dùng **WPA2/WPA3** (iOS mặc định "Cố định" với mạng có mật khẩu; mạng mở thì "Xoay vòng" 2 tuần/lần).
  - Đổi tên / mật khẩu mạng hoặc đặt lại cài đặt mạng trên điện thoại có thể ra MAC mới → đăng ký lại.
- **Nghe:** sniffer ngồi cố định trên **kênh của router**, chế độ promiscuous, lọc khung data + control. Đếm số khung mỗi
  giây có địa chỉ gửi/nhận trùng MAC đã đăng ký.
- **Giới hạn đã tra (ESP-IDF):** khung **MIMO** (nhiều luồng, router → điện thoại hay dùng) chỉ cho **độ dài, không có
  MAC**. Bù lại bằng **Block Ack** (khung control điện thoại gửi lại sau mỗi loạt khung nhận được, có địa chỉ máy gửi).
  Cách này là suy luận từ chuẩn 802.11, **chưa thử trên ESP32** → kiểm tra sớm (mục 9).
- **Đầu ra:** mỗi khe 10 s, mỗi thiết bị: có hoạt động / không. **Chỉ dừng ở mức này**, không phân biệt lướt web với
  xem video. TV, loa thông minh không tính (phát được khi không có ai xem).

### Q2 – Sóng đo có sạch không

- **Không cần sniffer.** Firmware RX (sửa từ `csi_recv` của esp-csi) bật promiscuous rồi mới lọc MAC của TX trong callback
  CSI (đã xem mã ví dụ). Số khung bị lọc là khung của thiết bị khác trên kênh CSI → trường `n_filtered` trong dòng
  `STAT` (đặc tả mục 3.4, **đã có sẵn**). Thêm `noise_floor` và tốc độ gói nhận được.
- Khung 802.11b không có CSI nên không được đếm; chấp nhận.
- **Đầu ra:** mỗi giây: kênh sạch / bị chiếm. Đoạn bị chiếm → cột cờ trong file đặc trưng, nhánh người dùng ở bước 1.
- Gợi ý đổi kênh chỉ là thông báo: đổi kênh làm CSI nền thay đổi, mô hình train ở kênh cũ có thể kém đi.

### Q3 – Trong nhà còn ai khác không

- **Thành viên khác:** thiết bị đã đăng ký có khung trong vài phút gần nhất → đang ở nhà.
- **Thiết bị lạ (nếu kịp):** probe request của thiết bị chưa đăng ký. Điện thoại dò mạng trên mọi kênh nên sniffer
  đứng yên trên kênh router vẫn bắt được. MAC băm trước khi ghi (đặc tả mục 4.3), lọc RSSI để bỏ hàng xóm, máy trạng
  thái Sherlock (bài báo 1) để xác nhận đến / đi. **Chỉ là bằng chứng phụ**: không đổi chế độ 1 người / nhiều người,
  không gửi tin được cho thiết bị lạ.

## 5. Gửi cảnh báo

| Cách | Ưu | Nhược |
|---|---|---|
| **Telegram bot** (đề xuất) | Miễn phí, vài dòng Python, tin nhắn có nút bấm (inline keyboard) để xác nhận | Cần Internet, người nhận cài Telegram |
| ntfy (nếu kịp) | Có thể chạy ngay trên laptop trong mạng nhà, **không cần Internet** | Nút bấm trên app iOS có thể chưa đủ tính năng – cần thử |

Luồng: cảnh báo → nhắn thành viên đang ở nhà → chờ N giây → chưa ai bấm "Tôi đã xử lý" → nhắn người thân ở xa.
Ghi lại thời điểm gửi và thời điểm xác nhận để đo độ trễ.

## 6. Phần cứng và mạng cho demo

- 1 ESP32‑C3 làm sniffer (SNF), cắm USB vào laptop cạnh RX1, RX2 (hub USB có nguồn).
- **Router hoặc hotspot riêng**, chỉ bật **2,4 GHz, chế độ b/g/n**, kênh cố định (tắt chọn kênh tự động), WPA2.
  Lý do: ESP32‑C3 và ESP32‑S3 cùng chỉ hỗ trợ 2,4 GHz, 802.11 b/g/n; không nghe được 5 GHz, không giải mã được khung
  Wi‑Fi 6. Đổi sang S3 không giúp gì; chỉ dòng C6 (Wi‑Fi 6) / C5 (thêm 5 GHz) mới khác, nhóm chưa có.
- TX ESP‑NOW của nhánh người phát trên kênh **khác** kênh router (chọn trong 1, 6, 11), băng thông **20 MHz**.
  Lưu ý: `csi_recv` / `csi_send` bản mới của esp-csi mặc định HT40 kênh 11 – chiếm 2 kênh, dễ đè lên router, và khác
  đặc tả v0.3 (LLTF, 20 MHz, `len` 104 như WiFall).

## 7. Riêng tư

- Chỉ theo dõi thiết bị **đã đăng ký** (chủ máy đồng ý). Chỉ lưu số tổng hợp (số khung mỗi khe), không lưu nội dung.
- MAC của thiết bị lạ băm trước khi ghi xuống đĩa, không lưu MAC thật (đã có trong đặc tả mục 4.3).
- MAC đã đăng ký cũng có thể lưu dạng băm cùng `salt` rồi so theo mã băm.

## 8. Đánh giá

Chạy **cùng một bộ dữ liệu** với hai cấu hình: chỉ nhánh người, và nhánh người + nhánh thiết bị. So sánh:
- Số báo động giả mỗi giờ (ngã, bất động lâu).
- Số cú ngã bắt được – **không được giảm**.
- Độ trễ cảnh báo (kể cả độ trễ do chờ kênh sạch) và độ trễ đến lúc có người xác nhận.

Riêng nhánh thiết bị: độ chính xác "có hoạt động / không" của Q1 so với ghi chép tay; `n_filtered` có tăng rõ khi tạo
nhiễu không (Q2).

**Buổi thu cần thêm** (đưa vào lịch thu của nhánh người):
- Tạo nhiễu có kiểm soát: điện thoại / laptop tải file trên cùng kênh với TX, xen kẽ có và không.
- Ngồi yên dùng điện thoại lâu, với ngưỡng "bất động lâu" rút ngắn cho demo (ví dụ 5 phút).
- Có người nhà ở phòng khác khi ngã (thử luồng gửi cảnh báo).

## 9. Phạm vi và việc kiểm tra sớm

| Mức | Nội dung |
|---|---|
| **Chính** | Q2 (độ sạch kênh từ `STAT`); Q1 mức có / không hoạt động; đăng ký thiết bị bằng tay; gửi cảnh báo qua Telegram có xác nhận và chuyển tiếp |
| **Nếu kịp** | Q3 với thiết bị lạ (probe + lọc RSSI + Sherlock); đăng ký tự động trên dashboard; ntfy chạy trong mạng nội bộ |
| **Không làm** | Đọc nội dung; phân biệt lướt / xem video; 5 GHz, Wi‑Fi 6; định danh khách; vai trò người dùng |

**Kiểm tra ở buổi kiểm thử phần cứng đầu tiên** (rủi ro lớn nhất nằm ở đây):
1. Sniffer có thấy khung của điện thoại trên hotspot không; số khung / giây khi đang lướt so với khi khoá màn hình.
2. Block Ack có bắt được và có đúng MAC điện thoại ở địa chỉ gửi không.
3. `n_filtered` của RX có tăng rõ khi một máy khác tải dữ liệu trên cùng kênh không.
4. MAC của điện thoại (Android và iPhone) có giữ nguyên sau khi tắt / bật Wi‑Fi, khởi động lại không.

## 10. Cần sửa trong đặc tả khi chốt (chưa sửa)

- **Mục 3.3:** sniffer không quét kênh 1→13 nữa mà đứng trên kênh router. Thêm loại dòng tổng hợp mỗi giây cho khung
  data / control, ví dụ (đề xuất):
  `DEV,<t_us>,<mac>,<n_frames>,<n_bytes>,<rssi_max>,<channel>` – một dòng cho mỗi MAC có khung trong giây đó;
  khung MIMO không có MAC gộp vào `mac` = `-`. Laptop băm MAC trước khi ghi như `PRB`.
- **Mục 6:** file đầu ra theo khe 10 s: `device_active` (mỗi thiết bị đã đăng ký), `channel_busy`,
  `members_home`, `n_visitor_devices`.
- **Mục 7:** bỏ "Sniffer quét kênh 1→13"; thêm kênh router, kênh TX, độ dài khe.

## 11. Tài liệu tham khảo chính

**Ý tưởng – suy ra hoạt động từ lưu lượng mạng**
- Mahmood, Huang (NYU), *Your Router as Fitbit* (IEEE BSN 2024): theo dõi lưu lượng (đã mã hoá) trên mạng nhà của người
  già để suy ra giờ ngủ / thức, thời gian dùng màn hình, có mặt hay vắng nhà – nền cho Q1.
  https://mlab.cyber.nyu.edu/static/ieee-bsn-24.pdf
- *Experience Paper: Scaling WiFi Sensing to Millions of Commodity Devices for Ubiquitous Home Monitoring*,
  arXiv 2506.04322 (2025): kinh nghiệm triển khai Wi‑Fi sensing trong nhà thật ở quy mô lớn. https://arxiv.org/abs/2506.04322

**Phần cứng ESP32 
- ESP-IDF, *Wi‑Fi Modes – Sniffer mode* (ESP32‑C3): khung nào dump được, khung MIMO chỉ có độ dài.
  https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32c3/api-guides/wifi-driver/wifi-modes.html
- ESP-IDF, *Wi‑Fi Vendor Features – CSI* (ESP32‑S3): cấu trúc CSI, khuyên bật promiscuous để nhận thêm CSI.
  https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32s3/api-guides/wifi-driver/wifi-vendor-features.html
- Espressif **esp-csi**, ví dụ `csi_recv` (lọc MAC trong callback, cấu hình mặc định HT40):
  https://github.com/espressif/esp-csi/blob/master/examples/get-started/csi_recv/main/app_main.c

**MAC ngẫu nhiên và đăng ký thiết bị**
- Android, *MAC randomization behavior*: https://source.android.com/docs/core/connect/wifi-mac-randomization-behavior
- Apple, *Use private Wi‑Fi addresses on Apple devices* (Cố định / Xoay vòng ở iOS 18): https://support.apple.com/102509

**Thiết bị lạ (Q3)** – có trong `tai_lieu/`
- Oliveira et al., *Mobile Device Detection Through WiFi Probe Request Analysis*, IEEE Access 2019 (bài báo 1, máy
  trạng thái Sherlock).
- Uras et al., *MAC address de-randomization for WiFi device counting*, Computer Networks 218 (2022).

**Gửi cảnh báo**
- Telegram Bot API (tin nhắn, inline keyboard): https://core.telegram.org/bots/api
- ntfy (gửi thông báo, nút bấm, tự chạy server): https://docs.ntfy.sh/publish/
