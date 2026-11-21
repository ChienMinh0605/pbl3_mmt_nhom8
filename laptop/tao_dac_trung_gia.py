#!/usr/bin/env python3
"""Sinh file đặc trưng GIẢ đúng định dạng mục 5 của đặc tả, để thử train.py khi chưa có dữ liệu thật.

Ví dụ:
    python tao_dac_trung_gia.py                       # 6 buổi thu, mỗi buổi 30 phút
    python tao_dac_trung_gia.py --sessions 8 --minutes 40

Dữ liệu được ghi vào ../data/features_gia/ (tách riêng khỏi ../data/features/ của dữ liệu thật).

Cách sinh (đơn giản hoá, chỉ để thử code):
- Mỗi window có 4 đặc trưng độ phân tán cho RSSI và cho 51 sóng mang con.
- Độ dao động phụ thuộc nhãn: EMPTY thấp, NEIGHBOR hơi cao, STILL/DOWN cao hơn một chút (khó tách khỏi EMPTY),
  ACTIVE cao rõ rệt.
- Mỗi buổi thu có "hệ số phòng" và độ nhạy từng sóng mang con riêng, để mô phỏng việc kết quả thay đổi giữa
  các buổi (như hiện tượng cross-domain trong bài báo 2).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "features_gia"

KEPT = [k for k in range(64) if k not in (0, 1) and not 27 <= k <= 37]      # 51 sóng mang con
# mức tăng phương sai so với phòng trống: (CSI, RSSI)
SCALE = {"EMPTY": (1.0, 1.0), "NEIGHBOR": (1.4, 1.6), "STILL": (2.0, 1.3), "DOWN": (1.7, 1.2), "ACTIVE": (7.0, 4.0)}
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nhan import ACTIVITY, PRESENCE as BINARY  # noqa: E402


def spread_features(var, rng):
    """Từ phương sai thật, sinh 4 đặc trưng có nhiễu (var, mad, range, iqr)."""
    sd = np.sqrt(var)
    noise = lambda: rng.lognormal(0, 0.15, size=np.shape(var))
    return var * noise(), 0.8 * sd * noise(), 6.0 * sd * noise(), 1.35 * sd * noise()


def make_session(i, minutes, t_start, rng, window=6.0, rate=100):
    room = rng.lognormal(0, 0.35)                       # buổi/phòng khác nhau thì mức nền khác nhau
    sens = rng.lognormal(0, 0.5, size=len(KEPT))         # độ nhạy từng sóng mang con
    plan = ["EMPTY", "ACTIVE", "STILL", "EMPTY", "ACTIVE", "DOWN", "NEIGHBOR", "EMPTY"]
    n_win = int(minutes * 60 // window)
    seg_len = n_win // len(plan)
    session_id = f"SIM{t_start.strftime('%Y%m%d')}_{1400 + i:04d}_gia{i + 1}"

    rows = []
    t0 = t_start.timestamp()
    for w in range(n_win):
        label = plan[min(w // seg_len, len(plan) - 1)]
        cs, rs = SCALE[label]
        n = int(rng.normal(rate * window, 15))
        if rng.random() < 0.02:
            n = int(rng.uniform(100, 400))               # window thiếu mẫu
        row = {"session_id": session_id, "win_start": round(t0 + w * window, 4),
               "win_end": round(t0 + (w + 1) * window, 4), "n_samples": n,
               "valid": int(n >= 0.7 * rate * window), "label_detail": label, "label": BINARY[label],
               "activity": ACTIVITY[label], "n_people": int(BINARY[label])}
        rv = spread_features(np.array(0.6 * room * rs), rng)
        for name, v in zip(("var", "mad", "range", "iqr"), rv):
            row[f"rssi_{name}"] = round(float(v), 4)
        cv = spread_features(1.5 * room * sens * cs * rng.lognormal(0, 0.25), rng)
        for name, v in zip(("var", "mad", "range", "iqr"), cv):
            for k, x in zip(KEPT, v):
                row[f"csi_{name}_{k:02d}"] = round(float(x), 4)
        rows.append(row)
    return session_id, pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="Sinh file đặc trưng giả để thử train.py.")
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    start = pd.Timestamp("2026-11-12 14:00")
    for i in range(args.sessions):
        sid, df = make_session(i, args.minutes, start + pd.Timedelta(days=i), rng)
        df.to_csv(out / f"{sid}.csv", index=False)
        print(f"{sid}: {len(df)} window, Empty {int((df.label == 0).sum())}, Occupied {int((df.label == 1).sum())}")
    meta = {"spec_version": "0.2", "simulated": True, "window_s": 6, "expected_rate_hz": 100, "valid_ratio": 0.7,
            "subcarriers_kept": KEPT, "denoise": None, "code_version": "tao_dac_trung_gia.py"}
    (out / "feature_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Đã ghi vào {out}")


if __name__ == "__main__":
    main()
