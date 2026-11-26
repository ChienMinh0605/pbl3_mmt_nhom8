#!/usr/bin/env python3
"""Tiền xử lý + trích đặc trưng từ buổi thu (đặc tả v0.3, mục 5 và 5.2). Dashboard gọi lại đúng các hàm ở đây để đặc
trưng lúc chạy thời gian thực giống hệt lúc train.

    python features.py                         # mọi buổi trong ../data/raw → ../data/features/<buổi>.csv (window 6 s)
    python features.py --dong-tac              # → ../data/features_action/<buổi>.csv (window động tác 3 s, trượt 0,5 s)
    python features.py ../data/raw/20261123_1200_sim1 --out /tmp/x

Mục 5 – mỗi dòng một window 6 s không chồng lấn: session_id, win_start, win_end, <board>_n_samples, valid,
label_detail, label, activity, n_people, breath_rate, và với mỗi RX: <board>_rssi_{var,mad,range,iqr},
<board>_csi_{var,mad,range,iqr}_<kk> (4 đặc trưng độ phân tán của bài báo 2 cho từng sóng mang con).
Window cắt ngang chỗ đổi trạng thái, nằm trong PAUSE hoặc trước nhãn đầu tiên thì bỏ; window thiếu mẫu (< 70 % ở bất kỳ
RX nào) vẫn ghi với valid = 0.

Mục 5.2 – window 3 s trượt 0,5 s, chỉ khi có đúng 1 người: action = động tác nếu trùng ≥ 2 s với đoạn động tác
[t − 0,5; t + 2,5] (t = lúc bấm), NONE nếu không trùng động tác nào, còn lại bỏ. Thêm 2 đặc trưng hình dạng cho mỗi RX:
<board>_shape_peak (biến thiên lớn nhất trong 0,1 s của biên độ trung bình) và <board>_shape_ratio (độ dao động nửa sau /
nửa đầu window – ngã: mạnh rồi yên hẳn), và các đặc trưng chuyển động trên thành phần chính PC1 (motion_features):
<board>_shape_pc1 (tỉ phần PC1), _cvmed/_cvmax (độ dao động tương đối các sóng mang con), _b0.._b4 (log năng lượng
theo dải tần BANDS), _slope/_pos (độ lớn, vị trí cú biến đổi lớn nhất), _after/_before (độ yên sau / trước nó), _busy.
Bộ gọn bền với gói hỏng (25 cột mỗi board, bộ khuyên dùng cho board, xem robust_features), tính trên các gói còn lại
sau khi bỏ gói hỏng: <board>_mon_* = motion_features + tail, head, lvl, width trên biên độ đã chia cho biên độ trung
bình của chính gói đó (bỏ dao động khuếch đại AGC chung mọi sóng mang con); <board>_mot_b0.._b4, _peak, _ratio = năng
lượng 5 dải và peak, ratio trên biên độ chưa chia; <board>_mot_bad = tỉ lệ gói bị bỏ.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nhan import ACTION_WINDOW, ACTIONS, ACTIVITY, PRESENCE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SPEC_VERSION = "0.3"
STATS = ("var", "mad", "range", "iqr")
NULL_64 = [0, 1] + list(range(27, 38))                     # len 128 (64 sóng mang con LLTF): bỏ sóng mang con rỗng
BREATHING = ("STILL", "DOWN", "BREATH_ABN")


# --------------------------------------------------------------------------- đọc dữ liệu
def csi_amplitude(csi_hex, first_word_invalid=False):
    """csi_hex → biên độ từng sóng mang con. Mỗi sóng mang con 2 byte int8: byte đầu phần ảo, byte sau phần thực
    (đặc tả mục 3.2) – luôn đọc theo cặp (2i, 2i+1)."""
    raw = np.frombuffer(bytes.fromhex(csi_hex), dtype=np.int8).astype(float)
    amp = np.hypot(raw[1::2], raw[0::2])
    if first_word_invalid:
        amp[:2] = np.nan                                    # 4 byte đầu = 2 sóng mang con đầu không hợp lệ
    return amp


def kept_subcarriers(n_sub):
    """52 sóng mang con (len 104): giữ hết; 64 (len 128): bỏ các sóng mang con rỗng."""
    return list(range(n_sub)) if n_sub != 64 else [k for k in range(64) if k not in NULL_64]


def load_session(d):
    """Đọc một buổi thu. Trả về meta, {board: (host_time, biên độ (n, số sóng mang con), rssi)}, bảng labels."""
    d = Path(d)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    csi = pd.read_csv(d / "csi.csv", dtype={"csi_hex": str})
    if "board" not in csi.columns:                          # buổi thu v0.2: một RX
        csi["board"] = "RX1"
    boards = {}
    for b, g in csi.groupby("board", sort=True):
        g = g[g["len"] == g["len"].mode().iloc[0]]          # bỏ vài dòng lạc độ dài
        raw = np.frombuffer(bytes.fromhex("".join(g["csi_hex"])), dtype=np.int8).astype(float)
        raw = raw.reshape(len(g), -1)
        amp = np.hypot(raw[:, 1::2], raw[:, 0::2])
        fwi = g["first_word_invalid"].to_numpy() == 1
        amp[fwi, :2] = np.nan
        boards[str(b)] = (g["host_time"].to_numpy(float), amp, g["rssi"].to_numpy(float))
    labels = pd.read_csv(d / "labels.csv") if (d / "labels.csv").exists() else pd.DataFrame(
        columns=["host_time", "event", "value"])
    return meta, boards, labels


# --------------------------------------------------------------------------- đặc trưng
def spread_stats(x, axis=0):
    """4 đặc trưng độ phân tán theo bài báo 2: phương sai, MAD (độ lệch tuyệt đối trung bình), max − min, IQR."""
    x = np.asarray(x, dtype=float)
    mean = np.nanmean(x, axis=axis, keepdims=True)
    q75, q25 = np.nanpercentile(x, [75, 25], axis=axis)
    return {"var": np.nanvar(x, axis=axis), "mad": np.nanmean(np.abs(x - mean), axis=axis),
            "range": np.nanmax(x, axis=axis) - np.nanmin(x, axis=axis), "iqr": q75 - q25}


BANDS = ((0.3, 1.0), (1.0, 3.0), (3.0, 8.0), (8.0, 20.0), (20.0, 40.0))   # Hz: ~ tốc độ đổi độ dài đường truyền


def motion_features(a, rate=100.0, extra=False):
    """Đặc trưng chuyển động của window động tác trên thành phần chính PC1 của biên độ tương đối các sóng mang con
    (mọi sóng mang con cùng đổi theo một chuyển động lớn của người; PC1 gom lại, bớt nhiễu riêng từng sóng mang con).
    a: (số mẫu, số sóng mang con) đã chọn sóng mang con. Trả về {tên: giá trị} chưa có tiền tố board.
    extra: thêm 4 đặc trưng tách ngã khỏi đi lại / nằm xuống: tail, head (độ dao động PC1 trong 1 s cuối / đầu so với cả
    window – ngã xong thì yên), lvl (PC1 lệch hẳn giữa 0,5 s cuối và đầu – tư thế đổi), width (số giây quanh cú lớn nhất
    mà độ đổi còn ≥ nửa đỉnh – ngã ngắn, nằm xuống dài, đi lại thì liền nhau)."""
    a = a[:, np.all(np.isfinite(a), axis=0)]
    rel = a / np.maximum(a.mean(axis=0), 1e-6) - 1             # biên độ tương đối: không phụ thuộc mức tín hiệu
    cv = rel.std(axis=0)
    rel = rel - rel.mean(axis=0)
    # PC1 bằng lặp lũy thừa trên ma trận hiệp phương sai K × K: svd/eigh của LAPACK chậm hơn ~30 lần khi máy bận
    c = rel.T @ rel
    v = c[:, np.argmax(np.diag(c))].copy()
    for _ in range(30):
        v = c @ v
        v /= max(np.linalg.norm(v), 1e-12)
    s = rel @ v / np.sqrt(rel.shape[1])                         # PC1, cùng thang với biên độ tương đối
    out = {"shape_pc1": float(v @ c @ v / max(np.trace(c), 1e-12)),   # chuyển động lớn → PC1 chiếm phần lớn
           "shape_cvmed": float(np.median(cv)), "shape_cvmax": float(cv.max())}
    p = np.abs(np.fft.rfft((s - s.mean()) * np.hanning(len(s)))) ** 2 / len(s)
    f = np.fft.rfftfreq(len(s), 1 / rate)
    for i, (lo, hi) in enumerate(BANDS):
        out[f"shape_b{i}"] = float(np.log10(p[(f >= lo) & (f < hi)].sum() + 1e-9))
    # cú biến đổi lớn nhất: độ đổi trong 0,2 s của PC1 đã làm trơn 0,1 s; vị trí 0–1 trong window
    w = max(int(round(0.1 * rate)), 1)
    sm = np.convolve(s, np.ones(w) / w, "valid")
    d = np.abs(sm[2 * w:] - sm[:-2 * w]) if len(sm) > 2 * w else np.zeros(1)
    k = int(np.argmax(d))
    top = max(d[k], 1e-12)
    # độ yên trước / sau cú biến đổi (ngã: mạnh rồi yên hẳn) và phần thời gian có chuyển động, so với cú lớn nhất
    after, before = d[k + 3 * w:], d[:max(k - 3 * w, 0)]
    out.update(shape_slope=float(d[k]), shape_pos=float((k + 1.5 * w) / len(s)),
               shape_after=float(after.mean() / top) if len(after) else 1.0,
               shape_before=float(before.mean() / top) if len(before) else 1.0,
               shape_busy=float(np.mean(d > 0.3 * top)))
    if extra:
        q, h, sd = max(int(rate), 2), max(int(0.5 * rate), 2), max(s.std(), 1e-9)
        hi = d > 0.5 * top
        lo_, hi_ = k, k                                         # đoạn liền quanh k còn ≥ nửa đỉnh
        while lo_ > 0 and hi[lo_ - 1]:
            lo_ -= 1
        while hi_ + 1 < len(d) and hi[hi_ + 1]:
            hi_ += 1
        out.update(shape_tail=float(s[-q:].std() / sd), shape_head=float(s[:q].std() / sd),
                   shape_lvl=float(abs(s[-h:].mean() - s[:h].mean()) / sd), shape_width=float((hi_ - lo_ + 1) / rate))
    return out


def peak_ratio(a):
    """shape_peak, shape_ratio trên biên độ trung bình các sóng mang con (xem docstring đầu file)."""
    m = np.nanmean(a, axis=1)
    m = m / max(np.nanmean(m), 1e-9)
    sm = np.convolve(m, np.ones(10) / 10, "valid") if len(m) >= 20 else m
    h = len(m) // 2
    return {"shape_peak": float(np.nanmax(np.abs(sm[10:] - sm[:-10]))) if len(sm) > 10 else 0.0,
            "shape_ratio": float(np.nanstd(m[h:]) / max(np.nanstd(m[:h]), 1e-9)) if h > 1 else 1.0}


BAD_LOG = 0.5     # gói hỏng: biên độ trung bình lệch > e^0,5 ≈ 1,65 lần so với trung vị window (gói hỏng ×2–4)


def good_packets(a):
    """Mặt nạ gói CSI không hỏng: |log(biên độ TB gói / trung vị các gói)| < BAD_LOG. Dùng trung vị vì vài gói hỏng
    (khung Wi-Fi khác chồng lên) không kéo lệch nó; người cử động chỉ đổi biên độ TB vài % vì AGC bù ~90 %.
    Bỏ > nửa số gói thì coi như không lọc được (trả về toàn True)."""
    m = np.nanmean(a, axis=1)
    g = np.abs(np.log(np.maximum(m, 1e-9) / max(np.nanmedian(m), 1e-9))) < BAD_LOG
    return g if g.sum() >= 0.5 * len(g) else np.ones(len(g), bool)


def robust_features(a, rate=100.0):
    """Bộ gọn cho board (25 cột, chưa có tiền tố): bỏ gói hỏng rồi tính motion_features(extra) trên biên độ chia cho
    trung bình của từng gói (mon_, 17 cột), và năng lượng 5 dải + peak, ratio trên biên độ chưa chia (mot_, 7 cột) +
    mot_bad. mon_ chỉ thấy sự đổi hình dạng phổ theo sóng mang con, bền với AGC; mot_ thêm sự đổi chung mọi sóng mang con
    (người che sóng). Giữ ít cột mot_ vì trên WiFall (CSI thật) thêm các cột mot_ khác làm F1 tụt (dao động AGC thật
    lấn tín hiệu chung), còn trên mô phỏng các dải mot_b* giúp nhiều nhất."""
    g = good_packets(a)
    a = a[g][:, np.all(np.isfinite(a[g]), axis=0)]
    out = {"mot_bad": float(1 - g.mean())}
    m = {**motion_features(a, rate), **peak_ratio(a)}
    out.update({"mot_" + k[6:]: m[k] for k in [f"shape_b{i}" for i in range(len(BANDS))] + ["shape_peak", "shape_ratio"]})
    n = a / np.maximum(a.mean(axis=1, keepdims=True), 1e-9)   # peak/ratio của n luôn ~ hằng số nên không tính
    out.update({"mon_" + k[6:]: v for k, v in motion_features(n, rate, True).items()})
    return out


def _check_motion_features():
    """Tự kiểm tra: cú đổi mạnh ở giữa rồi yên → slope lớn, vị trí ~0,5, after nhỏ; nhiễu trắng → after ~ before."""
    rng = np.random.default_rng(0)
    t = np.arange(300) / 100
    step = np.where(t > 1.5, 0.3, 0.0)[:, None] * rng.uniform(0.5, 1.5, 52)
    f = motion_features(10 + 10 * step + 0.05 * rng.standard_normal((300, 52)))
    assert f["shape_slope"] > 0.1 and abs(f["shape_pos"] - 0.5) < 0.05 and f["shape_after"] < 0.3, f
    g = motion_features(10 + 0.05 * rng.standard_normal((300, 52)))
    assert g["shape_slope"] < f["shape_slope"] / 5 and g["shape_after"] > 0.3, g
    e = motion_features(10 + 10 * step + 0.05 * rng.standard_normal((300, 52)), extra=True)
    assert e["shape_tail"] < 0.2 and e["shape_lvl"] > 1.5 and e["shape_width"] < 0.5, e
    # người yên + 3 % gói hỏng (×3): lọc bỏ đúng các gói đó, năng lượng dải cao mot_b4 không vọt lên như shape_b4
    x = 10 * rng.uniform(0.5, 1.5, 52) * (1 + 0.05 * rng.standard_normal((300, 52)))
    bad = rng.random(300) < 0.03
    x[bad] *= 3
    assert np.array_equal(~good_packets(x), bad)
    r, s = robust_features(x), motion_features(x)
    assert abs(r["mot_bad"] - bad.mean()) < 1e-9 and r["mot_b4"] < s["shape_b4"] - 1 and len(r) == 25, (r, s)


def breath_band(x, rate=100.0):
    """Dải thở 0,1–0,6 Hz của tín hiệu x: hạ mẫu còn 10 Hz (TB mỗi 0,1 s), bỏ TB, công suất các bin DFT trong dải.
    6 s → 60 điểm, chỉ 3 bin (1/6, 2/6, 3/6 Hz): trên board tính DFT 3 bin bằng bảng cos/sin sẵn, không cần FFT.
    → (log10 công suất dải, tỉ phần phương sai nằm trong dải 0–1). Người ngồi yên vẫn thở; phòng trống thì không."""
    h = max(int(round(rate / 10)), 1)
    n = len(x) // h
    y = np.asarray(x[:n * h], float).reshape(n, h).mean(axis=1)
    y = y - y.mean()
    f = np.fft.rfftfreq(n, h / rate)
    b = float((np.abs(np.fft.rfft(y)[(f >= 0.1) & (f <= 0.6) & (f > 0)]) ** 2).sum() / max(n, 1))
    return float(np.log10(b + 1e-12)), float(min(2 * b / max(float((y ** 2).sum()), 1e-12), 1.0))   # Parseval


def compact6_features(a, rssi, rate=100.0):
    """Bộ gọn window 6 s cho board (19 cột, chưa có tiền tố): vẫn 4 đặc trưng độ phân tán của bài báo 2 (var, mad,
    range, iqr) nhưng trên 4 tín hiệu đã gom thay cho RSSI + 52 sóng mang con: rssi, lvl (biên độ TB các sóng mang con
    của từng gói / TB cả window − 1: người che sóng, không phụ thuộc mức tín hiệu), pc1, pc2 (2 thành phần chính của
    biên độ tương đối các sóng mang con: chuyển động làm mọi sóng mang con đổi cùng nhau) → 16 cột; thêm br_pc1, brf_pc1
    (dải thở của pc1, tách "người ngồi yên" khỏi "phòng trống", kế hoạch mục 3) và bad_pkt (tỉ lệ gói hỏng bị bỏ).
    Trên board: 4 dãy × 600 số cần sắp xếp cho IQR thay vì 53, PC bằng lặp lũy thừa như motion_features."""
    g = good_packets(a)
    a, rssi = a[g], np.asarray(rssi, float)[g]
    # shortcut: bỏ gói hỏng/mất làm co trục thời gian vài % (lệch nhẹ tần số dải thở), cần chính xác hơn thì dùng lưới
    # thời gian như danh_gia_canh_bao.luoi
    a = a[:, np.all(np.isfinite(a), axis=0)]
    m = a.mean(axis=1)
    rel = a / np.maximum(a.mean(axis=0), 1e-6) - 1
    rel = rel - rel.mean(axis=0)
    c, pcs = rel.T @ rel, []
    for _ in range(2):                                          # PC1 rồi PC2 (trừ PC1 khỏi ma trận hiệp phương sai)
        v = c[:, np.argmax(np.diag(c))].copy()
        for _ in range(30):
            v = c @ v
            v /= max(np.linalg.norm(v), 1e-12)
        pcs.append(rel @ v / np.sqrt(rel.shape[1]))
        c = c - (v @ c @ v) * np.outer(v, v)
    sig = {"rssi": rssi, "lvl": m / max(m.mean(), 1e-9) - 1, "pc1": pcs[0], "pc2": pcs[1]}
    out = {f"{s}_{k}": float(v) for k, x in sig.items() for s, v in spread_stats(x).items()}
    out["br_pc1"], out["brf_pc1"] = breath_band(pcs[0], rate)
    out["bad_pkt"] = float(1 - g.mean())
    return out


def _check_compact6():
    """Tự kiểm tra bộ gọn 6 s: thở 0,25 Hz → tỉ phần dải thở cao, nhiễu trắng → thấp; đổi mức khuếch đại chung không đổi
    cột CSI nào (chỉ RSSI); gói hỏng được đếm và bỏ."""
    rng = np.random.default_rng(1)
    t = np.arange(600) / 100
    w = rng.uniform(0.5, 1.5, 52)
    tho = 10 * w * (1 + 0.02 * np.sin(2 * np.pi * 0.25 * t)[:, None] * rng.uniform(-1, 1, 52)
                    + 0.002 * rng.standard_normal((600, 52)))
    yen = 10 * w * (1 + 0.002 * rng.standard_normal((600, 52)))
    rs = -40 + rng.standard_normal(600)
    f, e = compact6_features(tho, rs), compact6_features(yen, rs)
    assert len(f) == 19 and f["brf_pc1"] > 0.8 and e["brf_pc1"] < 0.3 and f["br_pc1"] > e["br_pc1"] + 2, (f, e)
    k = compact6_features(3 * tho, rs)
    assert all(abs(k[c] - f[c]) <= 1e-6 * max(abs(f[c]), 1e-3) for c in f), (k, f)
    x = yen.copy()
    bad = rng.random(600) < 0.03
    x[bad] *= 3
    assert abs(compact6_features(x, rs)["bad_pkt"] - bad.mean()) < 1e-9


def window_features(amps, rssi, prefix="", kept=None, shape=False, rate=100.0):
    """amps: (số mẫu, số sóng mang con), rssi: (số mẫu,). Trả về {tên cột: giá trị} của một RX.
    rate: số mẫu/giây (cho dải tần): mặc định 100 như đặc tả, WiFall ~84. Window 6 s (shape=False) có thêm 19 cột
    <board>_g6_* (compact6_features)."""
    amps = np.asarray(amps, dtype=float)
    kept = kept_subcarriers(amps.shape[1]) if kept is None else kept
    out = {}
    r = spread_stats(rssi)
    for s in STATS:
        out[f"{prefix}rssi_{s}"] = float(r[s])
    c = spread_stats(amps[:, kept], axis=0)
    for s in STATS:
        for k, v in zip(kept, c[s]):
            out[f"{prefix}csi_{s}_{k:02d}"] = float(v)
    if shape:
        out.update({prefix + k: v for k, v in peak_ratio(amps[:, kept]).items()})
        out.update({prefix + k: v for k, v in motion_features(amps[:, kept], rate).items()})
        out.update({prefix + k: v for k, v in robust_features(amps[:, kept], rate).items()})
    else:
        out.update({prefix + "g6_" + k: v for k, v in compact6_features(amps[:, kept], rssi, rate).items()})
    return out


# --------------------------------------------------------------------------- nhãn
class Labels:
    """Tra cứu nhãn theo thời gian: trạng thái, số người, nhịp thở đáp án, các đoạn động tác."""

    def __init__(self, labels):
        lab = labels.sort_values("host_time")
        st = lab[lab["event"] == "STATE"]
        self.state_t, self.state_v = st["host_time"].to_numpy(float), st["value"].to_numpy(str)
        cnt = lab[lab["event"] == "COUNT"]
        self.count_t = cnt["host_time"].to_numpy(float)
        self.count_v = np.cumsum(cnt["value"].astype(int).to_numpy())
        rt = lab[lab["event"] == "RATE"]
        self.rate_t, self.rate_v = rt["host_time"].to_numpy(float), rt["value"].astype(float).to_numpy()
        act = lab[(lab["event"] == "ACTION") & lab["value"].isin(ACTIONS)]
        self.actions = [(float(t) + ACTION_WINDOW[0], float(t) + ACTION_WINDOW[1], v)
                        for t, v in zip(act["host_time"], act["value"])]

    def state(self, a, b):
        """Trạng thái duy nhất trong [a, b), None nếu đổi trạng thái giữa chừng hoặc chưa có nhãn."""
        i = np.searchsorted(self.state_t, a, side="right") - 1
        if i < 0 or (i + 1 < len(self.state_t) and self.state_t[i + 1] < b):
            return None
        return self.state_v[i]

    def people(self, t):
        i = np.searchsorted(self.count_t, t, side="right") - 1
        return int(self.count_v[i]) if i >= 0 else 0

    def rate(self, t, state):
        """Nhịp thở đáp án: RATE gần nhất trước t, nếu từ đó tới t người vẫn ở trạng thái thở."""
        i = np.searchsorted(self.rate_t, t, side="right") - 1
        if i < 0 or state not in BREATHING:
            return np.nan
        j0, j1 = np.searchsorted(self.state_t, [self.rate_t[i], t], side="right")
        if any(v not in BREATHING for v in self.state_v[j0:j1]):
            return np.nan
        return float(self.rate_v[i])


def _cut(times, a, b):
    return np.searchsorted(times, a), np.searchsorted(times, b)


# --------------------------------------------------------------------------- window
def session_windows(d, window=6.0, rate=100.0, valid_ratio=0.7):
    """Mục 5: window 6 s không chồng lấn → DataFrame."""
    meta, boards, labels = load_session(d)
    L = Labels(labels)
    t0 = min(v[0][0] for v in boards.values())
    t1 = max(v[0][-1] for v in boards.values())
    rows = []
    for a in np.arange(t0, t1 - window + 1e-9, window):
        b = a + window
        st = L.state(a, b)
        if st is None or st == "PAUSE" or st not in PRESENCE:
            continue
        row = {"session_id": meta["session_id"], "win_start": round(a, 4), "win_end": round(b, 4)}
        ok = True
        for name, (t, amp, rssi) in boards.items():
            i, j = _cut(t, a, b)
            p = name.lower() + "_"
            row[p + "n_samples"] = j - i
            ok &= (j - i) >= valid_ratio * rate * window
            if j - i >= 2:
                row.update(window_features(amp[i:j], rssi[i:j], prefix=p))
        mid = (a + b) / 2
        row.update({"valid": int(ok), "label_detail": st, "label": PRESENCE[st], "activity": ACTIVITY[st],
                    "n_people": L.people(mid), "breath_rate": L.rate(mid, st)})
        rows.append(row)
    return meta, pd.DataFrame(rows)


def action_windows(d, window=3.0, step=0.5, rate=100.0, valid_ratio=0.7):
    """Mục 5.2: window động tác 3 s trượt 0,5 s, chỉ khi có đúng 1 người → DataFrame."""
    meta, boards, labels = load_session(d)
    L = Labels(labels)
    t0 = min(v[0][0] for v in boards.values())
    t1 = max(v[0][-1] for v in boards.values())
    rows = []
    for a in np.arange(t0, t1 - window + 1e-9, step):
        b = a + window
        overlap = [(min(b, e) - max(a, s), v) for s, e, v in L.actions if min(b, e) > max(a, s)]
        big = [v for o, v in overlap if o >= 2.0]
        if big:
            action = big[0]
        elif not overlap:
            action = "NONE"
        else:
            continue                                        # trùng một phần: không rõ nhãn
        mid = (a + b) / 2
        i = np.searchsorted(L.state_t, mid, side="right") - 1
        state = L.state_v[i] if i >= 0 else None
        if state in (None, "PAUSE") or L.people(mid) != 1:
            continue
        row = {"session_id": meta["session_id"], "win_start": round(a, 4), "win_end": round(b, 4)}
        ok = True
        for name, (t, amp, rssi) in boards.items():
            i, j = _cut(t, a, b)
            p = name.lower() + "_"
            row[p + "n_samples"] = j - i
            ok &= (j - i) >= valid_ratio * rate * window
            if j - i >= 20:
                row.update(window_features(amp[i:j], rssi[i:j], prefix=p, shape=True, rate=rate))
        row.update({"valid": int(ok), "n_people": 1, "action": action, "state": state})
        rows.append(row)
    return meta, pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="Trích đặc trưng từ buổi thu (đặc tả v0.3, mục 5 và 5.2).")
    ap.add_argument("sessions", nargs="*", help="thư mục buổi thu (mặc định: mọi buổi trong ../data/raw)")
    ap.add_argument("--dong-tac", action="store_true", help="window động tác 3 s (mục 5.2) thay cho window 6 s")
    ap.add_argument("--out", help="thư mục ghi (mặc định ../data/features hoặc ../data/features_action)")
    ap.add_argument("--rate", type=float, default=100)
    args = ap.parse_args()
    _check_motion_features()
    _check_compact6()
    dirs = [Path(s) for s in args.sessions] or sorted(p for p in (ROOT / "data" / "raw").glob("*") if p.is_dir())
    dirs = [d for d in dirs if (d / "csi.csv").exists() and (d / "meta.json").exists()]
    if not dirs:
        sys.exit("Không có buổi thu nào (cần csi.csv và meta.json).")
    out = Path(args.out or ROOT / "data" / ("features_action" if args.dong_tac else "features"))
    out.mkdir(parents=True, exist_ok=True)
    fmeta = {"spec_version": SPEC_VERSION, "window_s": 3.0 if args.dong_tac else 6.0,
             "step_s": 0.5 if args.dong_tac else 6.0, "expected_rate_hz": args.rate, "valid_ratio": 0.7,
             "boards": set(), "csi_len": set(), "denoise": None, "simulated": False, "sessions": []}
    for d in dirs:
        meta, df = (action_windows if args.dong_tac else session_windows)(d, rate=args.rate)
        if df.empty:
            print(f"  {d.name}: không có window nào (chưa có nhãn?)")
            continue
        df.to_csv(out / f"{meta['session_id']}.csv", index=False)
        fmeta["boards"] |= {c.split("_")[0].upper() for c in df.columns if c.endswith("_n_samples")}
        fmeta["csi_len"].add(2 * (max(int(c.rsplit("_", 1)[1]) for c in df.columns if "_csi_var_" in c) + 1))
        fmeta["simulated"] |= bool(meta.get("simulated"))
        fmeta["sessions"].append(meta["session_id"])
        info = df["action"].value_counts().to_dict() if args.dong_tac else df["label_detail"].value_counts().to_dict()
        print(f"  {d.name}: {len(df)} window, hợp lệ {int(df['valid'].sum())} | {info}")
    fmeta["boards"], fmeta["csi_len"] = sorted(fmeta["boards"]), sorted(fmeta["csi_len"])
    (out / "feature_meta.json").write_text(json.dumps(fmeta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Đã ghi {len(fmeta['sessions'])} buổi vào {out}")


if __name__ == "__main__":
    main()
