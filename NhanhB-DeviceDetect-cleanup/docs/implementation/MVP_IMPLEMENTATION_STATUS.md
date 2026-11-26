# Trạng thái triển khai MVP

Audit bắt đầu trên `feature/device-csi-reliability` tại `fada6128628fab20965406c8c2a079da34f931a4`. Cây làm việc có thay đổi Giai đoạn 1–4, gồm các file mới chưa track. Phiên triển khai tiếp nối trực tiếp các file đó.

| Giai đoạn | Mã và test chứng minh | Kiểm chứng còn thiếu |
|---|---|---|
| 1 · Audit | Pipeline Probe v1, parser, record/replay, SQLite, FastAPI, React. Suite ban đầu đạt 176 test. [Audit](../legacy/REUSE_AUDIT.md) | Đo hiệu năng RF với bố trí mới. |
| 2 · SNF v2 | Mode fixed và Probe hopping/fixed. Test native C và schema UART. [Firmware](DEVICE_ACTIVITY_FIRMWARE.md) | Thu Data/Control và Block Ack trên router thật. |
| 3 · Q1 | Registry có HMAC, ba trạng thái, PTY qua pySerial, sanitized capture và replay. [Q1](REGISTERED_DEVICE_MONITOR.md) | Thử Vivo Y20 và thiết bị khác trên board thật. |
| 4 · Q2 | Metadata adapter, clock fit, timeline synthetic 1/10 s và Q1 capture. [Q2](CSI_CHANNEL_QUALITY.md) | Mapping BOOT/CSI/STAT và đo loss/clock với RX thật. |
| 5 · Q3 | Engine tư vấn, session LIVE/REPLAY/DEMO, SQLite, stale/fallback, version và rules. [Q3](CSI_RELIABILITY_DESIGN.md) | Adapter phần cứng LIVE và hiệu chuẩn. |
| 6 · Dashboard | Màn hình Device & CSI và Legacy cùng app. Browser test chạy FastAPI thật và kiểm tra provenance, giao diện mobile và lỗi API. [Dashboard](DASHBOARD_DEVICE_CSI.md) | Chạy dashboard phục vụ một buổi thu board thật. |
| 7 · Tích hợp | Chuỗi PTY → Q1; capture Q1 → Q2 → Q3 → UI; runner A/B/C chia theo session. [Kế hoạch thí nghiệm](../experiments/EXPERIMENT_PLAN.md) | Dataset có nhãn và dự báo A/B/C; tích hợp cảnh báo nhánh người. |

Xem lệnh và kết quả của kiểm tra cuối tại [Final Verification](FINAL_VERIFICATION_REPORT.md).
