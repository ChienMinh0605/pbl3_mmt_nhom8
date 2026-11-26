#!/usr/bin/env python3
"""Kiểm chứng đặc trưng window động tác (features.py) trên WiFall – CSI thật ESP32-S3, để không "học thuộc" mô phỏng.

    python wifall_dong_tac.py              # in bảng, lưu ../results/wifall_dong_tac/bang.csv

Mỗi file WiFall là một đoạn ~3 s (~84 gói/s) của một người (thư mục ID0–ID9) làm một động tác (thư mục fall, Jump,
sit, stand, walk). Mỗi đoạn coi như một window động tác của MỘT RX (tiền tố rx1_), tính bằng đúng
features.window_features(..., shape=True). Bài toán: ngã / không ngã. Đánh giá chéo leave-one-person-out (10 lượt,
người lấy từ tên thư mục ID*). ID2 chiếm 640/928 đoạn nên báo riêng ID2 và 9 người còn lại.
So sánh nhóm cột: "cu" = đặc trưng trước đợt cải tiến, "moi" = tất cả, "gon" = bỏ 4 × 52 cột từng sóng mang con,
"mot" = bộ gọn cho board (25 cột mot_*/mon_*, features.robust_features).
"""
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import window_features  # noqa: E402
from train import build_models, cross_validate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WIFALL = ROOT / "data/public/WiFall/raw/WiFall"
OUT = ROOT / "results/wifall_dong_tac"
OLD = re.compile(r"^rx1_((rssi|csi)_(var|mad|range|iqr)(_\d{2})?|shape_(peak|ratio))$")
GROUPS = {"cu": lambda c: bool(OLD.match(c)), "moi": lambda c: True,
          "gon": lambda c: not re.search(r"_csi_[a-z]+_\d{2}$", c), "mot": lambda c: bool(re.search(r"_mo[tn]_", c))}


def load():
    rows = []
    for f in sorted(WIFALL.glob("ID*/*/*.csv")):
        d = pd.read_csv(f)
        x = np.array([json.loads(s) for s in d["data"]], dtype=float)
        if len(x) < 100 or x.shape[1] != 104:
            continue
        amp = np.hypot(x[:, 1::2], x[:, 0::2])                 # theo cặp (2i, 2i+1); byte đầu phần ảo
        t = pd.to_datetime(d["timestamp"])
        rate = (len(t) - 1) / max((t.iloc[-1] - t.iloc[0]).total_seconds(), 1e-3)   # tốc độ gói thật (~84/s)
        assert 50 < rate < 150, (f, rate)
        row = window_features(amp, d["rssi"].to_numpy(float), prefix="rx1_", shape=True, rate=rate)
        row.update(person=f.parent.parent.name, action=f.parent.name.lower())
        rows.append(row)
    return pd.DataFrame(rows)


def scores(y, p):
    tp, fp, fn = int(((p == 1) & (y == 1)).sum()), int(((p == 1) & (y == 0)).sum()), int(((p == 0) & (y == 1)).sum())
    rec, pre = tp / max(tp + fn, 1), tp / max(tp + fp, 1)
    return rec, pre, 2 * rec * pre / max(rec + pre, 1e-9)


def main():
    if not WIFALL.exists():
        sys.exit(f"Chưa có WiFall ở {WIFALL} (xem KE_HOACH_NHANH_NGUOI.md mục 5.2)")
    df = load()
    y = (df["action"] == "fall").to_numpy(int)
    groups = df["person"].to_numpy()
    id2 = groups == "ID2"
    feats = [c for c in df.columns if c.startswith("rx1_")]
    print(f"{len(df)} đoạn, {y.sum()} ngã, {len(set(groups))} người; leave-one-person-out")
    out = []
    for g, keep in GROUPS.items():
        cols = [c for c in feats if keep(c)]
        X = df[cols].to_numpy(float)
        X = np.where(np.isfinite(X), X, 0.0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cv, _ = cross_validate({k: m for k, m in build_models(cols, 2).items() if k != "nguong"}, X, y, groups, 0, 2)
        for k, r in cv.items():
            rec, pre, f1 = scores(y, r["pred"])
            r2, p2, _ = scores(y[id2], r["pred"][id2])
            r9, p9, _ = scores(y[~id2], r["pred"][~id2])
            out.append({"nhom": g, "so_cot": len(cols), "mo_hinh": k, "recall": rec, "precision": pre, "f1": f1,
                        "recall_ID2": r2, "precision_ID2": p2, "recall_9nguoi": r9, "precision_9nguoi": p9})
    res = pd.DataFrame(out)
    print(res.round(3).to_string(index=False))
    OUT.mkdir(parents=True, exist_ok=True)
    res.round(4).to_csv(OUT / "bang.csv", index=False)
    print(f"Đã lưu {OUT / 'bang.csv'}")


assert scores(np.array([1, 1, 0, 0]), np.array([1, 0, 1, 0]))[:2] == (0.5, 0.5)

if __name__ == "__main__":
    main()
