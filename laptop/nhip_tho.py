#!/usr/bin/env python3
"""Ước lượng nhịp thở từ biên độ CSI (tầng 2b của kế hoạch nhánh người), dùng cho dữ liệu thật lẫn mô phỏng.

    from nhip_tho import uoc_luong
    bpm, tin_cay, ly_do = uoc_luong([amp_rx1, amp_rx2], fs=100)   # mỗi amp: (số mẫu, 52), cùng ~30 giây

    python nhip_tho.py          # tự đánh giá trên mô phỏng 3D và so với thuật toán đơn giản

Các bước (gộp cả 2 RX, 104 sóng mang con):
1. Gộp trung bình mỗi 0,1 s (10 Hz) để giảm nhiễu từng gói.
2. Kiểm tra cử động: dao động chậm (< 1 Hz) lớn hơn hẳn nhiễu nền → người đang đi lại / cử động, không đo.
3. Chia mỗi sóng mang con cho mức nhiễu nền của chính nó (dải 1,5–4,5 Hz) → sóng mang con nhạy với nhịp thở nổi lên.
4. Tìm các lúc xê dịch tư thế (biên độ đổi nhanh ở nhiều sóng mang con), khử xu hướng riêng từng đoạn giữa các lúc đó
   và làm phẳng quanh chỗ nhảy – nếu không, một lần xê dịch 5 cm sẽ lấn át cả cửa sổ.
5. Lọc thông dải 0,08–1 Hz, PCA: nhịp thở làm nhiều sóng mang con dao động cùng dạng nên gom lại thành thành phần chính.
6. Phổ Welch của 3 thành phần đầu, chọn thành phần có đỉnh nổi nhất trong 0,1–0,75 Hz (6–45 nhịp/phút); đỉnh nằm ở
   mép dải thì không tin (thường là trôi chậm còn sót). Nội suy parabol để lấy nhịp lẻ.
7. Độ tin cậy = đỉnh / trung vị phổ trong dải. Dưới MIN_PROM → "không thấy nhịp thở" (nín thở, phòng trống, quá xa).
"""
import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt, welch

FS_OUT = 10.0                     # Hz sau khi gộp
FILTER = (0.08, 1.0)              # Hz, dải lọc (rộng hơn dải tìm để mép bộ lọc không làm lệch nhịp nhanh)
SEARCH = (0.1, 0.75)              # Hz, dải tìm đỉnh: 6–45 nhịp/phút
MIN_PROM = 9.0                    # độ nổi đỉnh tối thiểu (chọn để ~10 % cửa sổ nín thở bị báo nhầm, xem _danh_gia)
MOVE_RATIO = 1.25                 # dao động < 1 Hz / nhiễu nền vượt mức này → đang cử động (đi lại ≥ 1,34; yên ≤ 1,15)


def _gop(amp, fs):
    step = max(1, int(round(fs / FS_OUT)))
    n = len(amp) // step * step
    return amp[:n].reshape(-1, step, amp.shape[1]).mean(axis=1)


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


def _dinh(sig):
    """(tần số đỉnh Hz, độ nổi) của một tín hiệu trong dải tìm; đỉnh ở mép dải → độ nổi 0."""
    f, P = welch(sig, fs=FS_OUT, nperseg=min(len(sig), int(20 * FS_OUT)), nfft=2048)
    b = (f >= SEARCH[0]) & (f <= SEARCH[1])
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
    Trả về (nhịp/phút hoặc None, độ nổi đỉnh, lý do khi None: 'ngan' | 'cu-dong' | 'khong-thay')."""
    bpm, prom, why = _tho(amps, fs)
    if bpm is not None and prom < MIN_PROM:
        return None, prom, "khong-thay"
    return bpm, prom, why


def _tho(amps, fs):
    """Như uoc_luong nhưng chưa áp ngưỡng độ nổi (để đánh giá nhiều ngưỡng)."""
    n = min(len(a) for a in amps)
    X = np.concatenate([_gop(np.asarray(a, dtype=float)[:n], fs) for a in amps], axis=1)
    if len(X) < 20 * FS_OUT:
        return None, 0.0, "ngan"
    X = X[:, X.std(axis=0) > 1e-9] - X[:, X.std(axis=0) > 1e-9].mean(axis=0)
    floor = sosfiltfilt(butter(3, [1.5, 4.5], btype="band", fs=FS_OUT, output="sos"), X, axis=0).std(axis=0)
    slow = sosfiltfilt(butter(3, 1.0, btype="low", fs=FS_OUT, output="sos"), X, axis=0).std(axis=0)
    if np.median(slow / np.maximum(floor, 1e-9)) > MOVE_RATIO:
        return None, 0.0, "cu-dong"
    X = _bo_xe_dich(X / np.maximum(floor, 1e-9))
    Y = sosfiltfilt(butter(3, FILTER, btype="band", fs=FS_OUT, output="sos"), X, axis=0)
    U, s, _ = np.linalg.svd(Y, full_matrices=False)
    peak, prom = max((_dinh(U[:, i] * s[i]) for i in range(min(3, len(s)))), key=lambda r: r[1])
    return float(peak * 60), prom, ""


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


def _danh_gia(n_seed=36, in_ra=True):
    """Đánh giá trên mô phỏng: cửa sổ 30 s khi ngồi yên ở chỗ ngẫu nhiên trong khu demo, nhịp 8–36/phút, và cửa sổ
    nín thở để chọn ngưỡng tin cậy. Trả về dict: tra_loi, dung_khi_tra_loi, nin_tho_bao_nham, don_gian."""
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
        _, _, _, spans, rx = sim.compute(f"ACTIVE:8,SIT_DOWN,{name}:70@{bpm:g},BREATH_ABN:40@0", seed)
        a0 = next(a for n, a, _ in spans if n == name) + 3
        z0 = next(a for n, a, b in spans if n == "BREATH_ABN" and b - a < 45) + 3
        amps = [np.hypot(im.astype(float), re.astype(float)) for im, re, _ in rx.values()]
        for w0 in (a0, a0 + 15, a0 + 30):
            w = [a[int(w0 * 100):int((w0 + 30) * 100)] for a in amps]
            est, prom, why = _tho(w, 100.0)
            rows.append((bpm, est, prom, why, don_gian(w)))
        apnea.append(_tho([a[int(z0 * 100):int((z0 + 30) * 100)] for a in amps], 100.0)[1])
    sim.CHAIR = chair0
    ok = lambda e, b: e is not None and abs(e - b) <= 2
    answered = np.array([e is not None and p >= MIN_PROM for _, e, p, _, _ in rows])
    hit = np.array([ok(e, b) for b, e, _, _, _ in rows])
    apnea = np.array(apnea)
    kq = {"tra_loi": answered.mean(), "dung_khi_tra_loi": hit[answered].mean() if answered.any() else 0.0,
          "nin_tho_bao_nham": np.mean(apnea >= MIN_PROM), "don_gian": np.mean([ok(o, b) for b, *_, o in rows])}
    if not in_ra:
        return kq
    print(f"{len(rows)} cửa sổ 30 s ngồi yên, nhịp 8–36/phút, {n_seed} chỗ ngồi ngẫu nhiên trong khu demo")
    print(f"  thuật toán đơn giản: đúng ±2 nhịp {np.mean([ok(o, b) for b, _, _, _, o in rows]):.0%} "
          f"(luôn trả lời, không biết khi nào sai)")
    print(f"  thuật toán mới:      trả lời {answered.mean():.0%} số cửa sổ, đúng ±2 nhịp khi trả lời "
          f"{hit[answered].mean() if answered.any() else 0:.0%}, sai số TB "
          f"{np.mean([abs(e - b) for (b, e, *_), k in zip(rows, answered) if k]):.2f} nhịp/phút")
    print(f"  nín thở 30 s bị báo nhầm là có thở: {np.mean(apnea >= MIN_PROM):.0%}  (ngưỡng độ nổi {MIN_PROM})")
    proms = np.array([p for _, _, p, _, _ in rows])
    for th in (6, 8, 9, 10, 12):
        keep = proms >= th
        acc = np.mean([abs(e - b) <= 2 for (b, e, *_), k in zip(rows, keep) if k and e is not None]) if keep.any() else 0
        print(f"    ngưỡng {th:>2}: trả lời {keep.mean():.0%}, đúng khi trả lời {acc:.0%}, "
              f"nín thở bị báo có thở {np.mean(apnea >= th):.0%}")
    return kq


if __name__ == "__main__":
    _danh_gia()
