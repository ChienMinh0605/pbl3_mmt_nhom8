# Nghiệm thu Giai đoạn 2 · Device & CSI

**Phần mềm PASS. Phần cứng RF và RX thật NOT VERIFIED.** Phạm vi được nghiệm thu trên FastAPI, UART ảo, trace chuẩn hóa, CSV và Chrome. Bản [đặc tả đầu ra](OUTPUT_SPECIFICATION.md) là chuẩn cho field, trạng thái, đơn vị và phạm vi.

## Kết quả triển khai

| Phần | Thay đổi |
|---|---|
| Q1 | Cửa sổ `[start,end)` 10 giây không chồng lấn. Chốt khoảng firmware hợp lệ chỉ trong một cửa sổ, giữ lịch sử khi chuyển cửa sổ và giữ lưới thời gian qua reconnect/đổi boot. Trả tổng frame/byte, tốc độ theo thời gian quan sát, kênh lần thấy cuối, độ phủ phân số và lý do thiếu dữ liệu. CSV Q1 dựng lại đúng cửa sổ từ cùng monitor và sự kiện nguồn. |
| Q2 | Giữ engine, đưa output `quality` vào timeline phiên CSI LIVE và khu Q2 trên Dashboard. Một phiên CSI LIVE dùng một RX, các phiên độc lập có thể chạy nhiều RX. Thêm jitter tổng thể, TX rate có điều kiện, count `n_filtered` và ID RX. Xử lý phần mất gói theo bằng chứng TX, wrap, mẫu lặp và reset mơ hồ. Bộ nhập `csi.csv` đưa dữ liệu logger vào schema hiện có với mốc thời gian và thời gian quan sát do thực nghiệm cung cấp. |
| Q3 | Dùng quyết định và mã suy giảm Q2 trên đường API, bổ sung alignment, coverage và enum evidence. CSI hợp lệ tự chạy khi context sniffer bị loại. Cảnh báo an toàn nằm ngoài hợp đồng Q3. Session và provenance được kiểm tra trước khi dùng mẫu sniffer; các report lưu cũ thiếu xác nhận liên kết cũng bị loại context khi đọc Q3. |
| Dashboard và CSV | Sáu khu vực, chẩn đoán chi tiết trong vùng mở rộng. Mô phỏng Q1 chạy bằng `ActivityMonitor`; React hiển thị state/số liệu trả về từ API. Bỏ thẻ và biểu đồ trùng lặp. Giữ một route CSV chung theo scope, tách cột giây quan sát, phân số phủ kênh và phân số phủ RX. |

### Module đã tinh gọn

- `ActivityMonitor` chốt một lần cho từng cửa sổ. Collector, replay và CSV dùng cùng dữ liệu đóng cửa sổ và cách xử lý control.
- `csi_reliability.assess` nhận kết quả Q2 từ tuyến API. Dùng chung định nghĩa ngưỡng cho caller nghiệp vụ trực tiếp. Q2 LIVE và CSV chia sẻ phép chiếu field và xử lý tuổi của cùng cửa sổ.
- `DeviceCsiPanel` bỏ dựng hàng DEMO, suy diễn state từ summary và các poll chỉ để vẽ đồ thị. Giữ các đầu mối điều khiển nguồn, kết nối, registry và phiên thực nghiệm hiện có.

### File đã sửa trong lượt này

| Nhóm | File |
|---|---|
| Backend | `backend/app/api/{device_activity,csi_quality,csi_reliability,device_csi_experiments}.py` |
| Pipeline | `research/{collector,device_activity,csi_ingestion,csi_quality,csi_reliability,reliability_demo}.py` |
| Dashboard | `frontend/src/device-csi/{DeviceCsiPanel.tsx,DeviceCsiExperiments.tsx,device-csi.css}` |
| Test và fixture | `tests/{test_registered_device_monitor,test_csi_quality,test_csi_reliability,test_device_csi_integration}.py`, `tests/dashboard_browser.mjs`, `tests/fixtures/csi_quality_synthetic.json` |
| Tài liệu | `docs/OUTPUT_SPECIFICATION.md`, `docs/STAGE_2_VERIFICATION.md` |

Các thay đổi firmware và Legacy có sẵn trong cây làm việc trước Giai đoạn 2 không thuộc danh sách trên. Giai đoạn này dùng phiên bản trong workspace để chạy regression.

### Đầu ra cuối cùng

Mỗi kết quả kế thừa `source`, `session_id` và biên thời gian từ cửa sổ hoặc phiên. `data_valid=false` biểu thị quyết định `UNKNOWN`. Các hợp đồng chi tiết nằm ở [Q1, Q2 và Q3 trong đặc tả](OUTPUT_SPECIFICATION.md).

| Kết quả | Nơi kiểm tra |
|---|---|
| Q1 | `GET /api/device-csi/state` trả các field theo thiết bị và cửa sổ. `/activity/history` chứa các cửa sổ đã đóng. Timeline CSI của phiên SIMULATION trả cửa sổ Q1 trong `activity`. |
| Q2 | `GET /api/device-csi/reliability/sessions/{id}/timeline` có `quality`. `GET /api/device-csi/quality/replays/{id}/timeline` có kết quả Q2 replay. |
| Q3 | `current` và `timeline` trong endpoint phiên CSI, với `evidence_source`, `channel_alignment`, `channel_coverage` và `reason_codes`. |
| CSV | `GET /api/device-csi/experiments/{scope}/{id}/export.csv`. Cột `observation_time_s` là giây. `channel_coverage` và `rx_coverage` là phân số. `packet_loss_fraction` là phân số, `jitter_ms` là ms. Ô thiếu để trống. |

## Kết quả chạy thực tế

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| Q1 | **PASS** | Test monitor và PTY xác nhận lưới 10 s, khoảng vắt biên không đếm hai lần, tổng/đơn vị tốc độ, coverage, đúng/sai kênh, im lặng hợp lệ, stale, ngắt/reconnect/đổi boot và Q1 độc lập với CSI. |
| Q2 | **PASS** | Test trace cho RX rate, jitter kỳ vọng 50 ms, loss có nguồn TX, wrap, duplicate và sequence reset, loss/TX thiếu trả null. Test hai RX có hai phiên và một phiên từ chối RX khác. Test RX mất và Q2 LIVE thiếu sniffer. |
| Q3 | **PASS** | Test CSI tốt với traffic cao, suy giảm, sai kênh/cửa sổ, phủ thấp, mất SNF/RX, từ chối nguồn khác phiên và CSI tổng hợp ghép capture UART. Test API từ chối payload điều khiển cảnh báo. |
| Dashboard và CSV | **PASS** | Chrome/Playwright với FastAPI và UART ảo kiểm số Q1, khu Q2 LIVE khớp API khi không có sniffer, Q3, phân luồng Simulation/Replay/LIVE, bố cục mobile và chuyển tab Legacy. Pytest kiểm Q1 LIVE/REPLAY/SIMULATION, Q2/Q3 CSV khớp cửa sổ backend, cột đơn vị và ô null. |
| Backend và Legacy regression | **PASS** | `.venv/bin/python -m pytest -q` chạy **205 bài PASS**. Backend khởi động trong browser test. Còn một cảnh báo deprecation của Starlette TestClient/AnyIO. |
| Frontend type-check/build | **PASS** | `npm run build` chạy `tsc --noEmit` và Vite production build thành công. |
| Schema UART và chế độ import | **PASS** | CLI UART v2 nhận 7/7 dòng. Native C parser được chạy trong pytest. CLI CSI nhận fixture 100 mẫu/10 khoảng telemetry, test mapper kiểm CSV logger. |
| Build/flash ESP32 Giai đoạn 2 | **NOT RUN** | Giai đoạn 2 không sửa firmware hay schema UART. Các báo cáo trước ghi nhận ba profile đã build. |
| Q1 với ESP32 thật, RSSI và Block Ack | **NOT VERIFIED** | Cần board Activity đúng profile, router/điện thoại cùng kênh, phiên ghi có đánh dấu. |
| RX vật lý, Q2/Q3 RF và hệ thống cảnh báo thật | **NOT VERIFIED** | Checkout nhánh người tại `101e8da` có file README mô tả firmware và mã logger. Thư mục firmware thiếu source RX, không tìm được capture RX thật trong checkout. Chưa có bằng chứng phần cứng để xác nhận format UART đang chạy, timing, counter TX hoặc đồng bộ hai radio. |

Một lượt browser ban đầu lộ lỗi race khi phản hồi dừng phiên CSI có thể kéo giao diện về nguồn trước. Thao tác dừng giờ cập nhật phiên trong danh sách và giữ nguồn người dùng vừa chọn. Sau khi chỉnh selector kiểm thử và xử lý phản hồi, lượt Chrome cuối PASS.

## Lệnh build, chạy và kiểm tra

Chạy từ gốc workspace.

```bash
npm run build
bash run.sh
.venv/bin/python -m pytest -q
.venv/bin/python -m backend.app.device_activity_protocol tests/fixtures/device_activity_v2.jsonl
.venv/bin/python -m research.csi_ingestion tests/fixtures/csi_quality_synthetic.json
DASHBOARD_PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node --test tests/dashboard_browser.mjs
```

Dùng địa chỉ mà `run.sh` in ra. Trong **Device & CSI**, chọn nguồn phù hợp. Với Q1 LIVE, chọn đúng USB sniffer, tự dò baud hoặc chọn 460800 cho profile Activity.

Các lệnh cho board Activity khi người vận hành đã xác nhận board, profile và cổng. Chọn kênh chính 2,4 GHz của router và MAC đã có đồng ý trong menuconfig. Nhả cổng khỏi Dashboard và trình monitor trước khi nạp.

```bash
bash scripts/sniffer.sh menuconfig activity
bash scripts/sniffer.sh build activity
bash scripts/sniffer.sh flash activity /dev/ttyUSB0
```

## Kết nối và chuẩn hóa CSI RX

Checkout nhánh người có parser nhóm bao gồm `BOOT`, `CSI` và `STAT`. Logger ghi `csi.csv` với `host_time,seq,t_us,src_mac,rssi,noise_floor,channel,...`. Đặc tả của nhóm ghi `seq` tăng khi xuất dòng UART. Vì vậy mapper đặt `sequence_kind=uart_emission`. Mất dòng UART không được tính thành mất gói TX. Mốc `host_time` lúc đọc serial cũng không tự trở thành anchor xác minh. [Logger nhóm](../../pbl3_mmt_nhom8/laptop/logger.py) · [Đặc tả dữ liệu nhóm](../../pbl3_mmt_nhom8/Dac_ta_dinh_dang_du_lieu.md) · [Firmware README](../../pbl3_mmt_nhom8/firmware/README.md)

1. Dùng logger RX của nhánh người hoặc adapter đã xác minh trên một cổng RX riêng. Xác nhận `BOOT` mô tả RX và kênh, kiểm tra MAC của luồng tham chiếu từ cấu hình/BOOT, lưu `csi.csv`. Cổng RX do logger/adapter giữ; cổng sniffer do collector Device Activity giữ.
2. Tách mỗi RX, link, boot và kênh thành một trace. Chuẩn bị JSON metadata theo `csi-quality-input-v1` **không gồm samples**, có `version`, `provenance`, `receiver_id`, `channel`, `duration_s`, `rx_clock` và `rx_connected` từ bằng chứng thực nghiệm. Thiếu mốc hoặc khoảng thu thì để mảng rỗng. Cung cấp `rx_telemetry` và xác nhận `tx_rate_verified` chỉ khi có phép đo và xác minh được ngữ nghĩa. Mapper không tự nhập `STAT` thành count khi thời lượng và cách đếm chưa đủ căn cứ.
3. Dùng mapper cùng schema hiện có. Biến `PBL3_RX_REFERENCE_MAC` là MAC tham chiếu đã đối chiếu với phiên thật.

```bash
.venv/bin/python -m research.csi_ingestion /path/to/csi.csv \
  --logger-metadata /path/to/rx-evidence.json \
  --reference-mac "$PBL3_RX_REFERENCE_MAC" > /path/to/trace.json
```

4. Bắt đầu phiên **Q2/Q3 LIVE**, gửi JSON `{"offset_us": ..., "trace": ...}` qua nút **Nạp batch LIVE** hoặc `POST /api/device-csi/reliability/sessions/{id}/batches`. `offset_us` tính từ lúc bắt đầu phiên. Batch LIVE yêu cầu `provenance=live_adapter`, ID RX ổn định, duration chia hết cho 10 giây và các cửa sổ đã kết thúc. Có thể chọn **REPLAY** và nhập `trace.json` để đánh giá trace đã lưu. Chọn nguồn SIMULATION cho fixture tổng hợp.
5. Q2 có thể nghiệm thu riêng với CSI. Chỉ gắn SNF vào batch LIVE sau khi xác minh cùng phiên và có timestamp/khoảng thu hợp lệ. Khai báo `sniffer_source=LIVE` và `sniffer_session_id` trùng phiên CSI. Khi replay dữ liệu ghi thật, ghép capture Q1 hoàn tất bằng `sniffer_capture_id`, `sniffer_boot_id`, `sniffer_source=LIVE`, `sniffer_session_id` trùng ID capture và anchors của đúng lượt. Các nhãn provenance/phiên là cam kết của adapter, còn kiểm chứng vật lý cần đối chiếu log và mốc thu.

## Checklist thực nghiệm phần cứng

- [ ] **Q1 đúng profile và kênh.** Router/điện thoại 2,4 GHz, binding registry và firmware cùng kênh. Heartbeat báo `DEVICE_ACTIVITY_FIXED_CHANNEL`, `fixed` và đúng kênh. Cắm sniffer khi chưa có RX, ghi tải lên/tải xuống rồi khoảng im lặng. Đối chiếu frame/byte, độ phủ, FCS, RSSI khung thu, Block Ack và nhãn thao tác.
- [ ] **Q1 sai kênh và mất nguồn.** Tạo phiên khác kênh, mất heartbeat, ngắt/cắm lại và reboot board. Xác nhận UNKNOWN đúng nguyên nhân, lịch sử có cửa sổ thiếu và im lặng hợp lệ chỉ xuất khi đã xác minh binding.
- [ ] **Q2 độc lập.** Thu một RX với sniffer ngắt, lặp với RX thứ hai trong phiên riêng. Đối chiếu UART, timestamps, đơn vị RSSI/noise, `STAT` và TX nếu có bộ đếm độc lập. Tắt RX, xác nhận stale/UNKNOWN. So số đo Dashboard và CSV cùng cửa sổ.
- [ ] **Q3 theo kênh, thời gian và coverage.** Lượt cùng kênh có clock anchors kiểm chứng, lượt lệch kênh, lượt phủ thấp, mất SNF và mất RX. Tạo tải cao ổn định, đối chiếu với lượt mất gói có căn cứ. Xác nhận `CSI_ONLY`/ `CSI_AND_SNIFFER`/ `INSUFFICIENT_DATA`, và kiểm tra hệ thống người tiếp tục xử lý cảnh báo an toàn độc lập.
- [ ] **Tái lập phiên.** Ghi dấu mốc thực nghiệm, kết thúc phiên, replay và xuất CSV. Đối chiếu source, session, biên, đơn vị và giá trị trống. Lưu raw và mốc đồng bộ để truy vết. Hiệu chuẩn các ngưỡng trên dữ liệu thật trước khi dùng cho kết luận nghiên cứu.
