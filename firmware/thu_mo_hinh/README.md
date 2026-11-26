# Thử mô hình động tác trên ESP32-S3 (cách B, một board)

Đo xem board S3 N16R8 có chạy kịp mô hình động tác không, và kết quả có giống Python không – trước khi viết firmware
RX đầy đủ. Chưa bật Wi‑Fi / CSI: chạy trên các window CSI thô đã nhúng sẵn.

| File | Việc |
|---|---|
| `main/dac_trung.c` | Bản C của `features.robust_features` (25 cột, window 3 s) – đổi bên nào thì đổi cả bên kia |
| `main/mo_hinh.c` | Chạy XGBoost dạng bảng nút (đọc thẳng từ flash) |
| `main/kiem_tra.c` | Chạy mọi window đối chiếu: tính cột, chạy mô hình, so với Python, đo thời gian |
| `main/main.c` | Chương trình trên board: in kết quả qua USB mỗi 10 s |
| `host/may_tinh.c` | Cùng phép thử, chạy trên máy tính |
| `main/mo_hinh.bin`, `main/du_lieu_thu.bin` | Sinh bởi `laptop/xuat_board.py` (không đưa lên Git) |

```bash
cd laptop && python xuat_board.py                      # train + xuất mô hình RX1 và 40 window đối chiếu
cd ../firmware/thu_mo_hinh/host
gcc -O2 -I../main may_tinh.c ../main/kiem_tra.c ../main/dac_trung.c ../main/mo_hinh.c -lm -o may_tinh
./may_tinh ../main/mo_hinh.bin ../main/du_lieu_thu.bin   # chạy trên máy tính
cd .. && . ~/.espressif/tools/activate_idf_v6.1.sh && idf.py build
idf.py -p /dev/ttyACM0 flash monitor                     # cần board; Ctrl+] để thoát monitor
```

Kết quả trên **ESP32-S3 N16R8 thật** (24/11/2026, 240 MHz, chưa bật Wi‑Fi; 40 window CSI mô phỏng của 2 buổi không
dùng để train):

| | Kết quả |
|---|---|
| Khớp Python | 40/40 window cùng lớp; xác suất lệch ≤ 1,2·10⁻⁷; từng cột lệch ≤ 1,1·10⁻⁵ |
| Tính 25 cột mỗi window 3 s | **69 ms** (lớn nhất 73 ms) – lần đầu 491 ms: gọi cos/sin trong vòng lặp, double giả lập |
| Chạy mô hình (1800 cây, 71 nghìn nút) | **13 ms** khi chép bảng nút sang PSRAM lúc khởi động; 33 ms nếu đọc thẳng từ flash (DIO) |
| Tổng mỗi window, trượt 0,5 s | ~82 ms → ~16 % một nhân |
| Bộ nhớ | App 2,4 MB / 6 MB; bảng nút 1,15 MB trong PSRAM; lúc tính cần ~230 KB RAM trong chip (còn thấp nhất 122 KB) |

Chưa đo: lúc vừa thu CSI 100 gói/s vừa tính (Wi‑Fi chiếm một phần nhân 0), và hai mô hình window 6 s (212 cột).
