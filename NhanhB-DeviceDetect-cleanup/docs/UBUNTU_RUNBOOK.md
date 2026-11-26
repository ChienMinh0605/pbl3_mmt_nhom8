# Ubuntu Runbook

## Cài và chạy

Repository dùng Python 3.12, Node.js 22+, npm và ESP-IDF 5.5.4 cho build ESP32-C3. Từ gốc repo:

```bash
bash scripts/setup.sh
./run.sh
```

Mở URL in trên terminal. Tùy chọn chạy Uvicorn và Vite cùng lúc trong chế độ phát triển bằng `npm run dev`, ở backend cổng 8000 và frontend cổng 5173. OpenAPI nằm tại `/docs` của backend.

## Build firmware và flash thủ công

Mặc định firmware Probe xuất JSONL v1. Với Q1 chọn profile activity và cấu hình kênh router/MAC theo [hướng dẫn firmware](implementation/DEVICE_ACTIVITY_FIRMWARE.md). Dùng cấu hình riêng để tránh ghi đè profile đang dùng.

```bash
source ~/esp/esp-idf/export.sh
cd firmware/sniffer
idf.py -B build/hopping -D SDKCONFIG=sdkconfig.hopping.local \
  -D SDKCONFIG_DEFAULTS=sdkconfig.defaults build
idf.py -B build/fixed -D SDKCONFIG=sdkconfig.fixed.local \
  -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.fixed' build
idf.py -B build/activity -D SDKCONFIG=sdkconfig.activity.local \
  -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.activity' menuconfig
idf.py -B build/activity -D SDKCONFIG=sdkconfig.activity.local \
  -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.activity' build
```

Chỉ sau khi kiểm tra đúng board, cổng, profile và quyền USB, đóng tiến trình đang giữ cổng. Từ thư mục firmware chạy lệnh dưới với `PORT` thay bằng cổng đã xác nhận. Lệnh ghi firmware vào board.

```bash
idf.py -B build/activity -D SDKCONFIG=sdkconfig.activity.local \
  -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.activity' -p PORT -b 460800 flash
```

## Demo và dữ liệu

- Mở **Device & CSI** và bấm **Chạy demo Device & CSI** để xem CSI ổn định/suy giảm và chuyển giữa CSI-only/CSI+Device. Đổi cửa sổ 1/10 giây rồi trở về **Nguồn hiện tại** để kiểm tra LIVE trống.
- Dùng [registry Q1](implementation/REGISTERED_DEVICE_MONITOR.md) để đăng ký có đồng ý và thu USB. Muốn dùng fixture Q2 qua API theo [hướng dẫn Q2](implementation/CSI_CHANNEL_QUALITY.md), lấy ID replay đó và gọi `POST /api/device-csi/reliability/sessions` với `{"mode":"REPLAY","quality_replay_id":"<id>"}`. Chọn phiên trong UI.
- Với adapter LIVE chuẩn hóa, dùng hợp đồng [Q3](implementation/CSI_RELIABILITY_DESIGN.md). Không lấy số đo của DEMO gắn nhãn LIVE. Tab **Legacy / Probe** chứa chức năng Probe đã có.

## Dữ liệu cục bộ và đóng gói

Runtime mặc định dùng `data/runtime/`. Để thử trong thư mục runtime riêng, đặt `WIFI_PROBE_DATA_DIR` tới đường dẫn tuyệt đối của thư mục đó. Muốn phát lại dữ liệu từ checkout khác, giữ nguyên SQLite, khóa registry và cây file phiên khi lấy bản sao. Giữ capture, calibration và kết quả cục bộ dưới `data/` hoặc ngoài checkout; dùng `configs/*.local.json` cho cấu hình riêng. [Ghi chú migration](MIGRATION_NOTES.md)

Từ repo Git, chạy `.venv/bin/python -m scripts.package` để tạo `../output/WiFi_Device_Sherlock_Source.zip` từ commit `HEAD`. Gói ZIP chỉ chứa snapshot đã commit.

## Kiểm tra

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
npm --prefix frontend ci
npm run build
.venv/bin/python -m backend.app.device_activity_protocol tests/fixtures/device_activity_v2.jsonl
.venv/bin/python -m research.csi_ingestion tests/fixtures/csi_quality_synthetic.json
npm install --prefix /tmp/pbl3-dashboard-browser playwright
DASHBOARD_PLAYWRIGHT_MODULE=/tmp/pbl3-dashboard-browser/node_modules/playwright/index.mjs \
  node --test tests/dashboard_browser.mjs
```

Build frontend bao gồm typecheck. Browser test dùng Chrome tại `/usr/bin/google-chrome` mặc định. Đặt `DASHBOARD_TEST_CHROME` hoặc `DASHBOARD_TEST_PYTHON` nếu đường dẫn môi trường khác. Repo hiện chưa cấu hình lint.
