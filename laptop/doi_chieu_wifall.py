#!/usr/bin/env python3
"""Đối chiếu mô phỏng 3D với CSI thật của bộ WiFall (ESP32-S3, đoạn 3 giây: ngã, ngồi, đứng, đi).

    python doi_chieu_wifall.py                 # in bảng, lưu ../results/doi_chieu_wifall/{bang.csv, hinh.png}

Bốn chỉ số, tính trên biên độ đã chia cho mức trung bình của từng sóng mang con (để hai phòng khác nhau vẫn so được):
  dao_dong   độ lệch chuẩn theo thời gian, trung bình 52 sóng mang con
  bien_TB    khoảng p95 – p5 của biên độ trung bình các sóng mang con (thay đổi "chung")
  nhieu_chung  nhiễu giữa hai gói liên tiếp, phần chung mọi sóng mang con (AGC)
  nhieu_rieng  nhiễu giữa hai gói liên tiếp, phần riêng từng sóng mang con
Hai chỉ số nhiễu là tính chất phần cứng → nên khớp. Hai chỉ số đầu phụ thuộc phòng (WiFall đo ở phòng họp, mô phỏng
là góc phòng 4 × 3,5 m) → chỉ cần cùng cỡ.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

import mo_phong as sim

ROOT = Path(__file__).resolve().parent.parent
WIFALL = ROOT / "data/public/WiFall/raw/WiFall"
OUT = ROOT / "results/doi_chieu_wifall"
NAMES = ("dao_dong", "bien_TB", "nhieu_chung", "nhieu_rieng")
RATE = 84                                                       # WiFall đo được ~84 gói/giây
# kịch bản mô phỏng và động tác cần cắt (đoạn 3 giây từ 0,5 s trước lúc bắt đầu, như cách gán nhãn v0.3)
PLANS = {"fall": ("ACTIVE:6,FALL,DOWN:6", "FALL"), "sit": ("ACTIVE:6,SIT_DOWN,STILL:6", "SIT_DOWN"),
         "stand": ("ACTIVE:6,SIT_DOWN,STILL:4,STAND_UP,STILL:4", "STAND_UP"), "walk": ("ACTIVE:12", None)}


def metrics(amp):
    rel = amp / np.maximum(amp.mean(axis=0), 1e-6)
    common = rel.mean(axis=1)
    own = rel - common[:, None]
    return [rel.std(axis=0).mean(), np.percentile(common, 95) - np.percentile(common, 5),
            np.diff(common).std() / np.sqrt(2), (np.diff(own, axis=0).std(axis=0) / np.sqrt(2)).mean()]


def real():
    out = {c: [] for c in PLANS}
    for f in WIFALL.glob("*/*/*.csv"):
        c = f.parent.name.lower()
        if c not in out:
            continue
        x = np.array([json.loads(r["data"]) for r in csv.DictReader(open(f, encoding="utf-8"))], dtype=float)
        if len(x) >= 100 and x.shape[1] == 104:
            out[c].append(metrics(np.hypot(x[:, 0::2], x[:, 1::2])))   # theo cặp (2i, 2i+1)
    return out


def simulated(n_seed):
    out = {c: [] for c in PLANS}
    for c, (plan, action) in PLANS.items():
        for seed in range(n_seed):
            _, _, _, spans, rx = sim.compute(plan, seed, RATE)
            a0 = next(a for n, a, _ in spans if n == action) - 0.5 if action else 4.0
            sl = slice(int(a0 * RATE), int((a0 + 3) * RATE))
            out[c] += [metrics(np.hypot(im[sl].astype(float), re[sl].astype(float))) for im, re, _ in rx.values()]
    return out


def main():
    if not WIFALL.exists():
        sys.exit(f"Chưa có WiFall ở {WIFALL} (xem KE_HOACH_NHANH_NGUOI.md mục 5.2)")
    R, S = real(), simulated(20)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"{'động tác':9s}{'chỉ số':13s}{'WiFall':>8s}{'mô phỏng':>10s}{'tỉ lệ':>8s}")
    for c in PLANS:
        r, s = np.median(R[c], axis=0), np.median(S[c], axis=0)
        for k, a, b in zip(NAMES, r, s):
            print(f"{c:9s}{k:13s}{a:8.3f}{b:10.3f}{b / a:8.2f}")
            rows.append([c, k, round(a, 4), round(b, 4), len(R[c]), len(S[c])])
    err = np.mean([abs(np.log(r[3] / r[2])) for r in rows])
    print(f"Độ lệch trung bình (|log tỉ lệ|): {err:.2f}  ≈ lệch {np.expm1(err) * 100:.0f} %")
    with open(OUT / "bang.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["dong_tac", "chi_so", "wifall", "mo_phong", "n_wifall", "n_mo_phong"]] + rows)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.8))
    for j, (ax, k) in enumerate(zip(axes, NAMES)):
        for i, c in enumerate(PLANS):
            ax.boxplot([np.array(R[c])[:, j], np.array(S[c])[:, j]], positions=[i * 3, i * 3 + 1], widths=0.8,
                       showfliers=False, patch_artist=True,
                       boxprops=dict(facecolor="none"), medianprops=dict(color="#dc2626"))
        ax.set_xticks([i * 3 + 0.5 for i in range(len(PLANS))], list(PLANS))
        ax.set_title(k)
    fig.suptitle("Trái: WiFall (ESP32-S3 thật) · Phải: mô phỏng 3D — mỗi cặp hộp là một động tác")
    fig.tight_layout()
    fig.savefig(OUT / "hinh.png", dpi=120)
    print(f"Đã lưu {OUT / 'bang.csv'} và {OUT / 'hinh.png'}")


if __name__ == "__main__":
    main()
