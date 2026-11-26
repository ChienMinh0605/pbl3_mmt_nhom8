# Kế hoạch thực nghiệm Device & CSI

Chạy ba biến thể trên cùng các cửa sổ và nhãn độc lập. A dùng CSI. B dùng CSI và đặc trưng chất lượng CSI. C dùng các đầu vào của B cùng hoạt động thiết bị đã đồng bộ trên cùng kênh. Định nghĩa feature và mô hình trước khi chạy test. Q3 là tín hiệu chất lượng của dữ liệu RF và không dùng dự báo hoặc nhãn con người làm đầu vào.

## Thu và chia dữ liệu

1. Ghi `session_id`, phòng/bố trí, board, channel, TX schedule, phiên bản firmware và anchor sai số. Thu thử Q1 trên điện thoại đã đồng ý tham gia trong lượt yên tĩnh, truy cập và ngắt Wi‑Fi. Ghi ground truth thao tác riêng với trạng thái suy luận từ frame.
2. Thu CSI khi đường RX ổn định, có mất gói được đối chiếu từ TX, tải nhẹ/cao cùng kênh và tải khác kênh làm đối chứng. Ghi log RX lúc dừng và khôi phục. Xác minh ý nghĩa sequence, `n_filtered` và `noise_floor` từ firmware thực tế.
3. Với nhánh người, lấy ground truth và dự báo của ba biến thể từ bộ đánh giá độc lập. Kiểm thử hành vi cảnh báo chỉ ở môi trường thử có kiểm soát và có quy trình an toàn của nhóm thu.
4. Chia theo nhóm buổi thu hoặc đối tượng/bố trí độc lập. Các clip của cùng nguồn ghi dùng chung `group_id`. Lưu SHA-256 của nguồn ghi thực tế và khóa danh sách development/test trước khi báo cáo. Hiệu chỉnh feature, tham số mô hình và heuristic trên development rồi đóng băng trước test.

## Evaluation runner

`research.reliability_evaluation` nhận JSON gồm `development` và `test`, mỗi phần là mảng session. Mỗi session có `session_id`, `group_id`, `recording_sha256`, `provenance: measured|synthetic` và danh sách `windows` theo thứ tự không chồng lấn. [Mã runner](../../research/reliability_evaluation.py) · [Tests](../../tests/test_reliability_evaluation.py)

Mỗi window có `{start_s,end_s,fall,scores}`. `fall` là nhãn độc lập `true`, `false` hoặc `null`. `scores` chứa `A`, `B`, `C`, mỗi giá trị từ 0 đến 1 hoặc `null`. Runner không tạo score thay cho mô hình. Có thể bổ sung `device_truth`, `device_observed`, `quality_truth`, `quality_estimate` để tính accuracy và confusion matrix riêng. `quality_truth` phải đến từ quy trình gán nhãn độc lập với luật Q3 đang đánh giá.

Runner từ chối ID/hashes trùng và nhóm chạy qua cả hai tập. Các ngưỡng chọn trên development tối đa hóa F1 theo lưới 0,01 rồi dùng cố định trên test. A/B/C tính trên cùng tập cửa sổ có đủ ba dự báo và nhãn. Báo coverage để thấy phần bị loại. False alarms đếm các đoạn dương liền nhau trong thời gian ground truth không ngã. Fall Recall đếm đoạn ngã có ít nhất một cửa sổ đánh giá được. Detection Delay là thời điểm cuối cửa sổ phát hiện đầu tiên trừ mốc bắt đầu đoạn ngã. Trường không đủ căn cứ trả `null`.

```bash
.venv/bin/python -m research.reliability_evaluation path/to/study.json > evaluation.json
.venv/bin/python -m pytest -q tests/test_reliability_evaluation.py
```

Chỉ dùng `--allow-synthetic` khi kiểm tra cơ chế. Báo cáo có `synthetic:true` nếu đầu vào chứa fixture. Chưa có bộ dữ liệu thật hoặc dự báo A/B/C cho nghiên cứu này, vì vậy chưa có kết quả so sánh thực nghiệm.
