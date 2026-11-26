# CSI Reliability Engine

Q3 kết hợp cửa sổ chất lượng CSI, hoạt động thiết bị đăng ký, mật độ frame trên kênh và tình trạng nguồn. [Q1](REGISTERED_DEVICE_MONITOR.md) cung cấp frame/s, byte/s, trạng thái, kênh và timestamp theo board. [Q2](CSI_CHANNEL_QUALITY.md) cung cấp receive rate, packet loss khi có căn cứ TX, P95 inter-arrival, RSSI, noise floor, `n_filtered` và thông tin đồng bộ. Mẫu thiếu được giữ ở `null`.

## Quy tắc và giải thích

- `UNKNOWN` khi không có CSI đủ độ phủ hoặc CSI mất nguồn, stale hay chưa đồng bộ. `DEGRADED` khi rate, loss, P95 hoặc phương sai RSSI vi phạm ngưỡng. `GOOD` khi các chỉ số có được nằm trong ngưỡng. Các nhãn là heuristic chưa hiệu chuẩn.
- Ghép bằng chứng thiết bị theo cùng kênh, cùng biên cửa sổ và sai số đồng bộ trong ngưỡng. Khi CSI có packet loss từ 5% trở lên, mật độ frame quan sát cao và đủ ít nhất 10 frame/s từ thiết bị đăng ký, luật kết hợp có thể đánh dấu suy giảm trước ngưỡng loss CSI-only 10%. Các ngưỡng đều cấu hình được. Traffic quan sát cao riêng lẻ chỉ thêm reason code.
- Khi thiếu SNF, sai kênh hoặc lệch đồng hồ, CSI-only tiếp tục chạy. Khi chỉ có thống kê kênh, kết quả ghi `CSI+Channel`. `data_sources` cho biết dữ liệu thực sự dùng và `source_freshness` ghi tình trạng, tuổi nguồn từng cửa sổ.
- API chỉ trả tư vấn `advisory_only:true`. Hợp đồng không nhận đầu vào từ mô hình người hay đầu vào cảnh báo. Hệ thống này chưa kết nối với hệ thống té ngã hoặc hô hấp, nên không có đường điều khiển hoãn/hủy cảnh báo. Kiểm thử phần mềm xác minh ranh giới hợp đồng. Kiểm thử end-to-end cảnh báo cần ứng dụng nhánh người.

## API và schema

Tiền tố `/api/device-csi/reliability`. OpenAPI mô tả body các request. SQLite thêm bảng `reliability_sessions` và `reliability_batches` bằng migration cộng thêm khi khởi động.

| Method | Đường dẫn | Hợp đồng |
|---|---|---|
| GET | `/sessions` | Phiên gần nhất với mode và provenance. |
| POST | `/sessions` | `{mode, rules?, quality_replay_id?}`. `REPLAY` cần ID Q2 và giữ provenance. `DEMO` tạo fixture synthetic. `LIVE` khởi tạo phiên trống. |
| POST | `/sessions/{id}/batches` | `{offset_us, trace}`. Chỉ phiên `LIVE` nhận `trace.provenance:"live_adapter"`. Batch chồng lấn bị từ chối, retry trùng kết quả giữ bản lưu đầu. |
| GET | `/sessions/{id}/timeline?window_s=10&context=csi-only` | `csi-reliability-v1`, `session`, `clocks`, `current`, `timeline`. Hỗ trợ `window_s=1` hoặc `10`, `context=combined` hoặc `csi-only`. |

Mỗi kết quả có `reliability_label`, `quality_indicators`, `reason_codes`, `event_timestamp`, `data_sources`, `source_freshness`, `evidence_mode`, `config_version`, `advisory_only` và biên cửa sổ. `observed_indicators` giữ các quan sát đã ghép được cho biểu đồ cả khi người dùng chọn CSI-only. `event_timestamp.session_us` là cuối cửa sổ theo phiên. LIVE có thêm `utc`, tính từ `started_at + offset_us + end_us`. `current` của LIVE được kiểm tra stale lại ở thời điểm đọc API, mặc định 15 giây. Timeline đánh giá bằng chứng lưu trữ theo thời gian ingest. DEMO và REPLAY dùng tuổi nguồn tại mốc bản ghi. Config được chốt theo phiên và có fingerprint từ toàn bộ ngưỡng.

LIVE nhận metadata đã chuẩn hóa từ một adapter cục bộ có mốc chung. Adapter gửi offset tính từ `started_at` do API trả, dữ liệu đã thu trước khi gửi, và các anchor ở hệ tọa độ cục bộ của batch. Offset và thời lượng là bội số 10 giây để mỗi batch cung cấp cả hai cỡ cửa sổ. Các batch cùng phiên có cùng ngữ nghĩa một nguồn CSI. Bản ghi quá khứ gửi trễ có thể được giữ nhưng kết quả hiện tại là stale. Chưa có adapter UART CSI hoặc trace phần cứng đã xác minh để kết nối tự động.

## Kiểm thử Giai đoạn 5

| Phạm vi | Kết quả |
|---|---|
| CSI ổn định, mất gói, traffic cao ổn định hoặc suy giảm, thiếu telemetry | PASS bằng fixture |
| Mất SNF/RX, sai kênh, lệch thời gian, thiếu dữ liệu và stale LIVE | PASS bằng unit/API test |
| DEMO/REPLAY/LIVE, config theo phiên, từ chối batch tương lai hoặc chồng lấn | PASS bằng API test |
| Ranh giới read-only của kết quả với cảnh báo | PASS kiểm tra schema. NOT RUN đối với ứng dụng cảnh báo thực tế. |
| Phần cứng CSI và đồng bộ RF | NOT RUN do thiếu nguồn RX xác minh. |

```bash
.venv/bin/python -m pytest -q tests/test_csi_reliability.py tests/test_csi_quality.py tests/test_registered_device_monitor.py
```
