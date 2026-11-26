# Giới hạn MVP

- ESP32-C3 nghe kênh 2,4 GHz đang cấu hình và firmware chỉ thống kê frame driver cung cấp. MAC riêng theo SSID có thể đổi. Block Ack, mật độ callback và độ phủ của Q1 trên router thực chưa xác minh ở vòng kiểm tra này. [Firmware activity](DEVICE_ACTIVITY_FIRMWARE.md)
- Không quan sát được traffic không chứng minh điện thoại rời nhà. Frame thấy được có thể do tác vụ nền. SNF đếm frame quan sát được theo giây, không đo thời gian kênh bị chiếm dụng.
- Q2 replay đang giới hạn ở CSI synthetic. Đã có endpoint LIVE Q3 cho metadata chuẩn hóa, chưa có driver nối RX thật. Timestamp board, sequence TX, packet loss, noise floor, `n_filtered`, bandwidth và anchor cần xác minh trên firmware RX của nhánh người. Khi hai nguồn lệch kênh hoặc lệch đồng hồ, Q3 quay về CSI-only.
- Bộ ngưỡng Reliability là heuristic chưa được hiệu chuẩn. Cơ chế kết hợp chỉ đánh giá chất lượng dữ liệu. Kiểm thử cảnh báo té ngã/hô hấp end-to-end cần hệ thống nhánh người, chưa có trong repo này.
- Phiên Q1 mới lưu metadata đã thay MAC bằng ID. Raw Probe v1 xuất theo schema lịch sử và có thể chứa MAC. Bảo vệ và tách dữ liệu v1 khỏi gói demo/chia sẻ. Giữ khóa HMAC cục bộ, giữ quyền truy cập runtime và chỉ bind server trong môi trường thử cục bộ.
- Bảng thiết bị REPLAY dùng capture đúng ID khi đã phát qua API. Timeline CSI của phiên ghép đã đồng bộ; bảng Q1 hiển thị tiến độ replay riêng của collector. Hai nguồn replay không chạy chung tốc độ con trỏ giao diện. Timeline giữ tối đa 300 cửa sổ mới nhất cho mỗi lần đọc.
