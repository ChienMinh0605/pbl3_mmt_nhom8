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
nửa đầu window – ngã: mạnh rồi yên hẳn).
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


def window_features(amps, rssi, prefix="", kept=None, shape=False):
    """amps: (số mẫu, số sóng mang con), rssi: (số mẫu,). Trả về {tên cột: giá trị} của một RX."""
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
        m = np.nanmean(amps[:, kept], axis=1)
        m = m / max(np.nanmean(m), 1e-9)
        sm = np.convolve(m, np.ones(10) / 10, "valid") if len(m) >= 20 else m
        out[f"{prefix}shape_peak"] = float(np.nanmax(np.abs(sm[10:] - sm[:-10]))) if len(sm) > 10 else 0.0
        h = len(m) // 2
        out[f"{prefix}shape_ratio"] = float(np.nanstd(m[h:]) / max(np.nanstd(m[:h]), 1e-9)) if h > 1 else 1.0
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
                row.update(window_features(amp[i:j], rssi[i:j], prefix=p, shape=True))
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
