# WiFi Device Detection — Sherlock adaptation v1.1 (PBL3)

**Một ESP32-C3 sniffer + laptop.** Dự án tập trung phát hiện và ước lượng sự
hiện diện thiết bị WiFi từ Probe Request. Không cần cặp TX/RX, không thu CSI,
không huấn luyện mô hình phát hiện người, không cần điện thoại kết nối AP của nhóm.

Phần kế thừa: máy trạng thái thời gian lấy cảm hứng từ Oliveira et al.,
*Mobile Device Detection Through WiFi Probe Request Analysis*, IEEE Access 2019,
DOI 10.1109/ACCESS.2019.2925406. Đây là **adaptation**, không tuyên bố mã gốc
hoặc kết quả của bài báo đã được tái lập trên ESP32-C3.

## Cập nhật sau rà soát hai repository

Đọc [docs/UPGRADE.md](docs/UPGRADE.md) để hợp nhất bản mới và thử lỗi Ubuntu
ngắt AP. Bản mới sửa lệch một khe AT/DT, bổ sung chẩn đoán MAC trước/sau lọc,
dấu mốc và nhật ký causal; không tự suy ra MAC mới là cùng thiết bị.
Firmware không thay đổi, không cần flash lại nếu đang dùng đúng firmware bản trước.

## 1. Mã nguồn làm được gì?

- Firmware ESP-IDF 5.5.4 cho ESP32-C3: promiscuous thụ động, lọc management
  Probe Request, fixed/hopping, queue hữu hạn, heartbeat/drop/error counters.
- Một tiến trình sở hữu serial, tự nối lại, parse JSONL và ghi timestamp laptop.
- Sherlock (AT/WT/DT) làm thuật toán chính; unique-MAC và timeout làm đối chứng.
- Dashboard tiếng Việt: ba số đếm, trạng thái nguồn, bảng trạng thái MAC, thu phiên,
  ghi nhãn số thiết bị thật, replay, cấu hình và đánh giá.
- Báo cáo MAE/bias/tỷ lệ đúng/PCC/MRE, coverage, độ trễ chạm mức đếm mới.
- Heatmap Probe theo MAC/khe, bảng khe CSV và thống kê khoảng gián đoạn quan sát.
- Quét tham số trên development, đánh giá một nhóm phiên test độc lập.

Kết quả trực tiếp là **số nguồn MAC đã xác nhận**, được đối chiếu với số thiết
bị thật để đánh giá khả năng ước lượng. Không coi đó là số thiết bị hoặc số người
chính xác. Một thiết bị có thể đổi MAC; hệ thống không ghép các MAC đó.

## 2. Chạy trước khi có board

### Dashboard kiểm thử phòng học

Màn hình mặc định gồm ba bước: bộ lọc phòng, chọn USB/demo, và ghi phiên.
Dashboard nghiên cứu cũ nằm trong **Mở công cụ nâng cao**; vẫn có chẩn đoán MAC,
replay phiên cũ, đồ thị, cấu hình chi tiết và xuất heatmap.

1. Trong **Tổng quan → Phạm vi quan sát**, bật lọc RSSI, chọn ngưỡng
   (−65 dBm là điểm bắt đầu để thử), rồi **Áp dụng bộ lọc**. Có thể đổi ngưỡng
   khi USB đang kết nối; sniffer tiếp tục chạy và máy trạng thái xác nhận lại
   nguồn theo ngưỡng mới. Biểu đồ xem trước dùng RSSI gần nhất của tối đa 50 MAC
   trong 60 giây, gồm cả nguồn bị lọc; bộ đếm cho biết gói được chấp nhận và gói
   bị loại do RSSI. Nếu đang ghi phiên, chọn **Lưu phiên hiện tại và tiếp tục
   phiên mới** trước khi áp dụng: phiên cũ giữ cấu hình cũ, phiên mới giữ nhãn
   thiết bị và thông tin phòng. Phần này cũng có trong **Cấu hình thu**.
2. Trong **Thời gian xác nhận và cấu hình**, có thể chọn **Thử nhanh: 15s,
   2/2/2** cho buổi thử ban đầu, hoặc giữ cấu hình tham chiếu. Cần đủ khe có
   Probe; không hứa xác nhận sau đúng 30 giây khi điện thoại phát thưa.
3. Chọn USB và kết nối, nhập số thiết bị thật/mô tả máy, bấm **Bắt đầu ghi**.
   Khi thêm/bớt máy, sửa số và bấm **Ghi số mới**. Ô chênh lệch dùng nhãn đã
   ghi gần nhất, không dùng số đang nhập chưa ghi.
4. **Kết thúc & lưu**, rồi **Xem kết quả** để tải báo cáo JSON hoặc timeline CSV.

Để thử không có board, bấm **Chạy demo nhanh**. Nút này lưu khe 5 giây,
AT/WT/DT=2/2/2 và tắt lọc RSSI, rồi phát fixture mô phỏng 10×. Sau demo,
ngắt nguồn và chọn lại thời gian/bộ lọc mong muốn trước khi thu thật.

RSSI không giới hạn chính xác trong một phòng, không quy đổi trực tiếp thành
mét. Thử cùng một máy ở gần board, cuối phòng, ngoài cửa và phòng bên; giữ
trạng thái WiFi/màn hình nhất quán, ghi nhãn theo ranh giới phòng thực tế.
So sánh đếm dư ngoài phòng và bỏ sót trong phòng trước khi chọn ngưỡng. Với
phòng có nhiều nguồn nền hoặc tín hiệu chồng lấn, một sniffer có thể không
tách được vùng bằng RSSI. Bộ lọc áp dụng cho cả ba phương pháp và lưu trong
cấu hình mỗi phiên; không lọc mất raw đã thu.

Ubuntu/Linux, **Python 3.12**, **Node.js >=22**. Giải nén ZIP vào Downloads:

```bash
cd ~/Downloads/wifi-device-sherlock
bash scripts/setup.sh
bash scripts/run.sh
```

Mở **http://127.0.0.1:8000**. Lần sau chỉ cần `bash scripts/run.sh`. Script tự tìm
thư mục dự án, không phải tự activate môi trường. Ctrl+C ở Terminal để dừng.

Nếu `python3.12` không có tên đó nhưng Python 3.12 nằm ở vị trí khác:

```bash
PYTHON=/duong/dan/python3.12 bash scripts/setup.sh
```

**Demo không phần cứng:** tại Tham số nghiên cứu, bấm “Điền cấu hình demo nhanh”
rồi **Lưu cấu hình**. Chọn replay `synthetic-probe-demo`, tốc độ 10×, Phát lại.
Khe=5 giây, AT=DT=2 chỉ giúp nhìn luồng nhanh. Banner luôn ghi MÔ PHỎNG.
Kết thúc replay -> nguồn không còn hợp lệ, không phải kết luận thiết bị đã rời.

Sau khi demo, Ngắt và bấm Điền cấu hình tham chiếu -> Lưu để thử cấu hình dài.

## 3. Cắm và nạp ESP32-C3

Chỉ cắm **một board** vào laptop bằng cáp USB có truyền dữ liệu. Có thể dùng lại
board trước đây chạy TX hoặc RX: nạp firmware mới sẽ thay chương trình cũ trên
board đó. Hai board còn lại không dùng cho phạm vi hiện tại.

```bash
source ~/esp/esp-idf/export.sh
idf.py --version
cd ~/Downloads/wifi-device-sherlock
python -m serial.tools.list_ports -v
```

Cần ESP-IDF **v5.5.4**. Tìm `/dev/ttyUSB0` hoặc `/dev/ttyUSB1`, mô tả CH340 / USB
Serial. Bỏ qua ttyS*. Với cổng thực tế `/dev/ttyUSB0`:

```bash
bash scripts/flash.sh /dev/ttyUSB0
```

Script build và flash duy nhất `firmware/sniffer`. Flash baud 460800; JSON UART
baud **921600**. Board CH340 UART0 GPIO21 TX / GPIO20 RX; board USB native cần
đổi đường console theo sơ đồ board, không mặc định cổng vật lý giống nhau.

Nếu Connecting đứng lâu: giữ BOOT -> nhấn/thả RESET -> chạy lại lệnh flash ->
thả BOOT khi bắt đầu Writing. Nếu thiếu quyền:

```bash
sudo usermod -aG dialout "$USER"
```

Đăng xuất/đăng nhập lại. Không chạy backend bằng sudo. Nếu cổng biến mất, xem
`sudo dmesg | tail -40`; xử lý BRLTTY chỉ khi log cho thấy nó chiếm CH340.

Nếu muốn xem monitor sau flash:

```bash
cd firmware/sniffer
idf.py -p /dev/ttyUSB0 -b 921600 monitor
```

Thoát monitor bằng Ctrl+] **trước** khi dashboard mở cổng.

## 4. Cấu hình thu giống hướng một giao diện của bài báo

Firmware mặc định: country VN, hopping kênh **1–13**, dwell **3 giây/kênh**.
Cần dùng kênh hợp lệ tại nơi triển khai; firmware kiểm tra giới hạn theo country
policy của driver. Một vòng danh nghĩa 39 giây, chưa tính trễ chuyển kênh/output;
đây không phải thu đồng thời 13 kênh. ESP32-C3 này chỉ khảo sát WiFi 2.4 GHz.

Để kiểm tra đường thu trước, có thể tạm chọn fixed channel 6:

```bash
cd ~/Downloads/wifi-device-sherlock/firmware/sniffer
idf.py menuconfig
```

Vào **Probe research sniffer**, tắt hopping, chọn fixed channel. Khi thực nghiệm
nhảy kênh, bật lại và ghi rõ config trong metadata/ghi chú; flash sau mỗi thay đổi.
Không thay kênh qua dashboard. Dữ liệu type=channel và heartbeat có ghi kênh thực.

Tham số phần mềm tham chiếu: slot=60s, AT=6, WT=2, DT=6. `rssi_min=-127` nghĩa
không áp dụng cắt RSSI bổ sung trong dải hợp lệ của parser; RSSI threshold là mở
rộng để thí nghiệm riêng, không gọi là thành phần nguyên bản của Sherlock.

Xem quy ước khe đầu và cách đếm tại [docs/ALGORITHM.md](docs/ALGORITHM.md).

## 5. Thu phiên thực tế

1. Chạy dashboard, chọn đúng cổng, Kết nối. Đợi heartbeat hợp lệ.
2. Ghi mẫu máy/OS, màn hình, trạng thái kết nối, bố trí và số thiết bị thật ban đầu.
3. Bắt đầu phiên. Khi mang thêm/bớt thiết bị trong vùng, sửa số và bấm **Ghi thay
   đổi nhãn** ngay tại thời điểm thay đổi; thêm ghi chú thao tác nếu cần.
4. Giữ mỗi giai đoạn đủ lâu cho AT/DT. Với cấu hình phút, dùng phiên khoảng
   45–60 phút cho kịch bản nhỏ; kéo dài nếu nhiều lần thêm/bớt.
5. Kết thúc, bấm Tính kết quả. Tải report JSON, timeline CSV, heatmap và bảng khe.

Dữ liệu: `data/runtime/experiments/ID/{raw.jsonl,truth.jsonl,metadata.json}`.
SQLite tại `data/runtime/metadata.sqlite3`. Raw chứa MAC quan sát đầy đủ; UI chỉ
rút gọn. Không công khai raw có người ngoài thử nghiệm; dùng thiết bị được đồng ý.
Không lưu SSID, không giải mã payload ứng dụng, không chủ động ép điện thoại phát.

Mất heartbeat/serial -> không có số đếm hợp lệ, **không trả 0**. Khởi động lại hoặc
khoảng mất nguồn cần xác nhận lại. Ghi phần thời gian chưa quan sát được vào
coverage, không bỏ qua khi báo cáo.

## 6. Phân tích offline và quét tham số

```bash
.venv/bin/python -m research.inspect --session data/runtime/experiments/ID
.venv/bin/python -m research.evaluate --session data/runtime/experiments/ID
```

inspect xuất `inspection/summary.json`, `probe-slots.csv`, `probe-heatmap.svg`.
Đây là khoảng gián đoạn **quan sát được**, có thể do sniffer đang ở kênh khác;
không suy ra trực tiếp tần suất phát thực sự của điện thoại.

evaluate xuất `evaluation/report.json` và `timeline.csv`. MAE so với số thiết bị
thật; PCC không phải accuracy và null nếu chuỗi hằng. MRE chỉ tính nhãn >0; lúc
nhãn=0 báo MAE riêng. Độ trễ là chạm mức đếm mới, không phải nhận dạng thiết bị
cụ thể; sai lệch sẵn có có thể tạo độ trễ 0. Sự kiện không đạt ghi censored.

Tạo `configs/split.json` từ ví dụ, thay bằng ID phiên thật, không để trùng tập:

```bash
.venv/bin/python -m research.sweep --root data/runtime/experiments --split configs/split.json --output data/results
```

Grid slot/AT/WT/DT chọn theo MAE development (trọng số giây hợp lệ), test chỉ dùng
sau khi chốt. Nếu nhìn test rồi sửa, phải có test mới. Các phiên cùng một lần thu
liên tục cần nằm cùng tập; script không tự biết lịch sử này.

## 7. Kiểm thử và cấu trúc

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
```

- firmware/sniffer + firmware/common: chương trình ESP32-C3 duy nhất
- backend/app: schema, serial ownership, SQLite và FastAPI
- research: detectors, collector, inspect, evaluate, sweep
- frontend: giao diện duy nhất cho phát hiện thiết bị
- configs: probe.json đang dùng; reference.json và demo.json tham khảo
- data/synthetic-probe-demo: dữ liệu MÔ PHỎNG, không phải kết quả thật
- docs/PLAN.md: kế hoạch từng giai đoạn và điều kiện hoàn thành

API cục bộ: http://127.0.0.1:8000/docs. Không expose backend ra Internet.
Phát triển frontend: `npm run dev` ở gốc, sau setup. Server Vite dùng 5173.
Đóng các server khác đang chiếm 8000 hoặc dùng `WIFI_PORT=8001 bash scripts/run.sh`
cho bản static. Chỉ một tiến trình được mở cổng serial.

Trạng thái kiểm thử của bản phát hành: [docs/VALIDATION.md](docs/VALIDATION.md).

## Chẩn đoán khi ngắt AP

Bắt đầu phiên -> nhập MAC đầy đủ -> Tra cứu quan sát -> ngắt AP trên máy thử ->
ghi mốc ap_disconnect -> Tra cứu lại. Gói received có nhưng accepted không tăng
thì xem reason: excluded/weak_rssi/retry/no_valid_heartbeat/capacity. Không có
received mới không đủ để kết luận máy đã rời. Xem UPGRADE.md và research.diagnose.

API bổ sung: GET /api/probe/diagnostics?mac=..., POST /api/probe/markers,
POST /api/probe/sessions/{id}/diagnose. Thuật toán v2 hiển thị trong state/report.
