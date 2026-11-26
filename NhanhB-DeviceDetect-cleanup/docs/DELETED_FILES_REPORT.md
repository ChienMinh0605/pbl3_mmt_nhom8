# Báo cáo xóa file

**Danh sách DELETE_CANDIDATE trống.** Audit không tìm thấy source, tài liệu nghiên cứu hay dữ liệu nào có đủ bằng chứng để đề nghị xóa. Vì vậy lần cleanup này có **0 file DELETED**, kể cả build artifacts và cache đang hiện diện.

Các router, panel React, tài liệu và manifest lịch sử đã đổi vị trí theo bảng MOVE. Thuật toán, parser, schema, fixture, baseline, dữ liệu thực nghiệm và calibration cục bộ được giữ lại. File ngoài Git không rõ nguồn gốc vẫn thuộc UNKNOWN. [Bảng kiểm kê và ánh xạ MOVE](REPOSITORY_CLEANUP_AUDIT.md)

Có thể đọc bản của bất kỳ file đã theo dõi ở mốc trước cleanup bằng `git show 743c804:<đường-dẫn-cũ>`. Dữ liệu cục bộ nằm ở checkout gốc và được kiểm đối chiếu bằng checksum.
