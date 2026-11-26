#!/usr/bin/env python3
"""Ước lượng nhịp thở từ biên độ CSI (tầng 2b của kế hoạch nhánh người), dùng cho dữ liệu thật lẫn mô phỏng.

    from nhip_tho import uoc_luong
    bpm, do_noi, ly_do = uoc_luong([amp_rx1], fs=100)   # mỗi amp: (số mẫu, 52) ~30 giây; hàng toàn NaN = gói mất

    python nhip_tho.py          # tự đánh giá trên mô phỏng 3D: hai RX / một RX, nhiễu ngẫu nhiên / đợt Wi-Fi

Một RX (52 sóng mang con, như trên board – cách B); đưa nhiều RX thì ghép sóng mang con của chúng. Các bước:
1. Bỏ gói hỏng (mức chung của gói lệch ×/÷ 1,5 so với trung vị trong giây đó), chia mỗi gói cho mức chung của nó (bỏ
   dao động khuếch đại chung mọi sóng mang con), gộp trung bình mỗi 0,1 s (10 Hz); ô 0,1 s mất hết gói → nội suy.
2. Kiểm tra cử động: dao động chậm (< 1 Hz) lớn hơn hẳn nhiễu nền → người đang đi lại / cử động, không đo.
3. Chia mỗi sóng mang con cho mức nhiễu nền của chính nó (dải 1,5–4,5 Hz) → sóng mang con nhạy với nhịp thở nổi lên.
4. Tìm các lúc xê dịch tư thế (biên độ đổi nhanh ở nhiều sóng mang con), khử xu hướng riêng từng đoạn giữa các lúc đó
   và làm phẳng quanh chỗ nhảy – nếu không, một lần xê dịch 5 cm sẽ lấn át cả cửa sổ.
5. Lọc thông dải 0,05–1 Hz, PCA: nhịp thở làm nhiều sóng mang con dao động cùng dạng nên gom lại thành thành phần chính.
6. Phổ Welch (2 đoạn 20 s) của 3 thành phần đầu, đỉnh trong 0,12–0,75 Hz (7,2–45 nhịp/phút); đỉnh nằm ở mép dải thì
   không tin (thường là trôi chậm còn sót). Nội suy parabol để lấy nhịp lẻ. Chọn thành phần có độ nổi / ngưỡng lớn nhất.
7. Thở nhanh (> 25, ngực chỉ dịch 3 mm) nằm dưới lắc lư chậm nên ít khi vào 3 thành phần trên: thêm PCA riêng trên dải
   0,35–1 Hz, đỉnh trong 24–48 nhịp/phút; nhận nếu độ nổi ≥ CAO_PROM, đỉnh của từng đoạn 20 s lệch ≤ 1 nhịp/phút (đỉnh
   nhiễu hay nhảy) và nổi hơn câu trả lời 8–25 nếu có.
8. Độ tin cậy = đỉnh / trung vị phổ trong dải, ngưỡng theo vùng nhịp: 6 (8–25), 7 (> 25), 20 (< 8) – đỉnh sai < 8 là
   lắc lư, rất nổi; đỉnh sai 8–25 chỉ làm lệch nhịp, không sinh cảnh báo. Dưới ngưỡng → không ra nhịp: 'khong-thay' nếu
   không có dao động chậm nào hơn nhiễu nền (nín thở, phòng trống), 'yeu' nếu có (thở yếu, cử động nhẹ).

Kết quả `python nhip_tho.py` (36 chỗ ngồi, mỗi chỗ 3 cửa sổ thở 8–36 nhịp/phút + 1 cửa sổ nín thở), bản trước (một
ngưỡng 8, không có bước 7) → bản này. "Bất thường giả": thở 10–22 mà ra > 25 hoặc < 8. "Thường → khong-thay": cửa sổ
thở thường bị đếm vào ngưng thở. Cách B dùng "một RX".

| Cấu hình                       | Trả lời     | Đúng ±2 khi trả lời | Nín thở báo có thở | Bất thường giả | Thường → khong-thay |
|--------------------------------|-------------|---------------------|--------------------|----------------|---------------------|
| hai RX, nhiễu ngẫu nhiên       | 0,31 → 0,38 | 0,71 → 0,68         | 0,11 → 0,14        | 0,013 → 0,013  | 0,28 → 0,25         |
| một RX, nhiễu ngẫu nhiên       | 0,19 → 0,26 | 0,80 → 0,71         | 0,06 → 0,07        | 0,007 → 0,000  | 0,37 → 0,33         |
| hai RX, đợt Wi-Fi (NaN gói mất)| 0,31 → 0,38 | 0,58 → 0,59         | 0,14 → 0,31        | 0,013 → 0,027  | 0,39 → 0,35         |
| một RX, đợt Wi-Fi (NaN gói mất)| 0,17 → 0,23 | 0,75 → 0,65         | 0,14 → 0,19        | 0,000 → 0,007  | 0,46 → 0,41         |

Ở mức cửa sổ bản này trả lời nhiều hơn, đổi lại nín thở trong đợt Wi-Fi hay bị báo có thở hơn (lúc chạy, cờ kênh bận
đã bỏ nhịp thở trong đợt Wi-Fi). Ngưỡng chọn theo SỰ KIỆN – danh_gia_canh_bao.py trên 40 buổi sim2, cách B, biến thể b,
có cờ kênh; chọn trên buổi lẻ, kiểm trên buổi chẵn (bắt được / số sự kiện; báo giả mỗi giờ):

| Nửa              | Thở nhanh/chậm | Nín thở  | THO_BAT_THUONG giả | NGUNG_THO giả | NGA_KHAN_CAP giả |
|------------------|----------------|----------|--------------------|---------------|------------------|
| lẻ (chọn)        | 0/13 → 3/13    | 0/4 → 0/4| 1,4 → 0,9          | 1,4 → 1,8     | 2,8 → 2,3        |
| chẵn (kiểm)      | 2/8 → 3/8      | 1/8 → 1/8| 2,3 → 3,7          | 2,3 → 2,3     | 0,9 → 0,9        |
| cả 40 buổi       | 2/21 → 6/21    | 1/12→1/12| 1,9 → 2,3          | 1,9 → 2,1     | 1,9 → 1,6        |

Giới hạn (mô phỏng): nhịp thở ở sát nhiễu – thở thường chỉ ~35 % cửa sổ một board có đỉnh đúng nhịp đứng đầu; thở < 7
nhịp/phút gần như không đo được trong 30 s (lắc lư lấn át: 0/4 lần thở 6 nhịp được báo); thở nhanh bắt được 4/7 lần
32 nhịp/phút nhưng chỉ 2/10 lần 38 (ngực dịch 3 mm). Dù nhịp thở đo đúng tuyệt đối, quy tắc canh_bao hiện tại cũng
chỉ bắt được ~14/21 thở bất thường (đoạn ngắn 15–40 s, hay ngay sau khi ngồi / nằm xuống nên cửa sổ 30 s còn dính cử
động) và 3/12 nín thở (cờ kênh bận, chưa đo được nhịp trong lần Yên đó, đoạn nín ngắn hơn 3 cửa sổ). Với đợt Wi-Fi, đưa gói mất
vào dưới dạng hàng NaN (theo rx_seq / thời gian) thì đúng hơn hẳn bỏ hàng (bỏ hàng làm co trục thời gian → nhịp lệch).

Chi phí trên ESP32-S3, một RX, cửa sổ 30 s (300 × 52 ô 10 Hz), chạy mỗi 5 s: mỗi gói ~300 phép tính (mức chung, chia,
cộng dồn vào ô 0,1 s) → ~30 nghìn phép/s; mỗi cửa sổ ~7–8 triệu phép float (4 lọc filtfilt ~3 tr., 2 hiệp phương sai
52 × 52 ~1,6 tr., 6 vector riêng bằng lặp luỹ thừa ~1,6 tr., 12 FFT 2048 điểm ~0,7 tr.; đỉnh từng đoạn 20 s lấy luôn từ
2 FFT của Welch) → cỡ 60–110 ms một nhân 240 MHz. Bộ nhớ ~200 KB float32: vòng đệm 300 × 52 (62 KB) + bản làm việc
(62 KB) + lọc (62 KB, ghi đè tại chỗ, PCA dải cao dùng lại sau khi xong PCA chính) + hiệp phương sai (11 KB) + FFT
(16 KB). Gói hỏng: lấy trung vị mức chung của giây trước làm mốc để khỏi đệm cả giây.
"""
import warnings

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt, welch

FS_OUT = 10.0                     # Hz sau khi gộp
FILTER = (0.05, 1.0)              # Hz, dải lọc. Cắt thấp ở 0,05 chứ không sát dải tìm: cắt ở 0,08 thì trôi chậm (lắc lư)
#                                   bị bộ lọc nắn thành "đỉnh" giả 6–8 nhịp/phút → báo thở chậm giả
SEARCH = (0.12, 0.75)             # Hz, dải tìm đỉnh: 7,2–45 nhịp/phút. Dưới 0,12 Hz trôi chậm lấn át nhịp thở trong 30 s
# Độ nổi tối thiểu theo vùng nhịp: đỉnh giả từ nhiễu không đều trên dải – lắc lư / trôi chậm cho đỉnh giả nổi ở nhịp
# thấp (sim2, thở thường: đỉnh sai < 8 nhịp/phút nổi tới 57, mà 0/6 cửa sổ thở 6 nhịp ra < 8), còn trên 25 nhịp/phút
# đỉnh sai hiếm khi > 7. Đỉnh sai trong 8–25 chỉ làm lệch nhịp, không sinh cảnh báo → ngưỡng thấp để hay trả lời hơn.
MIN_PROM = 6.0                    # 8–25 nhịp/phút (5: thêm 1 lần nín thở bắt được, nhưng hai RX đúng ±2 < 0,55)
MIN_PROM_CAO = 7.0                # > 25 nhịp/phút (thở nhanh)
MIN_PROM_THAP = 20.0              # < 8 nhịp/phút (thở chậm)
LOC_CAO = (0.35, 1.0)             # Hz, dải lọc của PCA riêng cho thở nhanh
TIM_CAO = (0.40, 0.80)            # Hz, dải tìm đỉnh của nó (24–48 nhịp/phút)
CAO_PROM = 7.5                    # PCA dải cao: độ nổi tối thiểu (≥ MIN_PROM_CAO) …
CAO_LECH = 1.0                    # … và đỉnh của 2 đoạn Welch 20 s lệch đỉnh chung ≤ 1 nhịp/phút
MOVE_RATIO = 1.25                 # dao động < 1 Hz / nhiễu nền vượt mức này → đang cử động (đi lại ≥ 1,34; yên ≤ 1,15)
GOI_HONG = 0.4                    # |ln(mức gói / trung vị trong giây đó)| > 0,4 (×/÷ 1,5) → gói hỏng, bỏ
YEU = 0.65                        # không ra nhịp mà dao động chậm / nhiễu nền > mức này → 'yeu' chứ không 'khong-thay'
#                                   (chỉ có nhiễu thì ≈ √(1/3) = 0,58; nín thở trong mô phỏng: 95 % cửa sổ ≤ 0,645)


def _gop(amp, fs):
    """Gộp trung bình mỗi 0,1 s. Hàng toàn NaN = gói mất (giữ đúng trục thời gian); ô 0,1 s không còn gói → nội suy.
    Trước khi gộp: bỏ gói hỏng (cả gói to / nhỏ đi 2–4 lần khi khung Wi-Fi khác chồng lên) và chia mỗi gói cho mức
    chung của nó – khuếch đại (AGC) dao động ~5 % mỗi gói, chung mọi sóng mang con, lớn hơn dao động do thở."""
    step = max(1, int(round(fs / FS_OUT)))
    a = np.asarray(amp, dtype=float)[:len(amp) // step * step]
    mat = np.isnan(a).all(axis=1)
    a = a[:, ~np.isnan(a[~mat]).any(axis=0)]                          # sóng mang con có NaN lẻ tẻ: bỏ
    with warnings.catch_warnings():                                   # ô / giây mất hết gói → NaN, xử lý ở dưới
        warnings.simplefilter("ignore", RuntimeWarning)
        lv = np.log(np.maximum(a.mean(axis=1), 1e-9))
        sec = 10 * step
        ref = np.nanmedian(np.pad(lv, (0, -len(lv) % sec), constant_values=np.nan).reshape(-1, sec), axis=1)
        a = a / np.exp(lv)[:, None]
        a[np.abs(lv - np.repeat(ref, sec)[:len(lv)]) > GOI_HONG] = np.nan
        X = np.nanmean(a.reshape(-1, step, a.shape[1]), axis=1)
    ok = ~np.isnan(X).any(axis=1)
    if ok.all() or ok.sum() < 2:
        return X[ok]
    i = np.arange(len(X))
    return np.array([np.interp(i, i[ok], c[ok]) for c in X.T]).T


def _bo_xe_dich(X):
    """Khử xu hướng riêng từng đoạn giữa các lúc xê dịch tư thế, làm phẳng ±1 s quanh mỗi lúc xê dịch."""
    Z = (X - X.mean(axis=0)) / np.maximum(X.std(axis=0), 1e-9)
    d = np.abs(Z[10:] - Z[:-10]).mean(axis=1)                       # đổi trong 1 s, trung bình các sóng mang con
    peaks, _ = find_peaks(d, height=3 * np.median(d) + 1e-9, distance=30)
    cuts = [0] + [p + 5 for p in peaks] + [len(X)]
    Y = np.zeros_like(X)
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a >= 3:
            t = np.vstack([np.arange(b - a), np.ones(b - a)]).T
            Y[a:b] = X[a:b] - t @ np.linalg.lstsq(t, X[a:b], rcond=None)[0]
    for p in peaks:
        Y[max(0, p - 3):p + 13] = 0
    return Y


def _nguong(bpm):
    return MIN_PROM_CAO if bpm > 25 else MIN_PROM_THAP if bpm < 8 else MIN_PROM


def _dinh(sig, dai=SEARCH):
    """(tần số đỉnh Hz, độ nổi) của một tín hiệu trong dải tìm; đỉnh ở mép dải → độ nổi 0."""
    m = min(len(sig), int(20 * FS_OUT))
    # luôn lấy 2 đoạn 20 s (đầu, cuối) như cửa sổ 30 s: cửa sổ ngắn hơn (bỏ gói mất) mà chỉ 1 đoạn thì phổ dao động
    # mạnh → đỉnh giả nổi hơn, nín thở bị nhầm là có thở
    f, P = welch(sig, fs=FS_OUT, nperseg=m, noverlap=max(0, min(m - 1, 2 * m - len(sig))), nfft=2048)
    b = (f >= dai[0]) & (f <= dai[1])
    fb, Pb = f[b], P[b]
    k = int(Pb.argmax())
    if k in (0, len(Pb) - 1):
        return fb[k], 0.0
    a, c = Pb[k - 1], Pb[k + 1]
    den = a - 2 * Pb[k] + c
    shift = 0.5 * (a - c) / den if den else 0.0
    return fb[k] + shift * (fb[1] - fb[0]), float(Pb[k] / np.median(Pb))


def uoc_luong(amps, fs=100.0):
    """amps: danh sách mảng (số mẫu, số sóng mang con) của từng RX, cùng khoảng thời gian, nên ≥ 20 giây.
    Hàng toàn NaN = gói mất ở đúng chỗ đó (nên đưa vào như vậy thay vì bỏ hàng: bỏ hàng làm co trục thời gian).
    Trả về (nhịp/phút hoặc None, độ nổi đỉnh, lý do khi None: 'ngan' | 'cu-dong' | 'khong-thay' | 'yeu').
    'khong-thay': không có dao động chậm nào hơn nhiễu nền (nín thở, phòng trống); 'yeu': có dao động chậm (thở yếu,
    cử động nhẹ) nhưng không ra được nhịp tin cậy – không nên tính là ngưng thở."""
    bpm, prom, why, dao_dong = _tho(amps, fs)
    if bpm is not None and prom < _nguong(bpm):
        return None, prom, "yeu" if dao_dong > YEU else "khong-thay"
    return bpm, prom, why


def _tho(amps, fs):
    """Như uoc_luong nhưng chưa áp ngưỡng độ nổi (để đánh giá nhiều ngưỡng); thêm trung vị dao động chậm / nhiễu nền."""
    X = [_gop(a, fs) for a in amps]
    n = min(len(x) for x in X)
    X = np.concatenate([x[:n] for x in X], axis=1)
    if len(X) < 20 * FS_OUT:
        return None, 0.0, "ngan", 0.0
    X = X[:, X.std(axis=0) > 1e-9] - X[:, X.std(axis=0) > 1e-9].mean(axis=0)
    floor = sosfiltfilt(butter(3, [1.5, 4.5], btype="band", fs=FS_OUT, output="sos"), X, axis=0).std(axis=0)
    slow = sosfiltfilt(butter(3, 1.0, btype="low", fs=FS_OUT, output="sos"), X, axis=0).std(axis=0)
    dao_dong = float(np.median(slow / np.maximum(floor, 1e-9)))
    if dao_dong > MOVE_RATIO:
        return None, 0.0, "cu-dong", dao_dong
    X = _bo_xe_dich(X / np.maximum(floor, 1e-9))
    Y = sosfiltfilt(butter(3, FILTER, btype="band", fs=FS_OUT, output="sos"), X, axis=0)
    U, s, _ = np.linalg.svd(Y, full_matrices=False)
    peak, prom = max((_dinh(U[:, i] * s[i]) for i in range(min(3, len(s)))), key=lambda r: r[1] / _nguong(r[0] * 60))
    # Thở nhanh nông (ngực dịch 3 mm) nằm dưới lắc lư chậm nên ít khi vào 3 thành phần trên: PCA riêng trên dải cao.
    # Đỉnh phải trùng ở cả 2 đoạn 20 s (đỉnh nhiễu hay nhảy) và nổi hơn câu trả lời 8–25 nếu có.
    U, s, _ = np.linalg.svd(sosfiltfilt(butter(3, LOC_CAO, btype="band", fs=FS_OUT, output="sos"), X, axis=0),
                            full_matrices=False)
    sig = max((U[:, i] * s[i] for i in range(min(3, len(s)))), key=lambda x: _dinh(x, TIM_CAO)[1])
    f, p = _dinh(sig, TIM_CAO)
    lech = max(abs(_dinh(sig[:200], TIM_CAO)[0] - f), abs(_dinh(sig[-200:], TIM_CAO)[0] - f)) * 60
    thuong = 8 <= peak * 60 <= 25 and prom / MIN_PROM > p / CAO_PROM
    if f * 60 > 25 and p >= CAO_PROM and lech <= CAO_LECH and not thuong:
        return float(f * 60), p, "", dao_dong
    return float(peak * 60), prom, "", dao_dong


def don_gian(amps, fs=100.0):
    """Thuật toán cũ để so sánh: trừ trung bình trượt 4 s, FFT, lấy sóng mang con có dải thở mạnh nhất (cả 2 RX)."""
    k = int(4 * fs)
    x = np.concatenate([np.asarray(a, dtype=float) for a in amps], axis=1)
    x = x - np.array([np.convolve(np.pad(c, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, "valid")
                      for c in x.T]).T
    f = np.fft.rfftfreq(len(x), 1 / fs)
    spec = np.abs(np.fft.rfft(x, axis=0))
    band = (f > 0.15) & (f < 0.6)
    return f[band][spec[band, spec[band].sum(axis=0).argmax()].argmax()] * 60


def _danh_gia(n_seed=36, in_ra=True, mot_rx=False, wifi=False):
    """Đánh giá trên mô phỏng: cửa sổ 30 s khi ngồi yên ở chỗ ngẫu nhiên trong khu demo, nhịp 8–36/phút, và cửa sổ
    nín thở để chọn ngưỡng tin cậy. mot_rx: mỗi RX tự đo (như trên board, cách B), mỗi cửa sổ tính một lần cho mỗi RX.
    wifi: thay các đợt nhiễu ngẫu nhiên bằng một đợt Wi-Fi chiếm kênh 10–40 s trong đoạn thở và 10–20 s trong đoạn nín
    thở (gói hỏng như mo_phong.compute, mất 5–40 % gói như write_session – đánh dấu NaN).
    Trả về dict: tra_loi, dung_khi_tra_loi, nin_tho_bao_nham, bat_thuong_gia (thở 10–22 mà ra > 25 hoặc < 8),
    nin_tho_khong_thay, thuong_khong_thay (tỉ lệ 'khong-thay' – thứ được đếm thành ngưng thở), don_gian."""
    import mo_phong as sim
    rng = np.random.default_rng(1)
    rows, apnea, chair0 = [], [], sim.CHAIR
    for seed in range(n_seed):
        while True:                                                   # chỗ ngồi không sát board
            chair = np.array([rng.uniform(0.5, 2.2), rng.uniform(0.5, 2.2)])
            if min(np.linalg.norm(chair - q) for q in [sim.TX, *sim.RX.values()]) > 0.6:
                break
        sim.CHAIR = chair
        bpm = float(rng.choice([8, 10, 12, 15, 18, 22, 30, 36]))
        name = "BREATH_ABN" if bpm > 25 or bpm < 10 else "STILL"
        r = np.random.default_rng(seed + 777)
        nhieu = (f"tat,wifi@{r.uniform(10, 60):.1f}:{r.uniform(10, 40):.1f},wifi@{r.uniform(82, 100):.1f}:"
                 f"{r.uniform(10, 20):.1f}") if wifi else None
        t, _, _, spans, rx = sim.compute(f"ACTIVE:8,SIT_DOWN,{name}:70@{bpm:g},BREATH_ABN:40@0", seed, nhieu=nhieu)
        a0 = next(a for n, a, _ in spans if n == name) + 3
        z0 = next(a for n, a, b in spans if n == "BREATH_ABN" and b - a < 45) + 3
        amps = [np.hypot(im.astype(float), re.astype(float)) for im, re, _ in rx.values()]
        for _, a, b in sim.interference_for(seed, len(t), 100, nhieu) if wifi else []:
            lost = ((t >= a) & (t < b)) * (0.05 + 0.35 * r.random())  # compute không bỏ gói: bỏ như write_session
            for x in amps:
                x[r.random(len(t)) < lost] = np.nan
        cut = lambda g, w0: [x[int(w0 * 100):int(w0 * 100) + 3000] for x in g]
        for g in ([[x] for x in amps] if mot_rx else [amps]):
            for w0 in (a0, a0 + 15, a0 + 30):
                w = cut(g, w0)
                co = ~np.any([np.isnan(x).any(axis=1) for x in w], axis=0)                 # don_gian không chịu NaN
                rows.append((bpm, *_tho(w, 100.0), don_gian([x[co] for x in w])))
            apnea.append(_tho(cut(g, z0), 100.0))
    sim.CHAIR = chair0
    ok = lambda e, b: e is not None and abs(e - b) <= 2
    tra = lambda e, p, k=1.0: e is not None and p >= k * _nguong(e)                  # k: hệ số nhân mọi ngưỡng
    khong = lambda e, p, d: not tra(e, p) and d <= YEU                    # như uoc_luong trả 'khong-thay'
    answered = np.array([tra(e, p) for _, e, p, *_ in rows])
    hit = np.array([ok(e, b) for b, e, *_ in rows])
    normal = [r for r in rows if 10 <= r[0] <= 22]
    kq = {"tra_loi": answered.mean(), "dung_khi_tra_loi": hit[answered].mean() if answered.any() else 0.0,
          "nin_tho_bao_nham": np.mean([tra(e, p) for e, p, *_ in apnea]),
          "bat_thuong_gia": np.mean([tra(e, p) and (e > 25 or e < 8) for _, e, p, *_ in normal]),
          "nin_tho_khong_thay": np.mean([khong(e, p, d) for e, p, _, d in apnea]),
          "thuong_khong_thay": np.mean([khong(e, p, d) for _, e, p, _, d, _ in normal]),
          "don_gian": np.mean([ok(o, b) for b, *_, o in rows])}
    if not in_ra:
        return kq
    print(f"{'một RX' if mot_rx else 'hai RX'}, {'đợt Wi-Fi chiếm kênh' if wifi else 'nhiễu ngẫu nhiên'}: {len(rows)} "
          f"cửa sổ 30 s ngồi yên, nhịp 8–36/phút, {n_seed} chỗ ngồi; thuật toán đơn giản đúng ±2 {kq['don_gian']:.0%}")
    print("  " + ", ".join(f"{k} {v:.2f}" for k, v in kq.items() if k != "don_gian"))
    print("  hệ số nhân ngưỡng độ nổi → trả lời / đúng khi trả lời / nín thở báo có thở:  " + "  ".join(
        f"×{k:g}: {np.mean(a):.2f}/{np.mean(hit[a]) if a.any() else 0:.2f}/"
        f"{np.mean([tra(e, p, k) for e, p, *_ in apnea]):.2f}"
        for k in (0.75, 1, 1.25, 1.5) for a in [np.array([tra(e, p, k) for _, e, p, *_ in rows])]))
    return kq


if __name__ == "__main__":
    _p = np.linspace(10, 20, 52)                    # tự kiểm _gop: bỏ gói hỏng, gói mất (NaN) không làm co trục thời gian
    _x = np.tile(_p, (3000, 1))
    _x[::50] *= 3 * np.linspace(0.6, 1.4, 52)
    _x[100:400] = np.nan
    assert _gop(_x, 100.0).shape == (300, 52) and np.allclose(_gop(_x, 100.0), _p / _p.mean())
    for cau_hinh in ({}, {"mot_rx": True}, {"wifi": True}, {"mot_rx": True, "wifi": True}):
        _danh_gia(**cau_hinh)
