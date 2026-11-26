# Đặc tả đầu ra nhánh thiết bị

**Phạm vi phát triển và Dashboard hiện tại là Q1 – Device Activity Monitoring.** Các mục Q2/Q3 mô tả contract backend được giữ để tích hợp ở giai đoạn sau. Màn hình Q1 chạy độc lập với CSI. [Báo cáo Dashboard Q1 và hướng dẫn nghiệm thu](implementation/Q1_DEVICE_ACTIVITY_DASHBOARD.md)

## 1. Mục tiêu nghiên cứu

1. Quan sát hoạt động mạng của thiết bị Wi‑Fi đã đăng ký và có sự đồng ý, trong khả năng thu của sniffer.
2. Đo chất lượng CSI từng RX và sử dụng bằng chứng vô tuyến hợp lệ để đánh giá độ tin cậy của dữ liệu CSI cho hệ thống phát hiện người.

Hoạt động mạng phản ánh các khung thu được, kể cả tác vụ nền. Cách diễn giải loại trừ suy luận về hiện diện, sử dụng điện thoại, danh tính hoặc ứng dụng của con người. Q3 là thông tin tham vấn và không tham gia hủy, trì hoãn hoặc chặn cảnh báo an toàn nghiêm trọng.

## 2. Quy ước chung

| Thuộc tính | Quy ước |
|---|---|
| `source` | `LIVE` cho lượt thu, `SIMULATION` cho lượt mô phỏng, `REPLAY` cho lượt phát lại. CSI API nhận request `mode=DEMO` cũ và trả lượt mới dưới `SIMULATION`. Giữ `provenance` gốc khi phát lại CSI đã lưu. |
| `session_id` | Q1 serial có ID phiên kể cả trước khi ghi. Khi bắt đầu capture, mở phiên ghi mới và dùng ID capture. Replay Q1 dùng lại ID capture với `source=REPLAY`. CSI dùng ID phiên hoặc `replay_id`; các row có thể kế thừa nguồn và phiên từ envelope. Registry, trạng thái chờ và chẩn đoán USB có thể xuất hiện trước khi có phiên/kết quả. |
| Thời gian | `window_start_us/window_end_us` là µs nguyên trên trục phiên, khoảng nửa mở `[start,end)`. Trace Q2 replay dùng `start_us/end_us` tương đương trong mảng native. Q1 lấy heartbeat Activity đầu tiên làm mốc quan sát và giữ cùng lưới 10 giây khi đổi epoch. Q2/Q3 dùng trục phiên CSI với `offset_us` của batch. UTC ISO 8601 có khi xác định được mốc tuyệt đối, như cửa sổ CSI LIVE. Marker Q1 lưu số giây từ đầu capture theo host. Khi đối chiếu marker với window Q1, cần tính độ trễ từ đầu capture đến heartbeat Activity đầu tiên trong raw capture. |
| `data_valid` | `true` khi có căn cứ kết luận trạng thái `OBSERVED_ACTIVE/NO_OBSERVED_ACTIVITY/GOOD/DEGRADED`, `false` khi `UNKNOWN`. Tính hợp lệ của quyết định và sự khả dụng của từng đại lượng tùy chọn là hai thuộc tính riêng. |
| `null` và đơn vị | Giá trị thiếu hoặc không tính được dùng `null`, CSV ghi ô trống. 0 là số đo hoặc kết quả đếm có căn cứ. Tỷ lệ độ phủ/loss ở dạng phân số 0–1. UI có thể định dạng thành %. Công suất dBm, phương sai RSSI dB², tốc độ gói/s, frame/s hoặc byte/s theo cột. |
| Cách ly | Phân biệt theo nguồn, phiên, đối tượng và trục thời gian. Q2/Q3 LIVE chỉ nhận batch `live_adapter` có RX ID. Sniffer nhúng LIVE khai báo `sniffer_source=LIVE` và `sniffer_session_id` đúng ID phiên CSI. REPLAY từ CSI tổng hợp chỉ dùng ngữ cảnh `SIMULATION`; REPLAY thật ghép qua capture hoàn tất và được liên kết rõ ràng. Nguồn/ID không thay thế bằng chứng đồng bộ. |

Bảng dùng tên logic và tên triển khai tương đương. Runtime models và JSON schema UART giữ vai trò khác nhau. Tái sử dụng kết quả nghiệp vụ khi trình bày và xuất dữ liệu. [Schema UART Activity](device-activity.schema.json) · [Schema UART Probe](packet.schema.json) · [Trace CSI](../research/csi_ingestion.py)

## 3. Q1 · Device Activity

**Input.** Registry HMAC MAC+kênh ở host, binding được đồng ý trên firmware, UART JSONL v2 `activity_sample/status/channel` và sự kiện kết nối. Thu header data/control/management có thể gán được. Khung không gán được giữ ở telemetry tổng. Một frame có thể liên quan hai thiết bị, tối đa một lần tính cho từng thiết bị. Capture lưu snapshot registry và đổi MAC thành ID trước khi ghi.

**Cửa sổ.** Một kết quả mỗi thiết bị trên lưới 10 giây không chồng lấn, độc lập với nhịp polling. Heartbeat cùng bản tin Activity kiểm chứng trạng thái, mốc và khoảng thu của firmware. Chỉ cộng khoảng firmware đã đóng và nằm trọn trong cửa sổ. Khoảng cắt biên không được nhân hoặc chia số frame; nếu có mẫu cắt biên khiến không thể kết luận im lặng, trả `UNKNOWN`. Reset kiểm tra binding khi mất kết nối, đổi boot, bộ đếm cấu hình hoặc epoch, giữ dòng lịch sử đã chốt. Khoảng mất thu được xuất UNKNOWN khi có đủ mốc để xác định các biên đã qua.

| Output logic | API hiện hành | Ý nghĩa |
|---|---|---|
| `device_id` | `devices[].id` | ID đã đăng ký, CSV dùng `device_id`. |
| `window_start`, `window_end` | `window_start_us/window_end_us` trên kết quả | Biên phiên 10 s. |
| `activity_state`, `reason` | `state/reasons` | Nhãn và danh sách mã. |
| `observed_frames`, `observed_bytes` | Cùng tên | Tổng frame gán được và tổng `sig_len` từ driver (gồm FCS theo firmware). |
| `frames_per_second`, `bytes_per_second` | `frames_per_s/bytes_per_s` | Tổng chia cho thời gian thu hợp lệ. |
| `rssi_dbm` | `rssi_max_dbm` | RSSI cực đại **của khung thu tại sniffer**. AP phát xuống điện thoại có thể đóng góp RSSI của AP. |
| `frame_types` | `frame_types.management/data/control` | Số khung của từng loại trong cửa sổ có thống kê được. Một khoảng thu đóng góp thời gian quan sát một lần dù có nhiều loại khung. |
| `tx_frames`, `rx_frames`, `block_ack_frames` | Cùng tên | Bộ đếm tùy chọn theo thiết bị lấy từ activity_sample firmware. Một khung có thể có đóng góp chiều TX/RX theo quy ước quy gán header; Block ACK có thể nằm trong Control. Đây là các thuộc tính của số khung đã đếm. |
| `last_seen`, `last_observed_channel` | `last_seen_us/last_observed_channel` | Mốc cuối khoảng có khung khớp và kênh của lần thấy đó. Kênh registry `channel` có ý nghĩa riêng. |
| `observation_time`, `channel_coverage` | `observation_time_s/channel_coverage` | Số giây quan sát hợp lệ trên kênh binding và phân số số giây đó / 10. Kết nối USB riêng lẻ không đóng góp thời gian đo. |

- `OBSERVED_ACTIVE` khi đủ điều kiện và ≥1 frame gán được.
- `NO_OBSERVED_ACTIVITY` khi đủ điều kiện, đã xác minh binding và có 0 frame. Tổng và tốc độ bằng 0, RSSI là `null`.
- `UNKNOWN` khi sai kênh, thiếu dữ liệu, lỗi/stale, gián đoạn hoặc coverage thấp. Đại lượng không có căn cứ là `null`.

Giữ ngưỡng phủ tối thiểu 8 giây trong 10 giây và heartbeat ≤2,5 s khi đánh giá hiện tại. Firmware runtime dùng registry revision đã xác nhận để kiểm tra binding cấu hình. Với firmware cũ, bằng chứng binding đến từ khung khớp trong epoch. Thiết bị chưa đồng bộ trả `UNKNOWN`. Monitor giữ kiểm tra UART, sequence, sai kênh, counter và tỷ lệ frame lỗi/không gán được. [Monitor](../research/device_activity.py) · [Collector](../research/collector.py)

## 4. Q2 · CSI Quality (backend giữ để tích hợp sau)

**Input.** `csi-quality-input-v1` cho một RX, một link tham chiếu, một epoch và một kênh. Các batch LIVE có duration chia hết cho 10 giây, offset đúng lưới 10 giây và một `receiver_id` cố định cho mỗi phiên CSI. Dùng phiên riêng cho RX khác. Trục phiên đến từ clock anchors và các khoảng quan sát RX có chứng cứ. UART emission sequence của logger nhánh người có nghĩa riêng với TX sequence. Q2 chạy khi không có sniffer và không phụ thuộc quyết định Q3.

| Output logic | API hiện hành | Ý nghĩa |
|---|---|---|
| `receiver_id` | Cùng tên | ID ổn định do adapter/phiên cung cấp. |
| `window_start`, `window_end`, `csi_channel` | `window_start_us/window_end_us/channel` | Biên phiên và kênh CSI, chu kỳ 1 hoặc 10 s. |
| `rx_packet_rate` | `csi_receive_hz` | Số mẫu chuẩn hóa từ link tham chiếu / giây RX quan sát. Sequence TX xác minh cho phép loại mẫu lặp; `rx_emitted_hz` là số dòng UART nếu telemetry có. |
| `tx_packet_rate` | Cùng tên | `expected_tx_hz` chỉ dùng khi adapter xác nhận `tx_rate_verified=true` dựa trên nguồn đo/đã xác minh. |
| `packet_loss` | `packet_loss_fraction` | RX phải phủ toàn cửa sổ. Dùng TX rate xác minh hoặc bước nhảy sequence TX liên tục **bên trong** chuỗi đo, có xử lý wrap/duplicate và loại reset mơ hồ. Đọc `loss_basis` và `loss_unavailable_reason` khi diễn giải. |
| `jitter_ms` | Cùng tên | Độ lệch chuẩn tổng thể của các khoảng đến liên tiếp hợp lệ trong đoạn RX liên tục, đổi µs → ms. Cần ít nhất hai khoảng đến hợp lệ (từ ít nhất ba gói). |
| `rssi_dbm`, `noise_floor_dbm` | `rssi_median_dbm/noise_floor_median_dbm` | Trung vị dBm từ mẫu có trường tương ứng. |
| `n_filtered` | Cùng tên | Tổng count callback bị lọc khi telemetry phủ đủ cửa sổ. Giá trị đo là count, có `n_filtered_hz` riêng nếu cần. |
| `quality_state`, `reason` | `quality/reasons` | Nhãn chất lượng và mã lý do. |

- `GOOD` khi đủ căn cứ và các chỉ số đánh giá đo được trong ngưỡng.
- `DEGRADED` khi tỷ lệ suy giảm vượt ngưỡng: RX <5 gói/s, loss >0,10, p95 khoảng đến >500 ms hoặc phương sai RSSI >25 dB² theo mặc định.
- `UNKNOWN` khi thiếu căn cứ, gồm RX ID, clock/epoch, coverage dưới 0,8, thiếu nguồn hoặc dữ liệu LIVE đã quá hạn. Trường tùy chọn chưa có vẫn là `null`. RX thực sự quan sát được 0 mẫu trong vùng đủ phủ có tốc độ 0 và kích hoạt lý do tốc độ thấp.

`n_filtered` là count theo cách lọc của RX. Các ngưỡng chất lượng là heuristic và cần hiệu chuẩn vật lý. [Timeline](../research/csi_quality.py) · [Ingestion và import csi.csv](../research/csi_ingestion.py)

## 5. Q3 · CSI Reliability (backend giữ để tích hợp sau)

**Input.** Kết quả Q2 theo từng RX và cùng cửa sổ 1 hoặc 10 giây. Bằng chứng tổng hợp trên kênh CSI có thể dùng kèm giờ thu thực tế và đồng bộ, kể cả khi thiếu quan sát thiết bị đăng ký. Q3 lấy khoảng sniffer hợp lệ trong đúng cửa sổ. Khe 10 giây Q1 không được kéo giãn để lấp các khe Q3 1 giây.

| Output logic | API hiện hành | Ý nghĩa |
|---|---|---|
| `receiver_id`, `window_start`, `window_end` | `receiver_id/window_start_us/window_end_us` | Như Q2. |
| `reliability_state` | `reliability_label` | `GOOD`, `DEGRADED`, `UNKNOWN`. |
| `channel_alignment` | Cùng tên | `MATCHED` khi có bằng chứng đúng kênh và đúng cửa sổ đồng bộ, `MISMATCH` khi phát hiện sai kênh, `UNKNOWN` khi chưa xác định được sự tương thích. |
| `channel_coverage` | Cùng tên | Phần cửa sổ có khoảng hợp lệ từ SNF cùng kênh, `null` khi thiếu chứng cứ đo hoặc clock. Lưu riêng với `rx_coverage`. |
| `evidence_source` | Cùng tên | `CSI_ONLY` khi chỉ dùng CSI, `CSI_AND_SNIFFER` khi dùng cả hai, `INSUFFICIENT_DATA` khi thiếu CSI cần thiết. |
| `reason_codes` | Cùng tên | Mã suy giảm, thiếu nguồn và fallback. |

**Ghép nguồn.** Kiểm tra provenance, session, cùng kênh và cửa sổ, coverage SNF ≥0,8, nguồn còn hiệu lực. Clock fit dùng ít nhất hai anchor tăng dần mỗi nguồn, drift ≤200 ppm, sai số gộp ≤50 ms, không ngoại suy. LIVE mặc định quá hạn sau 15 s. Khoảng SNF do adapter gắn vào batch cần bằng chứng nguồn và trục thời gian; kết nối USB Q1 không tự đồng bộ với CSI.

- `GOOD` khi có đủ CSI và không kích hoạt điều kiện suy giảm. Lưu lượng cao riêng lẻ giữ nguyên kết luận CSI.
- `DEGRADED` khi CSI đủ căn cứ và bị suy giảm theo Q2, hoặc heuristic hiện có ghi nhận mất gói CSI ≥0,05 đi cùng lưu lượng toàn kênh ≥100 frame/s và lưu lượng đăng ký ≥10 frame/s trong ngữ cảnh hợp lệ. Các số liệu kết hợp mô tả tương quan.
- `UNKNOWN` khi CSI thiếu căn cứ. Nếu chỉ thiếu SNF, kênh lệch hoặc phủ thiếu, kết quả dùng CSI hợp lệ và mã fallback.

[Engine](../research/csi_reliability.py) · [Session API](../backend/app/api/csi_reliability.py)

## 6. Phạm vi và Dashboard

| Mức | Chức năng |
|---|---|
| **CORE** | Firmware Device Activity, Device Registry, Q1, Fixed Channel, Serial Collector, Dashboard Q1, Experiment Recording, CSV Q1. |
| **SUPPORTING** | Auto Channel, Runtime Channel Configuration, Simulation cơ bản, Replay, Connection Diagnostics. Runtime Channel Configuration dùng UART hai chiều trên firmware Activity nâng cấp. Auto Channel được hoãn. |
| **OPTIONAL** | Adaptive Hopping, Advanced Simulation và đồ thị phụ được hoãn. |
| **TÍCH HỢP SAU** | Q2 CSI Quality và Q3 CSI Reliability giữ contract, API, thuật toán và kiểm thử backend. |
| **LEGACY** | Sherlock, Probe Request Device Counting, IE Fingerprinting, MAC De-randomization và benchmark liên quan. Các thuật toán Legacy độc lập với Q1/Q2/Q3. |

Dashboard **Device Activity Monitoring** bố trí sáu khu vực qua hàng KPI, ba cột và hàng thực nghiệm. [Nghiệm thu redesign](Q1_DASHBOARD_REDESIGN_VERIFICATION.md)

1. **Kết nối và chẩn đoán.** Chọn nguồn, USB, baudrate, trạng thái ESP32, firmware, capture mode, kênh thu thực tế, heartbeat, lỗi UART và số thiết bị đồng bộ. Firmware hỗ trợ runtime nhận yêu cầu thay đổi kênh.
2. **Quản lý thiết bị.** Thêm, sửa, xóa và lọc bằng tên, MAC hoặc kênh. Dashboard hiển thị đồng bộ UART và hỗ trợ gửi lại. Giới hạn firmware là 16 MAC theo cấu hình kênh thu.
3. **Tổng quan Q1.** Số thiết bị đăng ký, đồng bộ và số theo từng trạng thái, kênh và cửa sổ. Các thiết bị có thể cùng liên quan đến một khung, vì vậy Dashboard trình bày lưu lượng theo từng thiết bị.
4. **Bảng hoạt động và chi tiết.** Tìm theo tên, lọc trạng thái hoặc kênh đăng ký và sắp xếp theo từng cột. Chọn một thiết bị hoặc cửa sổ trên timeline để xem số đếm, kênh, lần thấy cuối, thời gian quan sát, coverage, nguồn, phiên, revision và lý do. ACK được đối chiếu với registry hiện tại. Phân tích Management/Data/Control gồm số lượng, tỷ lệ trên tổng frame và tốc độ. TX/RX có số lượng và tốc độ độc lập. Các tốc độ đều dùng thời gian quan sát hợp lệ; tỷ lệ loại khung thiếu khi tổng frame bằng 0.
5. **Timeline.** Mặc định chọn tất cả. Hiển thị trạng thái rỗng cho 0 thiết bị, timeline đơn cho 1, đường nhiều thiết bị cho 2–4 và heatmap cho 5–16. Chỉ số gồm frame/s, byte/s, RSSI hoặc dải trạng thái, trong 1/5/15/30 phút. Mỗi khe là một cửa sổ 10 giây. Khe thiếu hoặc `UNKNOWN` tạo khoảng trống trên đường số. Đường cũng ngắt khi thay boot, kênh hoặc registry revision. Chọn thiết bị trên timeline chỉ thay đổi hiển thị.
6. **Thực nghiệm và xuất CSV.** Đặt tên, chọn kịch bản và thiết bị, bắt đầu/kết thúc, tra lịch sử, xem kết quả tổng hợp sau khi kết thúc và xuất theo phiên hoặc nhóm thiết bị.

Route Dashboard giữ tương thích bookmark cũ. Legacy/Probe dùng điều hướng riêng. Màn hình Q1 dùng kết quả backend và chỉ định dạng đơn vị. [Dashboard Q1](../frontend/src/device-csi/DeviceCsiPanel.tsx)

## 7. Kiến trúc và CSV

- FastAPI giữ một `ProbeService` cho cổng UART. Firmware Activity chọn kênh khởi động theo NVS hoặc Kconfig mặc định rồi giữ kênh đến lệnh runtime. Backend đối soát ACK và tách epoch Q1 theo registry revision. Probe v1 dùng chung tài nguyên UART và có bộ phân tích riêng. [Giao thức UART](implementation/RUNTIME_DEVICE_REGISTRY.md)
- LIVE Q1 đi qua parser và giảm thiểu MAC. REPLAY và mô phỏng Q1 độc lập chạy `ActivityMonitor` qua bản ghi JSONL đã thay MAC bằng ID. Nguồn và ID phiên ràng buộc từng truy vấn. Bản ghi mô phỏng giữ `SIMULATION` khi xem lại. Một bản ghi UART thật có thể xem dưới nguồn `REPLAY`. Q2/Q3 giữ pipeline tương ứng ở mục 4–5.
- Lịch sử Q1 giữ tối đa 180 cửa sổ gần nhất của phiên đang thu trong bộ nhớ. Phiên ghi thực nghiệm đã kết thúc giữ JSONL và metadata (tên, kịch bản, nhóm thiết bị); có thể truy vấn cửa sổ từ bản ghi. Lịch sử nhận `source`, `session_id`, `device_id` hoặc `device_ids` lặp lại, `lookback_s` và tùy chọn `end_us`. Tải lại trang truy vấn lại phiên hiện có. Snapshot có thể hiển thị trạng thái tạm thời do heartbeat đã hết hiệu lực; lịch sử và CSV giữ kết quả đã đóng.
- `GET /api/device-csi/experiments/q1/{session_id}/export.csv` nhận `format=detail|summary|raw`. Mặc định xuất nhóm đã chọn cho thực nghiệm. Dùng `device_ids` lặp lại để chọn thiết bị hoặc `all_devices=true` để xuất tất cả thiết bị có trong bản ghi. Dùng `replay=true` khi xuất dưới nguồn `REPLAY` của lần thu UART thật. Thống kê trên Dashboard dùng `GET /api/device-csi/experiments/q1/{session_id}/summary` với cùng bộ lọc và cùng hàm tổng hợp như CSV. Phạm vi Q2/Q3 giữ endpoint và schema CSV riêng của chúng.

| File | Dòng và đơn vị |
|---|---|
| `q1_activity_detail.csv` | Một dòng từng thiết bị/cửa sổ đã chốt và các dòng metadata hoặc marker. `window_*_us` là thời gian phiên; `at` là UTC khi có mốc tuyệt đối và `elapsed_s` dành cho marker. `observation_time_s` là giây, `channel_coverage` là phân số, tốc độ theo frame/s hoặc byte/s, RSSI theo dBm. Cột `actual_channel` lấy từ cửa sổ; tốc độ theo loại và chiều dùng giây quan sát hợp lệ, tỷ lệ loại khung là phân số trên tổng frame. |
| `q1_experiment_summary.csv` | Một dòng cho từng nhóm tương thích của thiết bị, phân biệt boot, registry revision, kênh thu và kênh đăng ký trong phiên. `duration_s` là tổng độ dài các cửa sổ của nhóm, `observation_time_s` là giây quan sát hợp lệ. Tổng frame, byte và thời gian chỉ cộng các cửa sổ hợp lệ. Tốc độ trung bình lấy tổng chia thời gian quan sát hợp lệ. Cực đại và độ lệch chuẩn tổng thể lấy từ các tốc độ cửa sổ hợp lệ. RSSI đại diện là trung vị của RSSI cực đại cửa sổ đo được. Coverage là trung bình những cửa sổ có đo coverage, kể cả khi quyết định là `UNKNOWN`. `activity_ratio` = active / (active + quiet), với ô trống nếu mẫu số bằng 0. `active_fraction/quiet_fraction/unknown_fraction` lần lượt lấy số cửa sổ theo trạng thái chia cho tổng cửa sổ của nhóm. |
| `q1_raw_capture.csv` | Activity sample đã thay MAC bằng ID, heartbeat/status, sự kiện kênh, điều khiển capture và bộ đếm firmware khả dụng. Bộ lọc thiết bị áp dụng cho activity sample; giữ heartbeat và sự kiện nguồn chung để đối chiếu. Phiên mô phỏng lưu theo định dạng cũ có thể thiếu raw UART. |

Các file Q1 có `source` và `session_id`; trường thiếu để trống. Bản ghi Q1 không chứa MAC thô, payload Wi‑Fi hay trường CSI. [API Q1](../backend/app/api/device_activity.py) · [CSV](../backend/app/api/device_csi_experiments.py)

## 8. Kiểm kê tại Giai đoạn 1

Bảng dưới đây ghi các quyết định tại thời điểm audit, trước khi triển khai Giai đoạn 2. Các mục 1–7 quy định hành vi hiện hành.

`KEEP` giữ trách nhiệm đang dùng, `SIMPLIFY` giảm lặp hoặc thu hẹp trách nhiệm, `COMPLETE` bổ sung phần thiếu có tiêu chí nghiệm thu, `DEFER` hoãn phát triển, `LEGACY_ONLY` giữ cho luồng cũ, `REMOVE_CANDIDATE` chỉ xem xét sau khi xác minh phụ thuộc/tương thích. Nhóm cùng dòng có một vai trò và quyết định chung. Quyết định căn cứ vào đường chạy và test, độc lập với số dòng code.

### 8.1 Firmware, backend, collector và công cụ

| File/Module | Chức năng | Output phục vụ | Bằng chứng sử dụng | Quyết định |
|---|---|---|---|---|
| [`main.c`](../firmware/sniffer/main/main.c), `sniffer_wire.h`, `firmware/common/common.h` | Khởi tạo UART/radio theo profile, emit envelope và telemetry | Q1, Fixed Channel | `app_main` gọi `esp_wifi_set_channel` và `activity_capture_start`; nhánh v1 dùng chung emit | KEEP |
| [`activity_capture.c`](../firmware/sniffer/main/activity_capture.c)/`.h`, [`activity_frame.c`](../firmware/sniffer/main/activity_frame.c)/`.h` | Callback, gán TA/RA và phân loại khung, accumulator, status | Q1; khoảng SNF cho Q3 | Build profile Activity; `test_native_80211_header_parser` xác nhận parser C | KEEP |
| Firmware CMake, `idf_component.yml`, `Kconfig.projbuild`, `sdkconfig.defaults/activity` | Build profile và cấu hình radio/registry | Q1, build | CI build ba profile; Activity dùng `CONFIG_DEVICE_ACTIVITY_CHANNEL` | KEEP |
| `sdkconfig.fixed`, nhánh `PROBE_BASELINE` trong `main.c` | Probe cố định hoặc hopping v1 | Legacy | CMake/Kconfig và CI vẫn build, v1 API kết nối được | LEGACY_ONLY |
| [`backend/app/main.py`](../backend/app/main.py) | Entrypoint, lifespan, routers, serve static, ports/health | Q1–Q3, vận hành | `scripts.serve`, FastAPI TestClient; health/title còn mô tả `probe-only`/Sherlock | SIMPLIFY |
| [`research/collector.py`](../research/collector.py) · `ProbeService` | Vòng serial, dispatch protocol, reset nguồn, record/replay | Q1, vận hành | `lifespan`, cả hai router, PTY test; legacy state được khởi tạo cùng collector | SIMPLIFY |
| [`backend/app/device_activity_protocol.py`](../backend/app/device_activity_protocol.py) · `Wire/Sample/RegisteredSample/UnattributedSample/FixedChannel/Status/Channel` | Định nghĩa và parse UART v2 | Q1, Q3 input | Collector, capture loader và test parser/schema parity | KEEP |
| [`backend/app/protocol.py`](../backend/app/protocol.py) · `Wire/Probe/Status/Channel` | Parse Probe UART v1 | Legacy | Collector dispatch và `test_api_protocol.py`. Q1 đang dùng chung `mac_valid` và lựa chọn baud hạ tầng. Giữ chức năng chung có caller, Q1 không dùng kết quả thuật toán v1 | LEGACY_ONLY |
| [`research/device_activity.py`](../research/device_activity.py) · `Interval/ActivityMonitor`, binding/HMAC | Logic Q1, số đo và chứng cứ coverage | Q1, Q3 input | Collector, CSV, `replay_sniffer`, test monitor; thiếu output tổng/mốc/phân số | COMPLETE |
| [`research/activity_records.py`](../research/activity_records.py) · `DeviceSample/IgnoredSample/Control/PublicDevice/CaptureMetadata/Capture` | Giảm thiểu, lưu và đọc capture | Q1, Q3, recording | Collector, export, CSI capture replay; test không lộ MAC | KEEP |
| [`research/csi_ingestion.py`](../research/csi_ingestion.py) · `Record/ClockAnchor/Span/CsiSample/RxTelemetry/DeviceCounts/SnifferSpan/CsiTrace` | Chuẩn hóa một RX, clock, telemetry và nhập khoảng SNF | Q2/Q3 | API CSI và fixture; thiếu receiver ID và provenance từng đầu vào khi ghép | COMPLETE |
| [`research/csi_quality.py`](../research/csi_quality.py) · `QualityRules/ClockFit`, `timeline` | Quyết định chất lượng RX, tập hợp clock/coverage và dữ liệu đối chiếu | Q2, Q3 input | Hai router và CSV gọi `timeline`; `test_csi_quality.py` kiểm loss, đồng hồ và trường tùy chọn | COMPLETE |
| [`research/csi_reliability.py`](../research/csi_reliability.py) · `ReliabilityRules/CsiQualityWindow/DeviceActivityWindow/ChannelActivityWindow/SourceHealth` | Gate ngữ cảnh và quyết định độ tin cậy | Q3 | `assess_row` gọi `evidence/assess` cho API và CSV; Q3 lặp check CSI của Q2 | SIMPLIFY |
| [`research/reliability_demo.py`](../research/reliability_demo.py) | Fixture backend 20 s cho demo | Q2/Q3, simulation Q1 cần hoàn thiện | `create_session(DEMO)` và các test dùng chung trace; Q1 chưa chạy qua monitor | COMPLETE |
| [`research/reliability_evaluation.py`](../research/reliability_evaluation.py) · `Window/Session/Study` | Đánh giá offline có cutoff/metrics riêng | Kiểm thử nghiên cứu Q3 | CLI và `test_reliability_evaluation.py`; dashboard/API không gọi | KEEP |
| [`backend/app/storage.py`](../backend/app/storage.py) · `Store` | SQLite, registry, replay/batch, liên kết marker | Q1–Q3, Legacy | Các router, collector, test retry; có nơi lưu chính thống cho mỗi loại dữ liệu | KEEP |
| [`backend/app/api/private_input.py`](../backend/app/api/private_input.py) · `PrivateInputRoute` | Che nội dung từ lỗi validation | Q1–Q3, vận hành | Bốn router Device & CSI dùng chung, cần cho request có MAC/nhãn | KEEP |
| [`backend/app/api/device_activity.py`](../backend/app/api/device_activity.py) · `NameChange/Registration/Connection/Replay` | Registry, serial, Q1 state và capture/replay | Q1 | Dashboard và PTY/API test gọi trực tiếp; registry thêm/đổi tên có kiểm tra đồng ý | COMPLETE |
| [`backend/app/api/csi_quality.py`](../backend/app/api/csi_quality.py) · `QualityReplay` | Nhập trace và timeline Q2 | Q2, Q3 replay | Dashboard nhập/list replay, timeline có test API; ràng buộc provenance khi ghép nguồn cần sửa | COMPLETE |
| [`backend/app/api/csi_reliability.py`](../backend/app/api/csi_reliability.py) · `SessionRequest/LiveBatch` | Phiên CSI, ingestion và đọc Q3 | Q2/Q3 | Dashboard, export, test freshness/batch và chống trùng; thiếu đọc Q2 LIVE độc lập | COMPLETE |
| [`backend/app/api/device_csi_experiments.py`](../backend/app/api/device_csi_experiments.py) · `Marker/CsvLine` | Lưu mốc và xuất CSV từ dữ liệu phiên | Q1–Q3, recording/export | UI và test CSV cho cả ba Q; bộ chuyển row đang thiếu trường/đơn vị và có vòng replay Q1 riêng | COMPLETE |
| `backend/app/{device_activity,csi_quality,csi_reliability,probe}_api.py` | Alias Python cho đường import router trước khi reorganize | Tương thích | Entrypoint import từ `api/`. Một số model còn giữ `__module__` cũ; chưa có bằng chứng caller ngoài repo | REMOVE_CANDIDATE |
| [`backend/app/api/probe.py`](../backend/app/api/probe.py) · `Connection/Experiment/Truth/Replay/RssiFilter/Marker/DiagnosticChoice` | Điều khiển Probe, đánh giá và chẩn đoán MAC | Legacy | UI Legacy và các test API v1 dùng; connect/disconnect chung collector với Q1 | LEGACY_ONLY |
| `research/{stream,dashboard,detectors}.py` · `RecentProbeRecords/MacObservation/Stream/DashboardConfig/DashboardBuffer/ProbeConfig/Track/Sherlock/Comparison` | Bộ đếm, event, buffer và cấu hình v1 | Legacy | Collector/Probe UI và test thuật toán, API và dashboard | LEGACY_ONLY |
| `research/{ie_profile,ie_fingerprint,device_clustering,presence,in_room,cluster_counting}.py` | IE, liên kết MAC, presence/in-room và đếm thử nghiệm; gồm models và replay được liệt kê ngay dưới bảng | Legacy | CLI và tests IE/clustering/presence/in-room/evaluation; không vào module nghiệp vụ Q1–Q3 | LEGACY_ONLY |
| `research/{inspect,diagnose,evaluate,sweep,experiment,experiment_report,counting_accuracy,counting_report}.py`, `scripts/probe_fixture.py`, `configs/*.json` | Phiên, fixture, đồ thị, benchmark và preset Probe; gồm `EvaluationConfig/SherlockTiming/CountingConfig/ProbeAudit` | Legacy | Route Probe, CLI, tests evaluation; giữ cấu hình mà runtime hiện đọc | LEGACY_ONLY |
| `run.sh`, `scripts/{run.sh,serve.py,setup.sh,dev.mjs}`, package manifests, requirements, Vite/TS config, `.env.example` | Entrypoint, build, dependency, dev | Vận hành | `run.sh`/npm/CI; không tính Q | KEEP |
| `scripts/{sniffer.sh,flash.sh,package.py}` | Build/cấu hình firmware, thao tác phần cứng, gói source | Vận hành, thực nghiệm | Runbook, tài liệu build và `test_source_package.py`; không mở thêm entrypoint firmware | KEEP |
| `.github/workflows/check.yml`, `tests/`, `docs/{packet,device-activity}.schema.json` | Build/test và contract máy đọc cho UART | Kiểm thử và tương thích | CI Python/Node/ESP-IDF; schema test so với parser Pydantic | KEEP |

Các class trong nhóm nghiên cứu Legacy ở bảng trên được giữ theo cụm caller:

| File/Module | Chức năng | Output phục vụ | Bằng chứng sử dụng | Quyết định |
|---|---|---|---|---|
| `ie_profile.py` · `IEProfile`; `ie_fingerprint.py` | Phân tích IE và chữ ký | Legacy | CLI và `test_ie_fingerprint.py`, profile được clustering dùng | LEGACY_ONLY |
| `device_clustering.py` · `ClusteringConfig/AliasTrack/PairDecision/DeviceCluster` | Cấu hình, gán alias và thống kê cluster | Legacy | CLI, replay benchmark và `test_device_clustering.py` | LEGACY_ONLY |
| `presence.py` · `PresenceConfig/PresenceTrack/PresenceTracker/PresenceReplay` | Máy trạng thái quan sát theo cụm | Legacy | CLI, benchmark và `test_presence.py` | LEGACY_ONLY |
| `in_room.py` · `Settings/InRoomConfig/SignalVector/ReferenceWindow/RoomCalibration/SignalSample` | Đặc trưng tín hiệu, calibration và ước lượng thử nghiệm | Legacy | CLI, benchmark và `test_in_room.py` | LEGACY_ONLY |
| `cluster_counting.py` · `EvidenceConfig/ClusterReplay` | Replay kiểm chứng đếm theo chứng cứ | Legacy | Evaluation và test counting, không dùng trong Q1/Q2/Q3 | LEGACY_ONLY |

### 8.2 API đang đăng ký

Trong bảng, đường dẫn Device & CSI tương đối với `/api/device-csi`, Probe tương đối với `/api/probe`. Đường dẫn đầy đủ ghi riêng khi thuộc app root. Các route điều khiển và dữ liệu có caller khác nhau vẫn có thể tái dùng service.

| File/Module | Chức năng | Output phục vụ | Bằng chứng sử dụng | Quyết định |
|---|---|---|---|---|
| `GET /api/ports`, `GET /api/health` | Chọn cổng, health/capabilities | Vận hành | UI gọi ports; test API kiểm health; sửa scope/capabilities đang lệch | SIMPLIFY |
| `GET/POST /registry`, `PATCH /registry/{device_id}` | Đọc/thêm/đổi tên | Q1 | Form đăng ký, tests consent/HMAC/rename; bảng trạng thái đọc tên từ snapshot | KEEP |
| `GET /state` | Snapshot device và kết nối | Q1 | Dashboard poll 1 s, PTY/browser test | COMPLETE |
| `GET /activity/history` | History giới hạn cho biểu đồ | Q1, OPTIONAL | Dashboard poll và chart đọc; dùng chung kết quả window trước khi quyết định thu gọn polling | SIMPLIFY |
| `POST /connect`, `POST /disconnect` | Điều khiển USB Activity | Q1, vận hành | UI và PTY, dùng cùng `ProbeService` với Probe, guard hai loại phiên khác nhau | KEEP |
| `GET /captures`, `POST /captures/start`, `POST /captures/stop`, `POST /replay` | Ghi và phát lại Q1 | Q1, thực nghiệm | UI thực nghiệm, tests record/replay | KEEP |
| `GET/POST /quality/replays`, `GET /quality/replays/{replay_id}/timeline` | Danh mục, nhập trace và đọc báo cáo | Q2, input Q3 | UI chọn/import CSI; GET timeline có test; đổi điều kiện ghép mixed-provenance | COMPLETE |
| `GET/POST /reliability/sessions`, `POST /reliability/sessions/{session_id}/batches`, `POST /reliability/sessions/{session_id}/stop`, `GET /reliability/sessions/{session_id}/timeline` | Phiên, batch, dừng và đọc kết quả | Q2/Q3 | UI và tests; chia sẻ dữ liệu phiên cho Q2/Q3, tránh tạo thêm route ghi batch | COMPLETE |
| `GET/POST /experiments/{scope}/{session_id}/markers`, `GET /experiments/{scope}/{session_id}/export.csv` | Ghi chú theo phiên và xuất | Q1–Q3 | UI gọi, tests CSV/marker; giữ một route xuất cho mỗi scope qua tham số hiện có | COMPLETE |
| Probe `GET /state`, `GET /dashboard`, `GET/PUT /config`, `PUT /rssi`, `POST /connect`, `POST /disconnect` | State, cấu hình và kết nối Probe | Legacy | ProbePanel, ScopePanel, DeviceOverview và API tests | LEGACY_ONLY |
| Probe `GET /sessions`, `POST /sessions/start`, `POST /sessions/stop`, `POST /truth`, `POST /sessions/{sid}/evaluate`, `GET /replays`, `POST /replay`, `GET /sessions/{sid}/files/{kind}` | Phiên v1, nhãn, đánh giá, replay và tải file | Legacy | ProbePanel/ResearchPanel, test evaluate/replay/download | LEGACY_ONLY |
| Probe `POST /sessions/{sid}/inspect`, `GET /diagnostics`, `POST /markers`, `POST /sessions/{sid}/diagnose` | Thanh tra phiên, mốc và chẩn đoán MAC | Legacy | ResearchPanel và tests inspect/diagnose; khác marker theo scope CSI | LEGACY_ONLY |

### 8.3 Frontend

| File/Module | Chức năng | Output phục vụ | Bằng chứng sử dụng | Quyết định |
|---|---|---|---|---|
| `index.html`, `src/main.tsx`, `Dashboard.tsx`, `api.ts`, CSS chung | Mount React, điều hướng Device & CSI/Legacy và HTTP client | Q1–Q3, vận hành | Entrypoint Vite, browser test đổi tab | KEEP |
| `DeviceCsiPanel.tsx`, `device-csi.css` | Điều khiển kết nối/registry, poll state và trình bày | Q1–Q3 | Dashboard mặc định; code dựng Q1 demo và summary nguồn, thiếu khu Q2 độc lập | SIMPLIFY |
| `BarChart` và các tiết diện đồ thị trong `DeviceCsiPanel` | Biểu đồ chỉ số lặp thẻ/bảng, phát hiện gap hiển thị | Q1–Q3, OPTIONAL | Có caller trong panel và browser test; hoãn mở rộng, giảm số đồ thị trong dashboard tối thiểu | DEFER |
| `DeviceCsiExperiments.tsx` | Capture/replay Q1, import/Q2–Q3 session, marker, CSV | Q1–Q3, thực nghiệm | `DeviceCsiPanel` render trực tiếp, test có các đường API tương ứng; gom UI theo nguồn/phiên | SIMPLIFY |
| `ProbePanel.tsx`, `DeviceOverview.tsx` (`HistoryChart/ClusterHistory`), `ResearchPanel.tsx` (`CountChart`), `ScopePanel.tsx` | Dashboard Probe, đếm, thí nghiệm và ngưỡng RSSI | Legacy | `Dashboard` mở tab Legacy; `ProbePanel` gọi các component con, browser test chuyển tab | LEGACY_ONLY |

## 9. Tiêu chí nghiệm thu

| Phần | Tiêu chí |
|---|---|
| Q1 | Lưới 10 giây, mỗi frame không tính trùng, tốc độ theo giây quan sát, đúng coverage, sai kênh/thiếu dữ liệu `UNKNOWN`, mất heartbeat và reconnect, chạy độc lập khi thiếu CSI. |
| Q2 | RX rate, jitter có kỳ vọng, loss xác minh và `null` khi thiếu TX, cách ly nhiều RX, mất RX và hoạt động khi tắt sniffer. |
| Q3 | Traffic cao riêng lẻ giữ GOOD; CSI suy giảm, sai kênh/cửa sổ, phủ thấp và nguồn sai đều có lý do; sniffer mất dùng CSI-only, CSI mất trả UNKNOWN; output chỉ tham vấn. |
| Dashboard Q1/CSV | Chạy độc lập, không gọi API CSI từ trình duyệt. Kiểm tra 0, 1, 2, 4, 5, 8 và 16 thiết bị, ACK đồng bộ, đổi kênh, mất USB, bảng/timeline/CSV cùng phiên và cửa sổ, cùng đơn vị và ô trống phù hợp. Simulation, Replay và LIVE được ghi nhãn và cách ly. |
| Tích hợp | Pytest, TypeScript/Vite, trình duyệt, legacy regression và schema UART. Firmware build khi thay đổi firmware hoặc UART. Fixed Channel và RX thật xác minh riêng trên phần cứng. |

Xem kết quả và checklist hiện tại trong [báo cáo Dashboard Q1](implementation/Q1_DEVICE_ACTIVITY_DASHBOARD.md). Kết quả CSI được lưu trong [báo cáo Giai đoạn 2](STAGE_2_VERIFICATION.md).

## 10. Khác biệt với đề xuất gốc

| Đề xuất / đặc tả trước | Quyết định ở bản này |
|---|---|
| Q1 suy từ Wi‑Fi rằng điện thoại đang được dùng và có thể hoãn cảnh báo bất động 15–30 phút. Đầu ra hoạt động hai giá trị. | Ba trạng thái phản ánh khung được quan sát, im lặng có phủ hợp lệ và trường hợp chưa đủ dữ liệu, kèm số đo và lý do. Không đưa logic hoãn cảnh báo vào Q1. |
| Q2 “sạch/bị chiếm” dựa vào `STAT/n_filtered`, có ví dụ chờ sóng sạch để xác nhận sự kiện. | Q2 chấm chất lượng RX độc lập. `n_filtered`/noise floor là trường tùy điều kiện, cần xác minh trên RX thật. Q3 là thông tin đánh giá tín hiệu, không giữ/chặn đường cảnh báo an toàn. |
| Q3 “trong nhà còn ai khác”, thiết bị lạ, chọn người nhận Telegram/ntfy và chuyển tiếp. | Q3 là CSI Reliability như hướng MVP đã điều chỉnh. Chức năng đếm lạ/giải ngẫu nhiên nằm ở Legacy, định tuyến và xác nhận cảnh báo ngoài phạm vi. |
| Đề xuất demo thường đặt router và TX CSI ở hai kênh khác nhau. | Q1 và Q2 vẫn đo độc lập trong cấu hình đó. Q3 giữ CSI-only khi khác kênh. Lượt kiểm tải đồng kênh chỉ cho phép ghép khi đủ trục thời gian và coverage. |
| Đặc tả nhóm dùng `PRB`, CSV khe 1 phút với `n_confirmed/device_present`, và sniffer quét 1→13. Đề xuất chỉnh sang dòng `DEV` và `device_active/channel_busy/members_home/n_visitor_devices`. | Luồng chính dùng Activity JSONL v2 và trace CSI metadata hiện có với CSV Q1/Q2/Q3. Q1 theo 10 s, Q2/Q3 dùng 1 s hoặc 10 s cùng trục khi ghép. Fixed Channel là CORE. Các file/field Probe giữ giá trị lịch sử. |
| Kế hoạch MVP giữ tài liệu riêng cho Q1/Q2/Q3, hỗ trợ replay và adapter thử. | Sau xác nhận, contract và phạm vi tra tại tài liệu này. Hướng dẫn vận hành và báo cáo cũ là bằng chứng tham chiếu. Giữ simulation cơ bản để kiểm pipeline và tách provenance rõ ràng. |

[Đề xuất gốc nhánh thiết bị](legacy/DE_XUAT_NHANH_THIET_BI.md) · [Kế hoạch Device CSI MVP](legacy/DEVICE_CSI_MVP_PLAN.md) · [Đặc tả dữ liệu cấp nhóm](../Dac_ta_dinh_dang_du_lieu%20%282%29.md) · [Đặc tả Sherlock](../DAC_TA_DU_AN.md) · [Audit hệ thống cũ](legacy/CURRENT_SYSTEM_AUDIT.md) · [Audit tái sử dụng](legacy/REUSE_AUDIT.md) · [Audit tái cấu trúc repo](REPOSITORY_CLEANUP_AUDIT.md)
