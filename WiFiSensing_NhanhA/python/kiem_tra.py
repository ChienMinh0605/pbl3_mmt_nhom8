#!/usr/bin/env python3
"""Kiểm tra nhanh một buổi thu (dùng cho buổi kiểm thử tuần đầu và sau mỗi buổi thu).

  py python/kiem_tra.py data/raw/20261112_1430_phongA

In ra: tốc độ CSI, dòng bị mất (theo seq), mất trong queue (theo STAT), len thực tế,
tỉ lệ first_word_invalid, sig_mode/cwb, thời lượng mỗi nhãn, biên độ trung bình từng sóng mang con.
"""
import os
import sys

import numpy as np
import pandas as pd

from features import SUBCARRIERS_KEPT, load_csi, load_label_segments

if len(sys.argv) < 2:
    sys.exit(__doc__)
d = sys.argv[1]
raw = pd.read_csv(os.path.join(d, "csi.csv"), dtype={"csi_hex": str, "src_mac": str})
t, rssi, amp, df = load_csi(d)
dur = t[-1] - t[0] if len(t) > 1 else 0
print(f"Buổi thu: {os.path.basename(os.path.normpath(d))}")
print(f"  {len(raw)} dòng CSI trong {dur:.0f} s → {len(raw) / max(dur, 1):.1f} dòng/giây")
seq = raw["seq"].to_numpy()
gaps = np.diff(seq)
lost = int(gaps[gaps > 0].sum() - (gaps > 0).sum())
print(f"  mất trên đường truyền (theo seq): {lost} dòng ({100 * lost / max(len(raw) + lost, 1):.2f}%)"
      + ("   [seq quay về 0 – board khởi động lại]" if (gaps < 0).any() else ""))
st = os.path.join(d, "stat.csv")
if os.path.exists(st):
    s = pd.read_csv(st)
    s = s[s["board"] == "RX"]
    if len(s):
        print(f"  STAT: n_rx trung bình {s.n_rx.mean():.1f}/giây, mất trong queue {s.n_queue_drop.sum()}, "
              f"khung sai MAC {s.n_filtered.sum()}")
print(f"  len: {raw['len'].value_counts().to_dict()}   (dự kiến 128)")
print(f"  first_word_invalid = 1: {100 * raw['first_word_invalid'].mean():.1f}%")
print(f"  sig_mode: {raw['sig_mode'].value_counts().to_dict()}   cwb: {raw['cwb'].value_counts().to_dict()}")
print(f"  RSSI trung bình {rssi.mean():.1f} dBm")
segs = load_label_segments(d, t[-1] if len(t) else 0)
if segs:
    tong = {}
    for s0, s1, v in segs:
        tong[v] = tong.get(v, 0) + (s1 - s0)
    print("  thời lượng nhãn (giây):", {k: round(v) for k, v in tong.items()})
else:
    print("  CHƯA CÓ NHÃN (labels.csv trống)")
if len(amp):
    m = amp.mean(axis=0)
    print("  biên độ trung bình theo chỉ số sóng mang con (* = đang dùng):")
    for row in range(0, 64, 8):
        print("   " + "  ".join(f"{i:2d}{'*' if i in SUBCARRIERS_KEPT else ' '}{m[i]:5.1f}"
                                for i in range(row, row + 8)))
