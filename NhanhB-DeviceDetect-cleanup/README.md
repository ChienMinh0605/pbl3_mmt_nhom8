# WiFi Device Sherlock

Dự án PBL3 **Passive WiFi Device Activity Monitoring and Channel Quality Assessment for Reliable CSI-Based Human Sensing**. ESP32-C3 quan sát hoạt động Wi‑Fi và gửi metadata JSONL qua UART. FastAPI nhận dữ liệu, quản lý phiên và phục vụ dashboard React. CSI đi vào qua hợp đồng metadata riêng.

| Phần | Đầu vào → đầu ra |
|---|---|
| **Q1 · Device Activity** | JSONL v2 và registry → hoạt động thiết bị, frame/s, byte/s, RSSI, capture và replay theo ID. [Hướng dẫn Q1](docs/implementation/REGISTERED_DEVICE_MONITOR.md) |
| **Q2 · Channel Quality** | Metadata CSI, clock anchors và capture Q1 tùy chọn → timeline 1/10 giây, receive rate, RSSI và loss khi đủ căn cứ TX. [Hướng dẫn Q2](docs/implementation/CSI_CHANNEL_QUALITY.md) |
| **Q3 · Reliability** | Chất lượng CSI và hoạt động đã đồng bộ → `GOOD`, `DEGRADED`, `UNKNOWN` cùng mã lý do và tình trạng nguồn. [Hướng dẫn Q3](docs/implementation/CSI_RELIABILITY_DESIGN.md) |
| **Legacy / Probe** | JSONL v1 → Sherlock, unique-MAC và timeout; ghi phiên, replay, chẩn đoán và đánh giá. [Hướng dẫn Legacy](docs/legacy/DASHBOARD_GUIDE.md) |

## Chạy trên Ubuntu

Cần Python 3.12 có `venv`, Node.js 22+ và npm. Để build firmware cần ESP-IDF 5.5.4. Demo và test phần mềm chạy được khi chưa có board.

```bash
bash scripts/setup.sh
./run.sh
```

Mở URL in trên terminal. Tab **Device & CSI** mở mặc định. Bấm **Chạy demo Device & CSI**, chọn cửa sổ 1 hoặc 10 giây và xem lý do Reliability. Chọn **Nguồn hiện tại** để trở về LIVE. Chuyển sang **Legacy / Probe** và bấm **Chạy demo nhanh** để thử baseline. Tài liệu API tương tác ở `/docs` trên cùng server. [Runbook Ubuntu](docs/UBUNTU_RUNBOOK.md) · [Hướng dẫn VS Code](HUONG_DAN_CHAY_VSCODE.md)

```bash
npm run dev                         # Uvicorn :8000, Vite :5173
npm run build                       # TypeScript và Vite production
.venv/bin/python -m pytest -q
```

## Cấu trúc mã nguồn

- `firmware/sniffer/` là dự án ESP-IDF dùng chung cho Probe hopping, Probe fixed và Device Activity fixed. `firmware/common/` chứa mã khởi tạo chung.
- `backend/app/` chứa app FastAPI, parser UART và SQLite. `backend/app/api/` chứa router Probe, Q1, Q2 và Q3.
- `frontend/src/` chứa dashboard và hai nhóm giao diện `device-csi/`, `legacy-probe/`.
- `research/` chứa collector, thuật toán, record/replay, baseline và công cụ evaluation. `configs/`, `scripts/` và `tests/` giữ các cấu hình, lệnh và fixture có thể tái lập.

[Sơ đồ phụ thuộc và cấu trúc](docs/REPOSITORY_STRUCTURE.md) · [Audit và bảng phân loại](docs/REPOSITORY_CLEANUP_AUDIT.md) · [Migration và kết quả kiểm chứng](docs/MIGRATION_NOTES.md)

## Dữ liệu và thực nghiệm

Runtime mặc định ở `data/runtime/`, gồm SQLite, khóa registry và file phiên. Đặt cấu hình có MAC, dữ liệu capture, calibration và kết quả cục bộ dưới `data/` hoặc ngoài checkout. Probe v1 có thể lưu MAC đầy đủ. Q1 capture dùng ID đã thay MAC. Dùng thư mục runtime riêng khi thử demo trong worktree mới. [Quy trình thực nghiệm Probe](docs/experiments/EXPERIMENT_PROTOCOL.md) · [Đánh giá A/B/C cho Device & CSI](docs/experiments/EXPERIMENT_PLAN.md)

Build firmware và kiểm thử phần mềm đã chạy. Thu RF bằng ESP32, CSI RX LIVE, hiệu chuẩn trên dữ liệu đo và tích hợp hệ thống cảnh báo nhánh người vẫn là **NOT VERIFIED** trong lần cleanup. [Giới hạn MVP](docs/implementation/KNOWN_LIMITATIONS.md)
