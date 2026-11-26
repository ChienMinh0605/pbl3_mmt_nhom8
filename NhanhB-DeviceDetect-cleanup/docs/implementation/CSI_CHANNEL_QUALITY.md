# CSI Channel Quality Monitor

Giai đoạn 4 cung cấp adapter metadata CSI và timeline offline **1 giây / 10 giây**. Bản chạy hiện tại dùng replay gắn nhãn `synthetic`. Backend dùng FastAPI và SQLite hiện có, đồng thời có thể đọc capture Device Activity đã giảm thiểu dữ liệu. Kết quả CSI chỉ phục vụ nghiên cứu. Các quyết định về kênh radio, phát hiện người và cảnh báo ngã vẫn thuộc các hệ thống tương ứng. [Registered Device Activity Monitor](REGISTERED_DEVICE_MONITOR.md)

## Kiểm kê dữ liệu RX

Trong cây làm việc và dữ liệu runtime hiện có, chưa tìm thấy firmware CSI RX, driver kết nối nhánh người hay capture CSI thực. Đặc tả nhóm mô tả `CSI,<seq>,<t_us>,…` và `STAT,<t_us>,<board>,…` ở mức thiết kế. Các trường sau cần đối chiếu với output RX thực trước khi viết parser serial theo định dạng đó. [Đặc tả nhóm, mục 3.2 và 3.4](../../Dac_ta_dinh_dang_du_lieu%20%282%29.md)

| Trường | Bằng chứng hiện có và trạng thái |
|---|---|
| Timestamp RX | Thiết kế dùng `t_us` từ boot. Chưa xác nhận độ phân giải, reset hay mốc chung với SNF bằng log thật. |
| Số gói RX và sampling rate | Thiết kế `STAT.n_rx` đếm dòng CSI đã xuất trong kỳ. Chưa có counter callback RX hoặc lịch TX đã kiểm chứng. Adapter tính `csi_received` và `csi_receive_hz` từ bản ghi RX chuẩn hóa, báo `rx_emitted_hz` riêng khi có telemetry. |
| Sequence | Đặc tả gọi `CSI.seq` là số thứ tự xuất dòng ở ESP. Loại `uart_emission` không dùng để ước lượng mất gói RF. Chưa có sequence TX liên tục, quy ước wrap hoặc tần suất TX được xác minh. |
| RSSI, noise floor | Đặc tả có `rssi` và `noise_floor` dBm. Chưa xác nhận có trên board và phiên bản RX thực tế. |
| `n_filtered` | Đặc tả nói đến khung bị lọc vì khác MAC. Chưa rõ ở RX thực đây là counter theo kỳ hay tích lũy, hoặc phạm vi lọc cụ thể. |
| Airtime, CCA/PHY busy time, link layout và I/Q | Chưa có nguồn dữ liệu được xác minh. Timeline chỉ dùng metadata. Adapter không nhận payload I/Q hoặc MAC. |

## Hợp đồng adapter `csi-quality-input-v1`

Một trace mô tả một bộ RX và một luồng tham chiếu trên một kênh cố định đã khai báo. Mỗi lần reboot hoặc đổi link tách thành trace riêng. JSON khai báo `version`, `provenance`, `duration_s`, `channel` và `samples`. Phạm vi là 1–300 giây. [Adapter](../../research/csi_ingestion.py) · [Fixture synthetic](../../tests/fixtures/csi_quality_synthetic.json)

| Nhóm | Trường |
|---|---|
| `samples` | `ts_us` theo clock RX, cùng `seq`, `rssi_dbm`, `noise_floor_dbm` nếu có. Sắp xếp theo `ts_us`. |
| `rx_connected` | Các khoảng `[start_us,end_us)` thực sự có bằng chứng RX hoạt động, theo clock RX. Khoảng trống làm giảm coverage. Không dùng chỉ sự xuất hiện của mẫu để lấp khoảng trống. |
| `rx_telemetry` | Khoảng RX có `n_rx_emitted` và `n_filtered` nếu đúng ngữ nghĩa. Hai trường là số đếm của đúng khoảng đã khai báo. Nếu nguồn là counter tích lũy, lấy delta trong cùng boot trước khi nhập. |
| `sniffer_intervals` | `[start_us,end_us)`, `channel`, `frame_count` theo đồng hồ SNF. Có thể thay danh sách này bằng `sniffer_capture_id` và `sniffer_boot_id` khi gọi API. |
| `rx_clock`, `sniffer_clock` | Mỗi anchor có `{board_us, session_us, uncertainty_us}`. `session_us` của hai nguồn dùng chung gốc đo. |
| Loss tùy chọn | `sequence_kind: unknown\|uart_emission\|tx_contiguous`, `seq_modulus` nếu biết wrap, `expected_tx_hz` nếu đã xác minh tốc độ cố định nguyên và RX tạo tối đa một bản ghi trên mỗi TX. |

Clock của từng board được ánh xạ bằng đường thẳng qua hai anchor đầu/cuối. Adapter báo offset tại anchor đầu, drift ppm và sai lệch lớn nhất tại các anchor cộng với độ bất định của chúng. Không ngoại suy ngoài khoảng anchor. Mặc định loại clock có drift tuyệt đối trên 200 ppm hoặc sai số ước lượng trên 50 ms. Đối chiếu liên nguồn dùng tổng sai số ước lượng của RX và SNF với cùng ngưỡng. Đo hai anchor bằng sự kiện hoặc mốc đồng bộ có ghi lại sai số. Thời điểm host đọc UART tự nó không xác định được thời gian capture trên board.

## Timeline và cách diễn giải

- Cửa sổ nửa mở `[start_us,end_us)` không chồng lấn, lấy từ mốc chung. Chỉ xuất cửa sổ đủ độ dài. `csi_receive_hz` chia số bản ghi CSI chuẩn hóa trong cửa sổ cho thời gian RX có độ phủ. `interarrival_median_us` và P95 nearest-rank tính từ các cặp mẫu trong cửa sổ. RSSI dùng median và phương sai tổng thể. Ít hơn hai giá trị RSSI thì phương sai là `null`. Các trường noise floor hoặc `n_filtered` thiếu trả `null`. Tốc độ telemetry chỉ báo khi các khoảng đầy đủ cung cấp giá trị cho cả cửa sổ.
- `packet_loss_fraction` chỉ có khi RX phủ toàn bộ cửa sổ và có bằng chứng TX. Nếu có lịch TX cố định đã xác nhận, mẫu số là `expected_tx_hz × window_s`, có khử trùng sequence TX nếu nguồn cung cấp. Nếu chỉ có sequence TX liên tục, loss tính trong đoạn từ TX đầu đến TX cuối quan sát được mà không suy ra loss ở rìa. Gap UART, số sequence mơ hồ hoặc thiếu căn cứ cho kết quả `null` với lý do.
- `sniffer_frames_per_s` chia số callback frame hợp lệ cho thời gian SNF đủ dữ liệu cùng kênh. Capture Giai đoạn 3 dùng delta `rx_callbacks − invalid_frames − off_channel_frames` từ các heartbeat lành mạnh, gồm cả frame không gán được thiết bị và tránh cộng trùng theo registry. `channel_activity_indicator` là `LOW` hoặc `ELEVATED` theo ngưỡng frame/s. Đây là chỉ báo mật độ frame thấy được. Sniffer không đo thời gian kênh bận hay xuất phần trăm airtime. Thiếu SNF, sai kênh, thiếu độ phủ hoặc sai đồng bộ thì chỉ báo để `null` và `comparison_ready=false`.
- `quality` đánh giá dữ liệu **CSI RX**. Mặc định `UNKNOWN` khi clock RX chưa đối chiếu được hoặc độ phủ dưới 80%. Cửa sổ đủ điều kiện là `DEGRADED` nếu dưới 5 bản ghi/s, loss có bằng chứng vượt 10%, P95 inter-arrival trên 500 ms hoặc phương sai RSSI trên 25 dB². `GOOD` nghĩa là các chỉ số có được nằm trong ngưỡng. Các ngưỡng có thể cấu hình trong `rules` khi tạo replay và luôn mang cờ `heuristic_uncalibrated`. SNF thiếu dữ liệu không tự đổi nhãn CSI RX. Mật độ frame tăng có thể được đối chiếu với các chỉ số CSI, nhưng một lần trùng lặp trên timeline chưa xác định quan hệ nhân quả.

## Chạy fixture synthetic qua API

Chạy `./run.sh` và dùng cổng được in ra. API cấp ID replay và lưu trace chuẩn hóa cùng `rules` vào SQLite. Gọi timeline nhiều lần dùng lại đúng dữ liệu đã lưu. Ví dụ từ gốc repo với cổng 8000.

```bash
.venv/bin/python -m research.csi_ingestion tests/fixtures/csi_quality_synthetic.json
api=http://127.0.0.1:8000/api/device-csi/quality
replay_id=$(
  .venv/bin/python -c 'import json,sys; print(json.dumps({"trace":json.load(sys.stdin)}))' \
    < tests/fixtures/csi_quality_synthetic.json \
    | curl -fsS -H 'Content-Type: application/json' --data-binary @- "$api/replays" \
    | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["id"])'
)
curl -fsS "$api/replays/$replay_id/timeline?window_s=1"
curl -fsS "$api/replays/$replay_id/timeline?window_s=10"
```

Để kiểm thử cách đọc SNF, gửi thêm `sniffer_capture_id` và `sniffer_boot_id`, đặt `trace.sniffer_intervals` rỗng và điền anchor cho đúng boot đã chọn. Timeline vẫn mang nhãn `synthetic` vì đầu vào CSI là fixture. Test tích hợp có sẵn đi theo đường thu và phát lại này qua capture Giai đoạn 3.

## Chuẩn bị thử với dữ liệu thực

1. Lấy từ nhóm RX một đoạn BOOT/CSI/STAT thật có phiên bản firmware, kênh, mẫu trong khoảng RX chạy và bị ngắt. So casing, đơn vị, loại sequence và hành vi wrap/reset. Với `n_filtered` và số packet, so sánh từng khoảng để biết là count hay delta. Giữ trường thiếu ở `null`.
2. Thu đồng thời SNF đã giảm thiểu MAC và RX trong môi trường demo. Tạo lượt yên tĩnh và lượt có tải Wi‑Fi có kiểm soát trên cùng kênh. Lấy ít nhất hai anchor mỗi board trên cùng gốc host và ghi sai số mốc. Nếu SNF và RX nghe khác kênh, giữ dữ liệu làm đối chứng riêng.
3. Ánh xạ metadata đã xác nhận sang hợp đồng, bỏ MAC và I/Q khỏi file nhập, đặt `provenance:"unverified_import"`, rồi chạy `.venv/bin/python -m research.csi_ingestion /duong/dan/trace.json` để kiểm tra format offline. Giữ `sequence_kind:"uart_emission"` hoặc `unknown` cho sequence chưa được chứng minh là từ TX. API timeline hiện chỉ nhận fixture synthetic. Sau khi có log thật và đối chiếu semantics, dùng kết quả đó để quyết định adapter theo firmware RX và kiểm chứng lại ngưỡng trước khi mở ingestion thực.

```bash
.venv/bin/python -m pytest -q tests/test_csi_quality.py tests/test_registered_device_monitor.py
```
