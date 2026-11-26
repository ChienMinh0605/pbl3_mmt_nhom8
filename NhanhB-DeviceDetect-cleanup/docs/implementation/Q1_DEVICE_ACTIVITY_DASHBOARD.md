# Dashboard Q1 · Device Activity Monitoring

Dashboard tập trung vào hoạt động mạng của thiết bị Wi‑Fi đã đăng ký. Giao diện đã bỏ bảng và biểu đồ Q2/Q3, bộ lọc CSI, nút nạp JSON/Batch CSI và thông báo kết nối CSI Receiver. Trình duyệt chỉ gọi API phục vụ Q1. API, thuật toán, dữ liệu đã lưu và kiểm thử Q2/Q3 vẫn dùng được ở backend. Tab Legacy/Probe vẫn truy cập được. Bookmark Dashboard cũ mở màn hình Q1.

## Bố cục

| Khu vực | Hành vi |
|---|---|
| Kết nối và chẩn đoán | Chọn LIVE, SIMULATION hoặc REPLAY. Trong LIVE, chọn USB và tốc độ UART, kết nối/ngắt, xem firmware, capture mode, heartbeat, kênh thực tế, lỗi UART và thiết bị đã đồng bộ. Gửi kênh theo runtime khi firmware hỗ trợ. |
| Quản lý thiết bị | Tìm theo tên, MAC hoặc kênh. Thêm, sửa, xóa, xem revision/trạng thái đồng bộ và gửi lại cấu hình. Chỉ đăng ký thiết bị có sự đồng ý. |
| Tổng quan | Số đăng ký, số đã đồng bộ, số theo ba trạng thái, kênh và cửa sổ. Lưu lượng trình bày theo thiết bị vì một khung có thể được quy gán cho nhiều MAC. |
| Bảng hoạt động | Thiết bị, kênh, trạng thái, frame/s, byte/s, RSSI và coverage. Chọn tên để mở số đếm, kênh/thời điểm lần thấy, giây quan sát, trạng thái đồng bộ, lý do và các bộ đếm khả dụng. |
| Timeline | Mặc định chọn tất cả. Chọn 0/1/2–4/5–16 thiết bị để có màn hình rỗng/timeline đơn/đường nhiều thiết bị/heatmap. Chọn chỉ số và khoảng 1/5/15/30 phút. Xem chi tiết qua điểm, ô hoặc phím mũi tên trên dải trạng thái. |
| Thực nghiệm và CSV | Nhập tên, chọn kịch bản và nhóm thiết bị, ghi/kết thúc phiên, xem lịch sử, replay và xuất chi tiết, tổng hợp, UART theo nhóm thực nghiệm, từng thiết bị, nhóm timeline hoặc toàn bộ. |

## Dữ liệu và giới hạn

- Bảng, timeline và CSV nhận kết quả Q1 từ backend theo cửa sổ 10 giây. Các đầu ra gồm ID, trạng thái và lý do, số frame/byte, tốc độ, RSSI cực đại của khung thu, lần thấy cuối, kênh đăng ký/kênh lần thấy, thời gian quan sát, coverage và trạng thái hợp lệ. Các trạng thái có ý nghĩa trong phạm vi phiên và kênh đang quan sát.
- Management, Data, Control, TX, RX và Block ACK lấy từ bộ đếm thực của activity_sample khi khả dụng. Các bản ghi cũ hoặc cửa sổ thiếu số đo có thể để trống. RSSI áp dụng cho khung thu tại sniffer, kể cả khung từ AP. Đầu ra hiện tại mô tả lưu lượng mạng; không cung cấp trạng thái của con người, mức sử dụng điện thoại hoặc ứng dụng.
- Mất heartbeat, sai kênh, thiếu bằng chứng binding hoặc chưa đồng bộ có thể làm kết quả thành UNKNOWN. Sau khi heartbeat hết hiệu lực, snapshot hiện tại có thể thành UNKNOWN trong khi timeline/CSV vẫn giữ kết quả từng cửa sổ đã chốt. Cửa sổ đầu khi kết nối/thay đổi cấu hình có thể cần thêm thời gian quan sát. Firmware hỗ trợ tối đa 16 MAC trên kênh hiện tại.
- Timeline hiện lưu 30 phút cửa sổ đã đóng cho phiên đang thu. Phiên ghi thực nghiệm đã kết thúc có thể đọc lại từ đĩa. Chuyển chế độ biểu đồ không tác động đến thu thập; khoảng thiếu hoặc UNKNOWN xuất hiện dưới dạng khoảng trống ở đường số. Tổng hợp CSV tính trên toàn bộ phiên đã kết thúc.
- Ba file là `q1_activity_detail.csv`, `q1_experiment_summary.csv`, `q1_raw_capture.csv`. Bản ghi SIMULATION cũ do công cụ kết hợp tạo có thể chỉ có chi tiết và tổng hợp. Một số cờ chẩn đoán firmware cũ cũng có thể thiếu. [Định nghĩa cột và công thức](../OUTPUT_SPECIFICATION.md#7-kiến-trúc-và-csv)
- Nút mô phỏng Q1 tạo phiên 20 giây tách biệt và hoạt động với backend Q1. Kịch bản do người dùng chọn là metadata thực nghiệm; fixture mô phỏng có một cửa sổ tạo lưu lượng và một cửa sổ yên lặng. Bộ kịch bản UART chi tiết có sẵn qua `scripts.simulate_hardware`.

## Các file thay đổi trong lượt này

| File | Nội dung |
|---|---|
| `frontend/index.html`, `frontend/src/Dashboard.tsx` | Tên màn hình và điều hướng. |
| `frontend/src/device-csi/DeviceCsiPanel.tsx`, `frontend/src/device-csi/device-csi.css` | Bố cục Q1, chẩn đoán, tìm registry, tổng quan, bảng và khối chi tiết. |
| `frontend/src/device-csi/DeviceActivityTimeline.tsx` | Timeline tự đổi bố cục và truy vấn lịch sử nhóm. |
| `frontend/src/device-csi/DeviceCsiExperiments.tsx` | Thực nghiệm Q1, lịch sử, replay và lựa chọn CSV. |
| `backend/app/api/device_activity.py`, `backend/app/api/device_csi_experiments.py` | Tổng quan/lịch sử, metadata thực nghiệm, dữ liệu mô phỏng Q1 và ba kiểu CSV. |
| `research/device_activity.py`, `research/collector.py`, `research/activity_records.py` | Bộ đếm tùy chọn, metadata UART, danh mục thiết bị trong capture và đọc lại qua monitor. |
| `tests/dashboard_browser.mjs`, `tests/test_registered_device_monitor.py`, `tests/test_runtime_registry.py` | Kiểm thử giao diện Q1, đối chiếu export và danh mục thiết bị thay đổi tại runtime. |
| `docs/OUTPUT_SPECIFICATION.md`, tài liệu này | Phạm vi và nghiệm thu Q1. |

## Chạy Dashboard

Từ thư mục repository.

```bash
npm --prefix frontend run build
bash run.sh
```

Mở URL in trên Terminal, mặc định `http://127.0.0.1:8000/#device-activity`. Nếu chưa cài môi trường, chạy `bash scripts/setup.sh`. Để kiểm tra nhanh trên cùng Dashboard, chọn **SIMULATION**, nhập tên thực nghiệm và nhấn **Chạy mô phỏng Q1**. Chọn phiên trong **Lịch sử thực nghiệm** và tải CSV. Để dừng tiến trình, nhấn Ctrl+C trong Terminal.

## Kiểm nghiệm với ESP32-C3 và nhiều thiết bị

1. Chuẩn bị ESP32-C3 chạy profile **activity** có runtime registry, cáp USB dữ liệu và nhóm thiết bị đã đồng ý. Chỉ khi board chưa có firmware phù hợp mới cần build/nạp profile một lần. Thay đường dẫn mẫu bằng cổng đã xác nhận và ngắt kết nối Dashboard trước khi nạp.

   ```bash
   bash scripts/sniffer.sh build activity
   bash scripts/sniffer.sh flash activity /dev/ttyACM0
   ```

2. Chọn **LIVE**, cổng sniffer và **Tự dò** tốc độ UART. Xác nhận có heartbeat, đúng firmware, fixed capture và kênh thực tế. Đăng ký MAC của từng thiết bị trên đúng mạng đang dùng, gồm MAC riêng tư của mạng đó nếu thiết bị sử dụng. Kiểm tra ACK qua **SYNCED**, số thiết bị đồng bộ và registry revision.
3. Thử cùng kênh với 1, 2–4 và 5–16 thiết bị. Chọn/bỏ chọn từ timeline để quan sát sự thay đổi bố cục. Duy trì mỗi điều kiện ít nhất một cửa sổ trọn vẹn sau khi đã đồng bộ. Tạo lưu lượng cho một nhóm và để các thiết bị còn lại yên. Kiểm tra xem lưu lượng nền có tiếp tục tạo frame hay không trước khi diễn giải trạng thái.
4. Để kiểm tra sai kênh, sử dụng một thiết bị đăng ký trên kênh khác hoặc thay đổi kênh thu và kiểm tra kênh firmware xác nhận. Thiết bị sai kênh hoặc chưa đồng bộ cần là UNKNOWN. Ngắt USB để kiểm tra chẩn đoán ngắt kết nối và UNKNOWN, rồi kết nối lại, kiểm tra heartbeat và ACK.
5. Ghi một phiên có tên và chọn nhóm thiết bị. Báo mốc thao tác khi đổi điều kiện, sau đó bấm **Kết thúc Q1**. Đối chiếu bảng và timeline với `q1_activity_detail.csv` cùng ID thiết bị và biên cửa sổ; dùng raw để đối chiếu heartbeat, bộ đếm và revision. Kiểm tra file tổng hợp bằng các cửa sổ hợp lệ và thử bộ lọc từng thiết bị/nhóm.

## Kết quả kiểm thử

| Kiểm thử | Kết quả | Phạm vi đã chạy |
|---|---|---|
| Backend pytest | PASS · 211 | Q1 và UART ảo, registry/ACK, đổi kênh và revision, lịch sử 30 phút, đối chiếu bảng/lịch sử/CSV, lọc CSV, cách ly nguồn, Legacy/Probe và backend Q2/Q3. Một cảnh báo legacy từ alias AnyIO trong Starlette TestClient. |
| TypeScript và Vite | PASS | `npm --prefix frontend run build`. |
| Khởi động Dashboard | PASS | Chạy `bash run.sh` với thư mục dữ liệu tạm, kiểm tra trang Dashboard và `/api/health`. |
| Chrome qua Playwright | PASS · 3 | Q1 LIVE với UART ảo và replay khi thiếu CSI, không có request CSI từ trang Q1, trạng thái khi sai kênh/quá hạn/ngắt, nguồn cách ly, timeline 0/1/2/4/5/8/16, chọn chỉ số, tooltip, refresh, ba file CSV, tìm kiếm và CRUD runtime, tab Legacy. |
| Python UART simulator | PASS · 12/12 | S01–S12 với seed 20261126, gồm hồi quy đầu ra CSI backend còn giữ. |
| ESP-IDF | PASS · 3 profile | `bash scripts/sniffer.sh build activity`, `probe` và `probe-fixed`. |
| ESP32-C3 và lưu lượng Wi‑Fi thật | NOT VERIFIED | Môi trường thực hiện không có cổng ESP32. Checklist ở trên dành cho lượt nghiệm thu thực tế. |

```bash
.venv/bin/python -m pytest -q
node --test tests/dashboard_browser.mjs
q1_sim_test=$(mktemp -d)
.venv/bin/python -m scripts.simulate_hardware --all --seed 20261126 --tick-delay .03 --exit-after-run --output "$q1_sim_test"
```

Bài kiểm thử trình duyệt dùng Chrome cục bộ với Playwright. Nếu Playwright nằm ngoài node_modules của dự án, đặt `DASHBOARD_PLAYWRIGHT_MODULE` trỏ tới `playwright/index.mjs`. Có thể dùng `DASHBOARD_TEST_CHROME` để chỉ định Chrome.
