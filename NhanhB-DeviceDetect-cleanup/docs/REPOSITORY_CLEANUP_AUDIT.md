# Audit tái cấu trúc repository

## Phạm vi và dữ liệu

- Repo độc lập `qphuc9405/NhanhB-DeviceDetect` bắt đầu từ `743c804ab3fa173723b7b9a52e82bb516461e1a5` trên `feature/device-csi-reliability`. Index và working tree của repo này sạch trước khi bắt đầu. Nhánh `cleanup/repository-structure` chạy trong worktree riêng.
- Checkout PBL3 bao ngoài là một repo Git khác, có 103 mục thay đổi hoặc untracked dưới `wifi-device-sherlock/` (README, backend, firmware, frontend, research, docs, scripts, tests và cấu hình). Danh sách do Git xuất ở `/tmp/pbl3-cleanup-evidence.hQSOmr/parent-status.txt` trên máy này. Cleanup không đi qua checkout đó.
- Kiểm kê đọc nội dung 148 file theo dõi, phân tích import Python kể cả import bên trong hàm, đối chiếu import/CSS React, CMake/Kconfig, lệnh `python -m`, CI, đường dẫn trong test và Markdown. Git index không có symlink. Bản sao cleanup tái sử dụng môi trường phát triển cục bộ qua symlink ignored cho `.venv` và `frontend/node_modules`.
- Đã lấy checksum 27 file trong `data/runtime/` và `data/results/` ở checkout gốc mà không in nội dung. Nhóm này gồm SQLite, fixture demo runtime và bộ smoke test/thực nghiệm cục bộ. Không có dataset, checkpoint hay calibration được theo dõi riêng trong Git. Calibration có thể nằm trong cấu hình ngoài Git qua `WIFI_DASHBOARD_CONFIG` hoặc cấu hình evaluation. Giữ nguyên mọi file này và mọi bản ghi ngoài Git.
- Hai schema JSONL, firmware profile, fixture test, cấu hình baseline và manifest lịch sử chứa thông tin tái lập. Fixture nhỏ trong `tests/fixtures/` thuộc mã kiểm thử. Probe v1 raw có thể chứa MAC thật. Q1 capture lưu ID đã thay MAC, nhưng registry SQLite và khóa HMAC vẫn thuộc runtime. Local `.env`, khóa HMAC, cấu hình firmware chứa MAC và kết quả cục bộ phải nằm ngoài Git.

## Luồng dữ liệu và phụ thuộc

| Luồng | Lần theo mã |
|---|---|
| Probe v1 | `firmware/sniffer/main/main.c` → UART JSONL → `research.collector.ProbeService` → `backend.app.protocol` → `research.stream` và `research.dashboard` → SQLite/file phiên → `/api/probe` → Legacy / Probe. |
| Q1 | `activity_capture.c` + `activity_frame.c` → UART JSONL v2 → cùng collector, nhánh activity → `backend.app.device_activity_protocol` → `research.device_activity` và `research.activity_records` → `/api/device-csi` → bảng thiết bị. Capture đã giảm thiểu MAC được đọc lại bằng `load_records`. |
| Q2 | Trace metadata → `research.csi_ingestion` → `research.csi_quality` → SQLite và `/api/device-csi/quality`. Có thể ghép capture Q1 theo boot, kênh và clock anchors. Trace Q2 đọc qua API hiện dùng fixture tổng hợp. |
| Q3 | Demo, Q2 replay hoặc batch LIVE đã chuẩn hóa → timeline Q2 + bằng chứng Q1 → `research.csi_reliability` → SQLite và `/api/device-csi/reliability` → timeline và trạng thái Dashboard. |
| Offline | Công cụ nghiên cứu dùng parser/loader cùng thuật toán, cùng schema và cấu hình đã lưu. Các báo cáo và baseline giữ nguyên lệnh `python -m`. |

## Entrypoint, cấu hình và artifact

| Phạm vi | Thành phần đang dùng |
|---|---|
| Runtime | `./run.sh` → `scripts/run.sh` → `scripts.serve` → `backend.app.main:app`. `scripts/setup.sh` dựng venv và `frontend/dist/`. `.env.example` minh họa `WIFI_PROBE_CONFIG`, `WIFI_PROBE_DATA_DIR`, `WIFI_PORT`; cấu hình Dashboard tùy chọn qua `WIFI_DASHBOARD_CONFIG`. |
| Dev/build UI | `npm run dev` → `scripts/dev.mjs` → Uvicorn và Vite. `npm run build` → frontend TypeScript/Vite → `frontend/index.html` và `src/main.tsx`. `vite.config.ts`, `tsconfig.json`, package manifest và lockfile được dùng trực tiếp. |
| Python | `requirements.txt` pin FastAPI, Starlette, Uvicorn, pySerial, Pydantic, NumPy, python-dotenv. `requirements-dev.txt` bổ sung pytest, httpx và matplotlib cho test và báo cáo offline. SQLite thuộc thư viện chuẩn Python. |
| Firmware/CI | `scripts/flash.sh`, `firmware/sniffer/{CMakeLists.txt,sdkconfig.defaults,sdkconfig.fixed,sdkconfig.activity}`, `main/{CMakeLists.txt,Kconfig.projbuild,idf_component.yml}` và `firmware/common/common.h`. ESP-IDF quản lý cJSON và tạo cấu hình cục bộ, component tải về, ELF/BIN. `.github/workflows/check.yml` dùng image ESP-IDF và chạy pytest/npm; không có Dockerfile hay Compose trong repo. |
| Cấu hình nghiên cứu | `configs/probe.json` là mặc định runtime, `demo.json` được fixture generator/API demo dùng, `reference.json` là preset Sherlock, `counting-research.json` cho evaluation và `split.example.json` là mẫu chia tập. File split thực tế được truyền bằng CLI. |
| Test | `tests/conftest.py` thiết lập API fixture; toàn bộ pytest từ root. `tests/evaluation/` kiểm tra benchmark; `tests/fixtures/` gồm JSONL v2, CSI tổng hợp và C native. `tests/dashboard_browser.mjs` dùng Chrome, Playwright và FastAPI thật với runtime tạm. |
| Research | `research.{inspect,diagnose,evaluate,sweep,ie_fingerprint,device_clustering,presence,in_room,experiment,counting_accuracy,csi_ingestion,reliability_evaluation}` có CLI. `scripts.probe_fixture` vừa là CLI sinh demo vừa được API, test và evaluation import. Validator UART v2 dùng `python -m backend.app.device_activity_protocol`. |
| Phân phối source | `scripts/package.py` tạo ZIP source theo quy ước cũ. Audit thấy cách duyệt cây làm việc có thể đưa dữ liệu cục bộ và symlink vào gói. Giữ lệnh và sửa nguồn đầu vào thành snapshot Git đã commit. |

## Phân loại

Bảng dưới kiểm kê đường dẫn tại commit gốc. Các mẫu chỉ bao phủ đúng nhóm ghi kèm. Một mục được di chuyển có thể đồng thời thuộc legacy; nhãn MOVE ghi hành động cleanup. [Ánh xạ và kiểm chứng](MIGRATION_NOTES.md)

| Nhóm | Đường dẫn | Căn cứ |
|---|---|---|
| KEEP | `.env.example`, `package.json`, `requirements*.txt`, `run.sh`, `configs/`, `firmware/` (file theo dõi) | Entrypoint, build, runtime hoặc tái lập nghiên cứu. |
| KEEP | `backend/{__init__.py,app/__init__.py}`, `backend/app/{protocol.py,device_activity_protocol.py,storage.py}` | API, collector, schema, CLI và storage đã có đường dẫn ổn định. |
| KEEP | `research/{__init__,activity_records,collector,csi_ingestion,csi_quality,csi_reliability,device_activity,reliability_demo,reliability_evaluation}.py` | Runtime, Q1/Q2/Q3, demo và evaluation dùng chung. |
| KEEP | `frontend/{index.html,package.json,package-lock.json,tsconfig.json,vite.config.ts}`, `frontend/src/{main.tsx,api.ts,style.css,dashboard.css}` | Vite entry, thiết lập build và CSS dùng chung. |
| KEEP | `scripts/{__init__.py,dev.mjs,flash.sh,probe_fixture.py,run.sh,serve.py,setup.sh}`, `tests/` ngoại trừ test cập nhật đường import | Runtime, cài đặt, fixture, CI, firmware và test. |
| KEEP | `docs/{packet.schema.json,device-activity.schema.json}` | Máy đọc schema; giữ đường dẫn hợp đồng. |
| KEEP | `DAC_TA_DU_AN.md`, `Dac_ta_dinh_dang_du_lieu (2).md` | Giữ đặc tả baseline và thiết kế hệ thống cấp dự án. |
| LEGACY | `research/{cluster_counting,counting_accuracy,counting_report,dashboard,detectors,device_clustering,diagnose,evaluate,experiment,experiment_report,ie_fingerprint,ie_profile,in_room,inspect,presence,stream,sweep}.py` | Baseline Sherlock và nghiên cứu counting/IE/location. Nhiều module vẫn dùng trực tiếp trong runtime, API hoặc CLI. |
| REFACTOR | `.gitignore`, `.github/workflows/check.yml`, `backend/app/main.py`, `frontend/src/Dashboard.tsx`, `scripts/package.py`, `README.md`, `HUONG_DAN_CHAY_VSCODE.md`, `docs/UBUNTU_RUNBOOK.md`, `tests/test_registered_device_monitor.py` | Tổ chức import, bảo vệ dữ liệu, kiểm tra các profile firmware và hướng dẫn cấu trúc. |
| MOVE | Các router FastAPI, panel React theo feature và tài liệu ở bảng dưới | Gom theo ranh giới đang dùng; thay tham chiếu cùng nhóm. |
| GENERATED | `__pycache__/`, `.pytest_cache/`, `.venv/`, `frontend/{dist,node_modules}/`, output build/managed components/lock ESP-IDF | Công cụ có thể tạo lại. Giữ trên máy hiện tại và dùng ignore. |
| UNKNOWN | Runtime, datasets, calibration, model, split thực, kết quả và cấu hình riêng ngoài Git; thư mục metadata công cụ cục bộ | Nội dung và quyền sở hữu phụ thuộc buổi thu hoặc máy. Giữ tại chỗ. |

### Đường dẫn MOVE

| Trước | Sau |
|---|---|
| `backend/app/csi_quality_api.py` | `backend/app/api/csi_quality.py` |
| `backend/app/csi_reliability_api.py` | `backend/app/api/csi_reliability.py` |
| `backend/app/device_activity_api.py` | `backend/app/api/device_activity.py` |
| `backend/app/probe_api.py` | `backend/app/api/probe.py` |
| `docs/ALGORITHM.md` | `docs/legacy/ALGORITHM.md` |
| `docs/ARCHITECTURE.md` | `docs/architecture/ARCHITECTURE.md` |
| `docs/BOARD_SETUP.md` | `docs/implementation/BOARD_SETUP.md` |
| `docs/COUNTING_ACCURACY_RESEARCH.md` | `docs/experiments/COUNTING_ACCURACY_RESEARCH.md` |
| `docs/CSI_CHANNEL_QUALITY.md` | `docs/implementation/CSI_CHANNEL_QUALITY.md` |
| `docs/CSI_RELIABILITY_DESIGN.md` | `docs/implementation/CSI_RELIABILITY_DESIGN.md` |
| `docs/CURRENT_SYSTEM_AUDIT.md` | `docs/legacy/CURRENT_SYSTEM_AUDIT.md` |
| `docs/DASHBOARD.md` | `docs/legacy/DASHBOARD.md` |
| `docs/DASHBOARD_DEVICE_CSI.md` | `docs/implementation/DASHBOARD_DEVICE_CSI.md` |
| `docs/DASHBOARD_GUIDE.md` | `docs/legacy/DASHBOARD_GUIDE.md` |
| `docs/DEVELOPMENT_ROADMAP.md` | `docs/legacy/DEVELOPMENT_ROADMAP.md` |
| `docs/DEVICE_ACTIVITY_FIRMWARE.md` | `docs/implementation/DEVICE_ACTIVITY_FIRMWARE.md` |
| `docs/DEVICE_CLUSTERING.md` | `docs/legacy/DEVICE_CLUSTERING.md` |
| `docs/DEVICE_CSI_MVP_PLAN.md` | `docs/legacy/DEVICE_CSI_MVP_PLAN.md` |
| `docs/DE_XUAT_NHANH_THIET_BI.md` | `docs/legacy/DE_XUAT_NHANH_THIET_BI.md` |
| `docs/EVALUATION_RESULTS.md` | `docs/experiments/EVALUATION_RESULTS.md` |
| `docs/EXPERIMENT_PLAN.md` | `docs/experiments/EXPERIMENT_PLAN.md` |
| `docs/EXPERIMENT_PROTOCOL.md` | `docs/experiments/EXPERIMENT_PROTOCOL.md` |
| `docs/FINAL_VERIFICATION_REPORT.md` | `docs/implementation/FINAL_VERIFICATION_REPORT.md` |
| `docs/IE_FINGERPRINT_DESIGN.md` | `docs/legacy/IE_FINGERPRINT_DESIGN.md` |
| `docs/IN_ROOM_ESTIMATION.md` | `docs/legacy/IN_ROOM_ESTIMATION.md` |
| `docs/KNOWN_LIMITATIONS.md` | `docs/implementation/KNOWN_LIMITATIONS.md` |
| `docs/MAC_TRACKING.md` | `docs/legacy/MAC_TRACKING.md` |
| `docs/MVP_IMPLEMENTATION_STATUS.md` | `docs/implementation/MVP_IMPLEMENTATION_STATUS.md` |
| `docs/PHAN_TICH_THONG_SO_DASHBOARD.md` | `docs/legacy/PHAN_TICH_THONG_SO_DASHBOARD.md` |
| `docs/PLAN.md` | `docs/legacy/PLAN.md` |
| `docs/PRESENCE_STATE_MACHINE.md` | `docs/legacy/PRESENCE_STATE_MACHINE.md` |
| `docs/PROTOCOL.md` | `docs/architecture/PROTOCOL.md` |
| `docs/REGISTERED_DEVICE_MONITOR.md` | `docs/implementation/REGISTERED_DEVICE_MONITOR.md` |
| `docs/REUSE_AUDIT.md` | `docs/legacy/REUSE_AUDIT.md` |
| `docs/UPGRADE.md` | `docs/legacy/UPGRADE.md` |
| `docs/VALIDATION.md` | `docs/legacy/VALIDATION.md` |
| `docs/build-manifest.json` | `docs/legacy/build-manifest.json` |
| `frontend/src/DeviceCsiPanel.tsx` | `frontend/src/device-csi/DeviceCsiPanel.tsx` |
| `frontend/src/DeviceOverview.tsx` | `frontend/src/legacy-probe/DeviceOverview.tsx` |
| `frontend/src/ProbePanel.tsx` | `frontend/src/legacy-probe/ProbePanel.tsx` |
| `frontend/src/ResearchPanel.tsx` | `frontend/src/legacy-probe/ResearchPanel.tsx` |
| `frontend/src/ScopePanel.tsx` | `frontend/src/legacy-probe/ScopePanel.tsx` |
| `frontend/src/device-csi.css` | `frontend/src/device-csi/device-csi.css` |

## DELETE_CANDIDATE

Danh sách trống. Các CLI ít tham chiếu vẫn có vai trò phân phối hoặc tái lập kết quả; manifest cũ là hồ sơ có hash. Dữ liệu ngoài Git giữ UNKNOWN. Không đề nghị xóa source, tài liệu nghiên cứu hay dữ liệu.
