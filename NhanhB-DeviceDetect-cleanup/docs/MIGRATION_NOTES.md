# Ghi chú chuyển cấu trúc

Baseline là commit `743c804`. Cleanup chạy trên nhánh `cleanup/repository-structure` trong worktree riêng.

## Đường dẫn và tương thích

- Router chuyển từ `backend/app/*_api.py` vào `backend/app/api/`. Các đường import cũ vẫn trỏ tới cùng module. Entry `backend.app.main:app`, tên schema OpenAPI, route HTTP, format request/response và xử lý validation được giữ.
- Panel React chuyển vào `frontend/src/device-csi/` và `frontend/src/legacy-probe/`. Vite entry, URL và API client giữ nguyên.
- Tài liệu chuyển theo chủ đề. Với liên kết cũ đến checkout PBL3 bao ngoài, tài liệu lịch sử trỏ tới commit của repo PBL3 có chứa các file đã dẫn. [Ánh xạ toàn bộ đường dẫn](REPOSITORY_CLEANUP_AUDIT.md#đường-dẫn-move)
- Firmware, đường flash và ba profile giữ nguyên. CI firmware chạy matrix cho Probe hopping, Probe fixed và Device Activity fixed.
- Module `research.*`, parser JSONL, schema, preset và vị trí dữ liệu runtime giữ nguyên. SQLite và format capture không cần migration. Khi dùng worktree mới, mặc định ứng dụng dùng `data/runtime/` của worktree đó; dữ liệu trước đây nằm tại checkout gốc. Có thể trỏ `WIFI_PROBE_DATA_DIR` tới bản sao dữ liệu riêng để thử replay.
- `python -m scripts.package` giữ tên ZIP và đường dẫn tương đối cũ, nhưng chỉ đóng gói snapshot `HEAD`. Các chỉnh sửa chưa commit, capture và cấu hình cục bộ ngoài Git vắng mặt trong gói. Thay đổi sẽ vào ZIP sau khi có commit.

## Kiểm chứng

| Hạng mục | Baseline | Cleanup |
|---|---|---|
| Backend pytest, parser v1/v2, API, Q1/Q2/Q3, record/replay, evaluation và integration | PASS · 193 bài | PASS · 194 bài, gồm bài hồi quy đóng gói. Có một cảnh báo deprecation Starlette/AnyIO như baseline. |
| Firmware ESP-IDF 5.5.4, target ESP32-C3 | PASS · hopping, fixed, activity | PASS · build lại cả ba profile trong bản sao tạm. |
| TypeScript và Vite production | PASS | PASS · cùng tên asset CSS/JS và nội dung build với baseline. |
| Chrome/Playwright với FastAPI | PASS · 1 bài | PASS · 1 bài. LIVE trống, DEMO, REPLAY, lỗi API, mobile và Legacy. |
| OpenAPI | 34 đường dẫn | PASS · tài liệu JSON đã sắp khóa giống từng byte, gồm schema và operation IDs. |
| UART fixture và adapter CSI | Có fixture trong baseline | PASS · 7 bản ghi JSONL v2 hợp lệ; adapter nhận 100 bản ghi RX và 10 khoảng telemetry tổng hợp. |
| Kết quả thuật toán và Legacy | Có runner và fixture | PASS · source thuật toán, parser, schema và cấu hình không thay đổi. Chạy CLI evaluation trên cùng bộ tổng hợp; toàn bộ file báo cáo giống nhau. |
| Import, cấu hình, tài liệu, checksum | Kiểm kê đường dẫn gốc | PASS · 4 import tương thích, 218 tham chiếu Markdown cục bộ, kiểm tra URL ngoài, phụ thuộc Python, Bash syntax, khởi động qua `./run.sh` và checksum 27 file runtime/kết quả. |
| GitHub Actions, lint frontend | NOT RUN | NOT RUN · chạy lệnh build/test cục bộ; workflow hosted chưa chạy và project chưa có lint script. |
| ESP32/điện thoại/router thật, CSI RX LIVE và cảnh báo nhánh người | NOT VERIFIED | NOT VERIFIED · máy không thấy cổng USB–UART của board; không có RX log thật để đánh giá hoặc hiệu chuẩn. |

[Hướng dẫn chạy lại](UBUNTU_RUNBOOK.md) · [Báo cáo xóa file](DELETED_FILES_REPORT.md) · [Giới hạn phần cứng](implementation/KNOWN_LIMITATIONS.md)
