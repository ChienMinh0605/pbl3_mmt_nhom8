#!/usr/bin/env python3
"""DEMO THỜI GIAN THỰC nhánh A – chạy THẬT với board #2, hoặc MÔ PHỎNG không cần board.

  py python/live.py --rx COM9 --model models/model_a.joblib                 # chạy thật
  py python/live.py --mo-phong --model models/model_mo_phong.joblib         # mô phỏng

Cửa sổ hiển thị: kết quả Human: Empty / Occupied (cập nhật mỗi window 6 s, lấy đa số 3 window gần nhất),
biên độ CSI 10 giây gần nhất, và kết quả từng window.
Chế độ mô phỏng: bấm phím trong cửa sổ để đổi tình huống
  E = EMPTY   W = WALK   S = STATIC   M = MULTI   N = NEIGHBOR   (tắt bộ gõ tiếng Việt)
Cả hai chế độ dùng CÙNG hàm window_features() trong features.py.
"""
import argparse
import queue
import threading
import time
from collections import deque

import joblib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation

from features import (MIN_SAMPLES, STATE_KEYS, WINDOW_S, feature_columns, hex_to_iq,
                      iq_to_amplitude, parse_line, window_features)

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
src = ap.add_mutually_exclusive_group(required=True)
src.add_argument("--rx", help="cổng COM của board #2 (chạy thật)")
src.add_argument("--mo-phong", action="store_true", help="dùng dữ liệu giả lập")
ap.add_argument("--model", default="models/model_a.joblib")
ap.add_argument("--baud", type=int, default=921600)
a = ap.parse_args()

bundle = joblib.load(a.model)
model = bundle["model"]
all_cols = feature_columns()
col_idx = [all_cols.index(c) for c in bundle["feature_columns"]]

samples = queue.Queue()          # (host_time, rssi, amp_row)
state = {"sim": None, "sim_state": "EMPTY", "n_recv": 0}

if a.mo_phong:
    from mo_phong import CsiSim
    state["sim"] = CsiSim()
else:
    def serial_reader():
        import serial
        ser = serial.Serial(a.rx, a.baud, timeout=0.5)
        while True:
            line = ser.readline().decode("ascii", "ignore")
            p = parse_line(line)
            if p and p[0] == "CSI" and int(p[1]["len"]) == 128:
                amp = iq_to_amplitude(hex_to_iq([p[1]["csi_hex"]]))[0]
                samples.put((time.time(), float(p[1]["rssi"]), amp))
    threading.Thread(target=serial_reader, daemon=True).start()

HIEN_S = 10
buf_t, buf_amp = deque(), deque()
win = {"start": None, "t": [], "rssi": [], "amp": []}
votes = deque(maxlen=3)
hist = deque(maxlen=20)
last_sim = time.time()
ket_qua = {"text": "đang chờ window 6 giây đầu tiên...", "color": "gray", "p": None}

fig = plt.figure(figsize=(11, 7))
fig.canvas.manager.set_window_title("Nhánh A – phát hiện người bằng CSI")
ax1 = fig.add_axes([0.07, 0.50, 0.9, 0.31])
ax2 = fig.add_axes([0.07, 0.08, 0.9, 0.30])
txt = fig.text(0.5, 0.93, "", ha="center", fontsize=26, weight="bold")
sub = fig.text(0.5, 0.885, "", ha="center", fontsize=11, color="dimgray")
lines = [ax1.plot([], [], lw=0.8, label=f"sóng mang con {k}")[0] for k in (5, 15, 45)]
ax1.set_xlim(-HIEN_S, 0); ax1.set_ylim(0, 30)
ax1.set_title("Biên độ CSI (10 giây gần nhất)"); ax1.set_xlabel("giây"); ax1.legend(loc="upper left", fontsize=8)


def on_key(e):
    if state["sim"] is not None and e.key and e.key.lower() in STATE_KEYS and e.key.lower() != "p":
        state["sim_state"] = STATE_KEYS[e.key.lower()]
        state["sim"].set_state(state["sim_state"])
fig.canvas.mpl_connect("key_press_event", on_key)


def predict_window():
    n = len(win["t"])
    if n >= MIN_SAMPLES:
        f = window_features(np.array(win["amp"]), np.array(win["rssi"]))[col_idx]
        p = model.predict_proba(f[None])[0, 1]
        votes.append(int(p > 0.5))
        occ = sum(votes) * 2 > len(votes)
        hist.append((int(p > 0.5), p))
        ket_qua.update(text=f"Human: {'Occupied' if occ else 'Empty'}   (p = {p:.2f})",
                       color="tab:red" if occ else "tab:green", p=p)
    else:
        hist.append((-1, 0.0))
        ket_qua.update(text=f"window thiếu mẫu ({n} < {MIN_SAMPLES})", color="gray")
    ax2.cla()
    ax2.bar(range(len(hist)), [max(p, 0.02) for _, p in hist],
            color=["tab:red" if o == 1 else "tab:green" if o == 0 else "lightgray" for o, _ in hist])
    ax2.axhline(0.5, color="k", lw=0.6, ls="--")
    ax2.set_ylim(0, 1); ax2.set_xlim(-0.5, 19.5)
    ax2.set_title("Xác suất Occupied từng window 6 s (đỏ = Occupied, xanh = Empty)")
    ax2.set_xlabel("window gần nhất →")


def update(_):
    global last_sim
    now = time.time()
    if state["sim"] is not None:                       # sinh mẫu giả cho khoảng thời gian vừa trôi qua
        n = int((now - last_sim) * 95)
        if n > 0:
            amp, rssi, _ = state["sim"].step(n, 95)
            ts = np.linspace(last_sim, now, n, endpoint=False)
            for i in range(n):
                samples.put((ts[i], rssi[i], amp[i]))
            last_sim = now
    while not samples.empty():
        t, r, amp = samples.get()
        state["n_recv"] += 1
        buf_t.append(t); buf_amp.append(amp[[5, 15, 45]])
        if win["start"] is None:
            win["start"] = t
        if t - win["start"] >= WINDOW_S:
            predict_window()
            win.update(start=t, t=[], rssi=[], amp=[])
        win["t"].append(t); win["rssi"].append(r); win["amp"].append(amp)
    while buf_t and buf_t[0] < now - HIEN_S:
        buf_t.popleft(); buf_amp.popleft()
    if buf_t:
        x = np.array(buf_t) - now
        y = np.array(buf_amp)
        for i, ln in enumerate(lines):
            ln.set_data(x, y[:, i])
        ax1.set_ylim(0, max(30, y.max() * 1.1))
    txt.set_text(ket_qua["text"]); txt.set_color(ket_qua["color"])
    if state["sim"] is not None:
        sub.set_text(f"MÔ PHỎNG – tình huống hiện tại: {state['sim_state']}   (phím E / W / S / M / N để đổi)")
    else:
        sub.set_text(f"CHẠY THẬT – {a.rx} – {len(buf_t) / HIEN_S:.0f} mẫu CSI/giây")
    return lines


ani = FuncAnimation(fig, update, interval=200, cache_frame_data=False)
plt.show()
