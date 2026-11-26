# Dashboard Device & CSI

Dashboard mặc định mở **Device & CSI**. Tab **Legacy / Probe** giữ giao diện Sherlock, demo Probe và ghi/đánh giá phiên v1. Dùng cùng một FastAPI và một ứng dụng React. [Runbook Ubuntu](../UBUNTU_RUNBOOK.md)

- **LIVE** hiển thị nguồn đang kết nối và dữ liệu của phiên LIVE được chọn. Tạo phiên CSI và gửi batch từ adapter chuẩn hóa qua API. Khi chưa có batch hoặc batch đã cũ, Reliability là `UNKNOWN` và ô CSI để `NOT AVAILABLE`.
- **REPLAY** hiển thị CSI từ một Q2 replay đã nhập. Nếu phiên có capture Q1, nút phát capture cho phép xem bảng thiết bị của đúng ID đó. Hai màn hình ghi rõ provenance tổng hợp nếu nguồn CSI xuất phát từ fixture.
- **DEMO** tạo phiên mô phỏng riêng và hiển thị nhãn DEMO. Có đoạn CSI ổn định khi traffic tăng và đoạn packet loss cao. Thiết bị mô phỏng chỉ xuất hiện ở chế độ này.

Bảng thiết bị dùng tên và ID rút gọn, cùng kênh, Frames/s, Bytes/s, RSSI và lần thấy cuối theo đồng hồ mẫu. Form đăng ký yêu cầu đồng ý và che MAC khi nhập. API định danh thiết bị giữ MAC ở dạng HMAC. [Đăng ký và thu dữ liệu Q1](REGISTERED_DEVICE_MONITOR.md)

Các biểu đồ hiển thị bốn chuỗi theo cửa sổ 1 hoặc 10 giây. Cột sọc biểu thị thiếu dữ liệu hoặc UNKNOWN. `Hoạt động kênh` dùng frame/s. Panel Reliability hiển thị lý do, tuổi nguồn, sai lệch đồng bộ và timeline. Chuyển `CSI-only` để loại ảnh hưởng của cờ hoạt động khỏi quyết định Q3, trong khi biểu đồ kênh vẫn có thể hiển thị quan sát đã đồng bộ. [Hợp đồng Reliability](CSI_RELIABILITY_DESIGN.md)

```bash
npm run build
DASHBOARD_PLAYWRIGHT_MODULE=/tmp/pbl3-dashboard-browser/node_modules/playwright/index.mjs \
  node --test tests/dashboard_browser.mjs
```

Browser test dùng FastAPI thật với thư mục runtime tạm. Nó kiểm tra LIVE trống, DEMO, REPLAY fixture, lỗi API, đổi cửa sổ, lý do Reliability, mobile và baseline. Không có lint script trong `frontend/package.json`.
