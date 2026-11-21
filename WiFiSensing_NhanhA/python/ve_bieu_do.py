#!/usr/bin/env python3
"""Vẽ một buổi thu: biên độ CSI theo thời gian, nền tô màu theo nhãn, và phương sai mỗi window.

  py python/ve_bieu_do.py data/raw/20261112_1430_phongA
  py python/ve_bieu_do.py data_mo_phong/raw/20261109_0900_mophong1

Lưu thành <buổi thu>.png trong thư mục hiện tại và mở cửa sổ xem. Dùng được cho báo cáo.
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

from features import SUBCARRIERS_KEPT, WINDOW_S, denoise_db4, load_csi, load_label_segments

if len(sys.argv) < 2:
    sys.exit(__doc__)
d = sys.argv[1]
sid = os.path.basename(os.path.normpath(d))
t, rssi, amp, _ = load_csi(d)
t0 = t[0]
segs = load_label_segments(d, t[-1])
COLORS = {"EMPTY": "#d9f2d9", "NEIGHBOR": "#e6f0ff", "STATIC": "#fff2cc", "WALK": "#ffd9d9",
          "MULTI": "#f4c7f4", "PAUSE": "#eeeeee"}

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
for s0, s1, v in segs:
    for ax in (ax1, ax2):
        ax.axvspan(s0 - t0, s1 - t0, color=COLORS.get(v, "white"), lw=0)
    ax1.text((s0 + s1) / 2 - t0, 1.01, v, transform=ax1.get_xaxis_transform(), ha="center", fontsize=8)
for k in (5, 15, 45):
    ax1.plot(t - t0, amp[:, k], lw=0.4, label=f"sóng mang con {k}")
ax1.set_ylabel("biên độ CSI")
ax1.legend(loc="upper right", fontsize=8)
ax1.set_title(sid, pad=16)

edges = np.arange(t[0], t[-1], WINDOW_S)
xs, vs = [], []
for ws in edges:
    i0, i1 = np.searchsorted(t, ws), np.searchsorted(t, ws + WINDOW_S)
    if i1 - i0 >= 64:
        a = denoise_db4(amp[i0:i1][:, SUBCARRIERS_KEPT])
        xs.append(ws - t0 + WINDOW_S / 2)
        vs.append(a.var(axis=0).mean())
ax2.bar(xs, vs, width=WINDOW_S * 0.9, color="tab:orange")
ax2.set_ylabel("phương sai TB / window 6 s")
ax2.set_xlabel("giây từ đầu buổi thu")
fig.tight_layout()
fig.savefig(f"{sid}.png", dpi=120)
print(f"Đã lưu {sid}.png")
plt.show()
