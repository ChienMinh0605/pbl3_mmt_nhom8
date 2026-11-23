# Đặc tả định dạng dữ liệu – Đề tài Wi‑Fi Sensing (Nhóm 8)

**Phiên bản:** v0.3 (1 TX phát ESP‑NOW broadcast, 2 RX; nhãn động tác; window động tác 3 s – xem `KE_HOACH_NHANH_NGUOI.md`)

> Phần đổi ở v0.3 được đánh dấu **(v0.3)**. Code phía laptop (`logger.py`, `nhan.py`, `kiem_tra_buoi_thu.py`,
> `features.py`, `train.py`, dashboard) và mô phỏng `mo_phong.py` đã theo v0.3; firmware chưa có.
**Người soạn:** Chiến

---

## 0. File này để làm gì?

Ba người làm ba phần khác nhau, nhưng dữ liệu phải chạy xuyên qua cả ba:

- **Tiên** viết firmware TX và RX → các RX (RX1, RX2) gửi dữ liệu CSI lên laptop → Tiên tiền xử lý, trích đặc trưng.
- **Phúc** viết firmware #3 → #3 gửi dữ liệu Probe Request lên laptop → Phúc chạy máy trạng thái Sherlock.
- **Chiến** đọc dữ liệu từ cả hai board, ghi thành file theo từng buổi thu, train mô hình và làm dashboard.

File này chốt **dữ liệu trông như thế nào ở mỗi chỗ giao nhau**: ESP32 in ra dòng gì, laptop lưu file gì, cột nào tên gì. Ai cũng làm theo file này thì khi ghép lại sẽ khớp, không phải sửa code của nhau.

> Nguyên tắc: muốn đổi định dạng thì sửa file này trước, báo cả nhóm, tăng số phiên bản, rồi mới sửa code.

---

## 1. Đường đi của dữ liệu

```
 ESP32-C3 TX ··· ESP-NOW broadcast ~100 gói/s ···►  RX1, RX2 cùng thu CSI của cùng một gói

 ESP32-S3 RX1 (thu CSI)    ──USB──┐
 ESP32-S3 RX2 (thu CSI)    ──USB──┼──► logger.py (laptop) ──► data/raw/<buổi thu>/
 ESP32-C3 #3 (sniffer)     ──USB──┘          ▲                 csi.csv, probe.csv, stat.csv
                                             │                 labels.csv, meta.json
                                  phím ghi nhãn (labels)
                                                                      │
                     ┌────────────────────────────────────────────────┤
                     ▼                                                ▼
        Tiên: tiền xử lý + đặc trưng                    Phúc: máy trạng thái Sherlock
        → data/features/<buổi thu>.csv                  → data/device/<buổi thu>.csv
                     │                                                │
                     └──────────────► Chiến: train mô hình, dashboard ◄┘
```

TX **không gửi dữ liệu lên laptop**. Nó chỉ cần in dòng `BOOT` (mục 3.1) để nhóm biết MAC của nó.

**(v0.3)** Bỏ cách cũ "TX làm SoftAP, RX kết nối và ping 100 Hz". TX phát **ESP‑NOW broadcast** trên một kênh cố
định, mọi RX nghe cùng kênh và lấy CSI của các gói đó. Firmware sửa từ ví dụ `csi_send` / `csi_recv` của repo
Espressif **esp‑csi**. Làm theo bậc: 1 RX chạy thông trước, rồi mới nạp cùng firmware cho RX2.

---

## 2. Quy ước chung cho dữ liệu ESP32 gửi lên laptop

| Quy ước | Giá trị | Vì sao |
|---|---|---|
| Cổng | USB Serial/JTAG có sẵn trên ESP32-C3 và ESP32-S3 | Nhanh hơn UART 115200, không cần mạch chuyển USB |
| Dạng dữ liệu | **Văn bản**, mỗi bản ghi một dòng, kết thúc bằng `\n` | Mở serial monitor là đọc được, dễ gỡ lỗi |
| Phân cách | Dấu phẩy `,`, không có dấu cách | Đọc bằng `line.split(",")` |
| Từ khoá đầu dòng | `BOOT`, `CSI`, `PRB`, `STAT` | Laptop biết dòng thuộc loại nào |
| Dòng khác | Laptop **bỏ qua** | Log `ESP_LOGI` để gỡ lỗi vẫn in thoải mái |
| Thời gian trên ESP | `t_us` = `esp_timer_get_time()`, micro giây tính từ lúc bật board | Có sẵn, đủ chính xác |
| Thời gian trên laptop | `host_time` = `time.time()`, giây (số thực, Unix time) | Dùng để ghép dữ liệu của các RX, SNF và nhãn |
| Định dạng MAC | `aa:bb:cc:dd:ee:ff`, chữ thường | Thống nhất để so sánh |

**Về tốc độ:** một dòng `CSI` dài khoảng 330 ký tự. Ở 100 dòng/giây là khoảng 33 KB/giây. USB Serial/JTAG dự kiến đáp ứng được, nhưng **phải kiểm tra ở buổi kiểm thử tuần đầu** (xem số `n_queue_drop` trong dòng `STAT`). Nếu không kịp, phiên bản sau sẽ chuyển sang dạng nhị phân.

---

## 3. Các loại dòng ESP32 gửi lên

### 3.1. `BOOT` – mọi board (TX, RX1, RX2, SNF)

In **khi khởi động** và **lặp lại mỗi 30 giây**, để logger bật sau vẫn nhận được.

```
BOOT,<board>,<fw>,<mac_sta>,<mac_ap>,<channel>
```

| Trường | Ý nghĩa | Ví dụ |
|---|---|---|
| `board` | **(v0.3)** `TX`, `RX1`, `RX2` (`RX3` nếu dùng) hoặc `SNF`. Tên RX đặt trong menuconfig, mỗi board một tên | `RX1` |
| `fw` | Phiên bản firmware | `0.3` |
| `mac_sta` | MAC giao diện STA của board (với TX: MAC dùng để phát ESP‑NOW) | `64:e8:33:01:02:03` |
| `mac_ap` | **(v0.3)** Với RX: MAC của TX đang lọc theo. Board khác: `-` | `1a:00:00:00:00:00` |
| `channel` | Kênh hiện tại | `6` |

Ví dụ:
```
BOOT,TX,0.3,1a:00:00:00:00:00,-,6
BOOT,RX1,0.3,64:e8:33:01:02:03,1a:00:00:00:00:00,6
BOOT,RX2,0.3,64:e8:33:01:02:04,1a:00:00:00:00:00,6
BOOT,SNF,0.3,64:e8:33:05:06:07,-,1
```

Dùng để: logger biết cổng USB nào là RX nào, biết MAC của TX, và lập **danh sách MAC loại trừ** cho nhánh thiết bị.

### 3.2. `CSI` – RX1, RX2 (Tiên phụ trách)

Mỗi gói ESP‑NOW nhận được từ TX sinh ra một dòng.

```
CSI,<seq>,<t_us>,<rx_seq>,<src_mac>,<rssi>,<noise_floor>,<channel>,<sig_mode>,<cwb>,<first_word_invalid>,<len>,<csi_hex>
```

| Trường | Lấy từ (`wifi_csi_info_t`) | Ý nghĩa |
|---|---|---|
| `seq` | bộ đếm trên ESP | Tăng 1 sau mỗi dòng `CSI` gửi đi. Laptop dựa vào đây để biết có mất dòng hay không |
| `t_us` | `esp_timer_get_time()` | Thời điểm nhận khung, micro giây |
| `rx_seq` | `rx_seq` | **(v0.3)** Số thứ tự 802.11 của gói. Cùng một gói TX thì các RX có cùng `rx_seq` → dùng để ghép RX1 với RX2. Cần kiểm tra ở buổi kiểm thử là trường này có giá trị đúng với gói ESP‑NOW broadcast |
| `src_mac` | `mac` | MAC nguồn của khung |
| `rssi` | `rx_ctrl.rssi` | dBm |
| `noise_floor` | `rx_ctrl.noise_floor` | dBm |
| `channel` | `rx_ctrl.channel` | Kênh nhận |
| `sig_mode` | `rx_ctrl.sig_mode` | 0: non-HT (11b/g), 1: HT (11n) |
| `cwb` | `rx_ctrl.cwb` | 0: 20 MHz, 1: 40 MHz |
| `first_word_invalid` | `first_word_invalid` | 1 nếu 4 byte đầu của CSI không hợp lệ (giới hạn phần cứng ESP32) |
| `len` | `len` | Số byte CSI |
| `csi_hex` | `buf` | `len` byte CSI viết dưới dạng hex liền nhau (2 ký tự mỗi byte) |

**Cấu hình CSI thống nhất** (`wifi_csi_config_t`). **(v0.3)** Nếu ví dụ esp‑csi dùng giá trị khác bảng dưới thì theo esp‑csi và sửa lại bảng:

| Trường | Giá trị | Ghi chú |
|---|---|---|
| `lltf_en` | `true` | Chỉ lấy phần LLTF (64 sóng mang con) |
| `htltf_en` | `false` | |
| `stbc_htltf2_en` | `false` | |
| `ltf_merge_en` | `false` | |
| `channel_filter_en` | `false` | Giữ các sóng mang con độc lập, không làm mượt |
| `manu_scale` | `false` | Tự động co giãn |

Với cấu hình này, **`len` dự kiến là 128 byte** (64 sóng mang con × 2 byte) **hoặc 104 byte** (52 sóng mang con,
khi driver đã bỏ các sóng mang con rỗng). Bộ dữ liệu WiFall/WiCount (ESP32‑S3, esp‑csi, `sig_mode` 0) có
`len` = 104. **(v0.3)** Giữ cấu hình CSI mặc định của esp‑csi để dữ liệu của nhóm so được với hai bộ này; ghi `len`
thực tế sau buổi kiểm thử vào đây.

**Cách đọc `csi_hex`:** mỗi sóng mang con chiếm 2 byte có dấu (`int8`): **byte đầu là phần ảo, byte sau là phần thực** (theo tài liệu ESP-IDF). Biên độ = √(thực² + ảo²).
Luôn đọc **theo cặp** `(byte 2i, byte 2i+1)`; không ghép lệch cặp (script mẫu `process1.py` của WiFall mắc lỗi này).

**Lọc trên ESP (v0.3):** chỉ gửi dòng khi `src_mac` trùng MAC của TX. MAC này **đặt trong menuconfig** (theo cách
ví dụ esp‑csi đặt MAC phát cho `csi_send` – cần kiểm tra), **không ghi cứng trong mã nguồn**, và được in ở trường
`mac_ap` của dòng `BOOT`.

Ví dụ (rút gọn phần hex):
```
CSI,1532,48211934,2207,1a:00:00:00:00:00,-42,-95,6,0,0,1,104,0000000003fa05f8...
```

### 3.3. `PRB` – ESP32-C3 #3 (Phúc phụ trách)

Mỗi Probe Request bắt được sinh ra một dòng.

```
PRB,<seq>,<t_us>,<src_mac>,<rssi>,<channel>
```

| Trường | Ý nghĩa |
|---|---|
| `seq` | Bộ đếm trên ESP, tăng 1 sau mỗi dòng `PRB` |
| `t_us` | Thời điểm nhận, micro giây |
| `src_mac` | MAC nguồn (Address 2, byte 10–15 của header) |
| `rssi` | `rx_ctrl.rssi`, dBm (chỉ ghi log, không dùng để quyết định) |
| `channel` | Kênh sniffer đang nghe khi bắt được khung |

**Lọc trên ESP:** chỉ lấy khung quản lý có subtype 4 (byte đầu của frame control là `0x40`).

MAC được gửi nguyên dạng qua USB. **Laptop băm MAC trước khi ghi xuống đĩa** (mục 4.3), nên MAC thật không bao giờ được lưu.

Ví dụ:
```
PRB,88,61230011,9a:31:87:22:fd:08,-67,6
```

### 3.4. `STAT` – RX1, RX2 và SNF, mỗi giây một dòng

```
STAT,<t_us>,<board>,<n_rx>,<n_filtered>,<n_queue_drop>,<channel>
```

| Trường | Với `RX1`, `RX2` | Với `SNF` |
|---|---|---|
| `n_rx` | Số dòng `CSI` đã gửi trong giây vừa qua | Số dòng `PRB` đã gửi |
| `n_filtered` | Số khung bị bỏ vì không phải MAC của TX | Số khung quản lý không phải Probe Request |
| `n_queue_drop` | Số bản ghi mất vì queue đầy | Như bên trái |
| `channel` | Kênh hiện tại | Kênh đang nghe |

Dùng cho buổi kiểm thử tuần đầu (tốc độ CSI thực tế) và đèn báo "hệ thống khoẻ" trên dashboard.

---

## 4. File của mỗi buổi thu (logger trên laptop ghi ra)

### 4.1. Thư mục

```
data/raw/<session_id>/
    meta.json      thông tin buổi thu
    csi.csv        các dòng CSI
    probe.csv      các dòng PRB (MAC đã băm)
    stat.csv       các dòng STAT
    boot.csv       các dòng BOOT
    labels.csv     nhãn ghi bằng phím
```

`session_id` có dạng `YYYYMMDD_HHMM_<tên-ngắn>`, ví dụ `20261112_1430_phongA`.

### 4.2. `csi.csv`, `stat.csv`, `boot.csv`

Giữ nguyên các trường như mục 3, **thêm cột `host_time` ở đầu**. Dòng tiêu đề là tên các trường.

**(v0.3)** `csi.csv` thêm cột `board` (`RX1`, `RX2`, …) ngay sau `host_time`: mọi RX ghi chung một file, lấy tên
board từ dòng `BOOT` của cổng đó. `stat.csv` giữ nguyên vì dòng `STAT` đã có trường `board`.

```
host_time,board,seq,t_us,rx_seq,src_mac,rssi,noise_floor,channel,sig_mode,cwb,first_word_invalid,len,csi_hex
1762932600.1234,RX1,1532,48211934,2207,1a:00:00:00:00:00,-42,-95,6,0,0,1,104,0000000003fa05f8...
1762932600.1241,RX2,1498,50110220,2207,1a:00:00:00:00:00,-47,-95,6,0,0,1,104,00000000fe0a0712...
```

### 4.3. `probe.csv`

```
host_time,seq,t_us,mac_hash,local_admin,rssi,channel,excluded
```

| Cột | Ý nghĩa |
|---|---|
| `mac_hash` | 12 ký tự hex đầu của SHA-256(`salt` + MAC). Cùng một MAC luôn cho cùng `mac_hash` |
| `local_admin` | Bit U/L của MAC: 1 = địa chỉ quản lý cục bộ (thường là MAC ngẫu nhiên) |
| `excluded` | 1 nếu MAC nằm trong danh sách loại trừ (board của nhóm, laptop demo). Máy trạng thái bỏ qua các dòng này |

`salt` để trong file cấu hình cục bộ, **không đưa lên Git và không ghi vào thư mục dữ liệu**.

### 4.4. `labels.csv` – nhãn ghi bằng phím

```
host_time,event,value
```

| `event` | `value` | Phím | Ý nghĩa |
|---|---|---|---|
| `STATE` | `EMPTY` | `E` | Phòng trống |
| `STATE` | `ACTIVE` | `A` (hoặc `W`) | Người được giám sát đi lại, sinh hoạt |
| `STATE` | `STILL` | `S` | Ngồi, đứng hoặc nằm yên, thở bình thường |
| `STATE` | `DOWN` | `D` | Nằm bất động sau khi ngã – bấm ngay sau `F` |
| `STATE` | `BREATH_ABN` | `B` | Yên nhưng thở bất thường (nhanh, chậm hoặc nín thở theo kịch bản) |
| `STATE` | `NEIGHBOR` | `N` | Phòng trống, có người đi lại ở phòng bên (kiểm tra báo động giả) |
| `STATE` | `PAUSE` | `P` | Đang sắp xếp, không dùng đoạn này |
| `ACTION` | `FALL` | `F` | **(v0.3)** Té ngã – bấm **lúc bắt đầu** ngã |
| `ACTION` | `SIT_DOWN` | `G` | **(v0.3)** Ngồi xuống |
| `ACTION` | `STAND_UP` | `U` | **(v0.3)** Đứng dậy |
| `ACTION` | `LIE_DOWN` | `L` | **(v0.3)** Nằm xuống (chủ động, không phải ngã) |
| `ACTION` | `PICK_UP` | `C` | **(v0.3)** Cúi nhặt đồ – động tác dễ nhầm với ngã |
| `COUNT` | `+1` / `-1` | `+` / `-` | Có người vào / ra (số người trong phòng, gồm cả khách) |
| `RATE` | số nhịp/phút | `R` | **(v0.3)** Nhịp thở đáp án (theo app máy đếm nhịp); gõ số rồi Enter |
| `NOTE` | chữ tự do | `T` | Ghi chú |

Một nhãn `STATE` có hiệu lực **từ thời điểm bấm đến lần bấm `STATE` tiếp theo**.

**(v0.3)** `ACTION` là **sự kiện ngắn, không đổi `STATE`**. Đoạn động tác quy ước là `[t − 0,5 s, t + 2,5 s]`
(`t` = lúc bấm; 3 giây, bằng độ dài đoạn của WiFall). Sau `FALL` bấm `D`; sau các động tác khác bấm `S` hoặc `A`
theo tình huống. `FALL` không còn là `STATE` như ở v0.2.

**Tư thế sau động tác** (để suy ra tư thế hiện tại): `SIT_DOWN` → ngồi; `STAND_UP`, `PICK_UP` → đứng;
`LIE_DOWN`, `FALL` → nằm.

`RATE` có hiệu lực từ lúc bấm đến lần `RATE` tiếp theo hoặc lần đổi sang `STATE` khác `STILL` / `DOWN` / `BREATH_ABN`.
Nín thở thì ghi `RATE` = `0`.

`STATE` mô tả **hoạt động của người được giám sát**. **Số người trong phòng** (khách, người chăm sóc) là thông tin
riêng, lấy từ các sự kiện `COUNT` – không còn nhãn `MULTI`.

**Quy đổi** (định nghĩa trong `laptop/nhan.py`, mọi script dùng chung):

| Nhãn chi tiết | `label` – có người | `activity` – mức hoạt động |
|---|---|---|
| `EMPTY`, `NEIGHBOR` | 0 | 0 – trống |
| `ACTIVE` | 1 | 1 – hoạt động |
| `STILL`, `DOWN`, `BREATH_ABN` | 1 | 2 – yên |
| `PAUSE` | bỏ | bỏ |

### 4.5. `meta.json`

```json
{
  "session_id": "20261112_1430_phongA",
  "room": "Phòng A, tầng 2",
  "tx_rx_distance_m": 3.0,
  "channel": 6,
  "members": ["Chiến", "Tiên", "Phúc"],
  "simulated": false,
  "ports": {"RX1": "/dev/ttyACM0", "RX2": "/dev/ttyACM1", "SNF": "/dev/ttyACM2"},
  "notes": "",
  "fw": {"RX1": "0.3", "RX2": "0.3", "SNF": "0.3"},
  "spec_version": "0.3",
  "stats": {
    "duration_s": 1800.2,
    "lines": {"BOOT": 180, "CSI": 359740, "PRB": 2301, "STAT": 5400},
    "lost_by_seq": {"RX1/CSI": 12, "RX2/CSI": 30},
    "bad_lines": 0,
    "label_events": 9
  }
}
```

- `fw` lấy từ các dòng `BOOT` nhận được (TX không nối USB nên thường không có).
- **(v0.3)** Khoá trong `ports`, `fw`, `lost_by_seq` là tên board trong dòng `BOOT`.
- `stats` chỉ có khi logger kết thúc bình thường. Thiếu `stats` nghĩa là buổi thu bị ngắt giữa chừng; dữ liệu đã ghi vẫn dùng được.
- `simulated: true` là dữ liệu giả, **không dùng để train**.

---

## 5. File đặc trưng (Tiên → Chiến)

```
data/features/<session_id>.csv
data/features/feature_meta.json
```

Mỗi dòng là **một window**:

| Cột | Ý nghĩa |
|---|---|
| `session_id` | Mã buổi thu (dùng để chia train/test theo buổi) |
| `win_start`, `win_end` | `host_time` đầu và cuối window |
| `n_samples` | Số mẫu CSI trong window |
| `valid` | 1 nếu `n_samples` ≥ 70% số mẫu dự kiến |
| `label_detail` | Một nhãn `STATE` ở mục 4.4 |
| `label` | 0 hoặc 1 – có người (bảng quy đổi mục 4.4) |
| `activity` | 0 / 1 / 2 – trống / hoạt động / yên |
| `n_people` | Số người trong phòng tại giữa window, tính từ các sự kiện `COUNT` |
| `breath_rate` | **(v0.3)** Nhịp thở đáp án (`RATE`) tại giữa window; để trống nếu không có |
| `rssi_var`, `rssi_mad`, `rssi_range`, `rssi_iqr` | 4 đặc trưng của RSSI |
| `csi_var_k`, `csi_mad_k`, `csi_range_k`, `csi_iqr_k` | 4 đặc trưng của sóng mang con thứ `k`. `k` là **vị trí sóng mang con trong `csi_hex`** (byte `2k`, `2k+1`), viết 2 chữ số (`csi_var_07`), để tên cột không đổi khi danh sách sóng mang con giữ lại thay đổi |

**(v0.3) Nhiều RX:** mỗi cột đặc trưng (`rssi_*`, `csi_*`, `n_samples`) có **tiền tố tên board**, ví dụ `rx1_csi_var_07`,
`rx2_rssi_mad`, `rx1_n_samples`. `valid` = 1 khi **mọi** RX dùng trong file đều đạt ngưỡng. Muốn so "1 RX với 2 RX"
thì chọn cột theo tiền tố, không cần tạo file riêng.

Quy tắc:
- Window **cắt ngang chỗ đổi nhãn** thì bỏ, vì không biết gán nhãn nào.
- Window nằm trong đoạn `PAUSE` thì bỏ.
- Window có `valid = 0` vẫn ghi ra file (để thống kê), mô hình sẽ lọc bỏ.

### 5.2. **(v0.3)** File window động tác (phát hiện ngã và động tác)

```
data/features_action/<session_id>.csv
```

Window **3 giây, trượt 0,5 giây**, chỉ dùng cho chế độ 1 người. Cột chung giống mục 5 (`session_id`, `win_start`,
`win_end`, `valid`, `n_people`, các cột `<board>_n_samples`), thêm:

| Cột | Ý nghĩa |
|---|---|
| `action` | `FALL`, `SIT_DOWN`, `STAND_UP`, `LIE_DOWN`, `PICK_UP`, hoặc `NONE` |
| `state` | Nhãn `STATE` tại giữa window (để lấy mẫu `NONE` từ cả đoạn `ACTIVE` lẫn `STILL`) |
| Đặc trưng | Tên cột có tiền tố board như trên. Hiện `features.py` dùng 4 đặc trưng độ phân tán (như window 6 s) + 2 đặc trưng hình dạng mỗi RX: `<board>_shape_peak` (biến thiên lớn nhất trong 0,1 s của biên độ trung bình), `<board>_shape_ratio` (độ dao động nửa sau / nửa đầu window) |

Gán nhãn `action`:
- Window trùng **≥ 2 giây** với đoạn của một động tác (mục 4.4) → nhãn của động tác đó.
- Window **không trùng** đoạn động tác nào → `NONE`.
- Các trường hợp còn lại (trùng một phần) → **bỏ**, vì không rõ nhãn.
- Window nằm trong `PAUSE` hoặc có `n_people` ≠ 1 → bỏ.

`feature_meta.json` ghi lại cách tạo đặc trưng, để biết hai file có so sánh được với nhau không:
```json
{
  "spec_version": "0.3",
  "boards": ["RX1", "RX2"],
  "csi_len": 104,
  "window_s": 6,
  "expected_rate_hz": 100,
  "valid_ratio": 0.7,
  "subcarriers_kept": [6, 7, 8],
  "denoise": {"wavelet": "db4", "level": 9},
  "code_version": "git commit"
}
```
(`subcarriers_kept` ở trên chỉ là ví dụ; danh sách thật được chốt sau khi xem dữ liệu thật. Hai file đặc trưng chỉ
so sánh được khi cùng `csi_len`.)

**Code tiền xử lý viết thành hàm trong một module dùng chung** (ví dụ `features.py`), không chỉ trong notebook. Dashboard sẽ gọi lại đúng các hàm này khi chạy thời gian thực.

---

## 6. File đầu ra nhánh thiết bị (Phúc → Chiến)

```
data/device/<session_id>.csv
```

Mỗi dòng là **một khe 1 phút**:

| Cột | Ý nghĩa |
|---|---|
| `session_id` | Mã buổi thu |
| `slot_start` | `host_time` đầu khe |
| `n_sources_seen` | Số `mac_hash` khác nhau thấy trong khe (đã bỏ `excluded = 1`) |
| `n_confirmed` | Số nguồn đang ở trạng thái "Xác nhận đến" hoặc "Có thể đã đi" |
| `device_present` | 1 nếu `n_confirmed` ≥ 1 |
| `people_manual` | Số người đếm thủ công, tính từ các sự kiện `COUNT` trong `labels.csv` (dùng để tính PCC, MRE) |

---

## 7. Thông số mặc định

| Thông số | Giá trị |
|---|---|
| Tốc độ phát của TX (ESP‑NOW broadcast) | 100 gói/giây |
| Window có người / mức hoạt động | 6 giây, không chồng lấn |
| Window động tác | 3 giây, trượt 0,5 giây |
| Window nhịp thở | 30 giây, lọc 0,1–0,6 Hz |
| Window hợp lệ | ≥ 70% số mẫu dự kiến (≥ 420 mẫu với window 6 s), xét **từng RX** |
| Sniffer #3 | Kênh 1→13, 3 giây mỗi kênh |
| Khe Sherlock | 60 giây |
| Ngưỡng Sherlock | AT = DT = 6, WT = 2 |
| Chu kỳ dòng `STAT` | 1 giây |
| Chu kỳ lặp dòng `BOOT` | 30 giây |

---

## 8. Việc cần chốt và ai làm

**Cần cả nhóm xác nhận:**
- [ ] Đồng ý dùng dạng văn bản (chuyển sang nhị phân nếu buổi kiểm thử cho thấy không kịp).
- [ ] Đồng ý đổi sang ESP‑NOW broadcast, 1 TX + 2 RX, thêm trường `rx_seq` (v0.3).
- [ ] Đồng ý bộ nhãn trạng thái, động tác và phím ở mục 4.4 (v0.3).

**Kiểm tra ở buổi kiểm thử phần cứng:** `len` thực tế; `rx_seq` của RX1 và RX2 có trùng nhau cho cùng một gói
không; tốc độ CSI mỗi RX (`STAT`) khi laptop đọc đồng thời 3 cổng.

**Tiên:** firmware TX (ESP‑NOW broadcast, in `BOOT`) và RX (in `BOOT`, `CSI`, `STAT` đúng mục 3) từ ví dụ esp‑csi;
viết `features.py` xuất file đúng mục 5 và 5.2.

**Phúc:** firmware #3 in `BOOT`, `PRB`, `STAT` đúng mục 3; máy trạng thái đọc `probe.csv` và xuất file đúng mục 6
(ghép vào nhánh người đang tạm gác).

**Chiến:** ~~sửa `nhan.py`, `logger.py`, `kiem_tra_buoi_thu.py`, `train.py`, dashboard theo v0.3; viết
`features.py` (mục 5, 5.2)~~ – xong 23/11/2026.

---

## Lịch sử thay đổi

| Phiên bản | Ngày | Người sửa | Nội dung |
|---|---|---|---|
| 0.1 | 09/11/2026 | Chiến | Bản nháp đầu tiên; bổ sung các trường `simulated`, `ports`, `stats` của `meta.json` theo `laptop/logger.py` |
| 0.2 | 21/11/2026 | Chiến | Bài toán mới (giám sát an toàn): nhãn `ACTIVE`, `STILL`, `FALL`, `DOWN`, `BREATH_ABN` thay `WALK`, `STATIC`, `MULTI`; số người lấy từ `COUNT`; file đặc trưng thêm `activity`, `n_people`; `meta.json` có thể có khối `simulator` (dữ liệu mô phỏng Sionna RT) |
| 0.3 | 22/11/2026 | Chiến | TX phát ESP‑NOW broadcast thay SoftAP + ping; 2 RX (`RX1`, `RX2`), dòng `CSI` thêm `rx_seq`, `csi.csv` thêm cột `board`; chấp nhận `len` 104; `FALL` chuyển từ `STATE` sang sự kiện `ACTION` cùng `SIT_DOWN`, `STAND_UP`, `LIE_DOWN`, `PICK_UP`; thêm `RATE` (nhịp thở đáp án); cột đặc trưng có tiền tố board, thêm `breath_rate`; thêm file window động tác 3 s (mục 5.2) |
