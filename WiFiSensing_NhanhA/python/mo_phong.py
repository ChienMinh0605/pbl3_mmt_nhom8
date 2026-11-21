#!/usr/bin/env python3
"""MÔ PHỎNG board #1 + #2: tạo buổi thu GIẢ đúng định dạng đặc tả (mục 4), không cần phần cứng.

  py python/mo_phong.py                      # 4 buổi, mỗi trạng thái 2 phút → data_mo_phong/raw/
  py python/mo_phong.py --buoi 6 --phut 3

Mỗi buổi đi qua các trạng thái EMPTY → WALK → STATIC → NEIGHBOR → MULTI, xen giữa là PAUSE 10 s,
giống một buổi thu thật có người bấm phím ghi nhãn. Ghi ra: csi.csv, stat.csv, boot.csv,
labels.csv, meta.json – cùng cấu trúc với logger thật, nên features.py / train.py / ve_bieu_do.py
chạy y hệt trên dữ liệu thật và dữ liệu giả.

Mô hình tín hiệu (đơn giản, chỉ để thử phần mềm – KHÔNG dùng số liệu này trong báo cáo):
  EMPTY     biên độ phẳng + nhiễu
  NEIGHBOR  dao động rất nhỏ (người ở phòng bên)
  STATIC    dao động nhỏ, chậm (thở, cử động nhẹ)
  WALK      dao động lớn, nhanh hơn
  MULTI     dao động lớn nhất
"""
import argparse
import json
import os

import numpy as np

# mức dao động (tỉ lệ biên độ nền) và tần số (Hz) cho từng trạng thái
STATE_MODEL = {
    "EMPTY":    (0.00, 0.0),
    "NEIGHBOR": (0.03, 0.6),
    "STATIC":   (0.06, 0.25),
    "WALK":     (0.25, 0.9),
    "MULTI":    (0.35, 1.2),
    "PAUSE":    (0.20, 0.8),
}
GUARD = [0] + list(range(27, 38))
TX_MAC, TX_AP_MAC, RX_MAC = "84:f7:03:0a:92:9c", "84:f7:03:0a:92:9d", "84:f7:03:01:02:03"


class CsiSim:
    """Sinh luồng CSI giả cho từng mẫu: biên độ (n,64), RSSI (n,), byte IQ (n,128)."""

    def __init__(self, seed=None):
        self.rng = np.random.default_rng(seed)
        self.base = self.rng.normal(14, 3, 64).clip(3)
        self.base[GUARD] = 0
        self.gain = self.rng.uniform(0.8, 1.2)              # mỗi buổi một mức khác nhau
        self.phase_k = self.rng.uniform(0, 2 * np.pi, 64)
        self.t = 0.0
        self.state = "EMPTY"
        self._new_motion()

    def _new_motion(self):
        lvl, f = STATE_MODEL[self.state]
        self.lvl = lvl * self.rng.uniform(0.7, 1.3)
        self.freqs = f * self.rng.uniform(0.6, 1.4, 3) if f else np.zeros(3)
        self.ph = self.rng.uniform(0, 2 * np.pi, 3)

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self._new_motion()

    def step(self, n, rate_hz):
        tt = self.t + np.arange(n) / rate_hz
        self.t = tt[-1] + 1 / rate_hz
        m = np.zeros((n, 64))
        if self.lvl:
            for f, p in zip(self.freqs, self.ph):
                m += np.sin(2 * np.pi * f * tt[:, None] + p + self.phase_k[None, :] * 0.7) / 3
            m *= self.lvl
        amp = self.gain * self.base * (1 + m) + self.rng.normal(0, 0.8, (n, 64))
        amp[:, GUARD] = np.abs(self.rng.normal(0, 0.3, (n, len(GUARD))))
        amp = amp.clip(0)
        rssi = np.round(-40 + 3 * m.mean(axis=1) + self.rng.normal(0, 0.7, n)).astype(int)
        phase = self.rng.uniform(0, 2 * np.pi, (n, 64))
        iq = np.empty((n, 128), np.int8)
        iq[:, 0::2] = np.clip(np.round(amp * np.sin(phase)), -128, 127)
        iq[:, 1::2] = np.clip(np.round(amp * np.cos(phase)), -128, 127)
        return amp, rssi, iq


def csi_line_fields(seq, t_us, rssi, iq_row):
    """Các trường của một dòng CSI đúng mục 3.2 (không có tiền tố 'CSI')."""
    return [seq, t_us, TX_AP_MAC, rssi, -95, 6, 1, 0, 0, 128, iq_row.tobytes().hex()]


def tao_buoi(out_root, session_id, phut_moi_trang_thai, seed):
    rng = np.random.default_rng(seed)
    sim = CsiSim(seed)
    d = os.path.join(out_root, session_id)
    os.makedirs(d, exist_ok=True)
    kich_ban = []
    for s in ["EMPTY", "WALK", "STATIC", "NEIGHBOR", "MULTI"]:
        kich_ban += [("PAUSE", 10), (s, phut_moi_trang_thai * 60)]
    host0 = 1762650000.0 + seed * 3600
    t_us0 = int(rng.integers(5e6, 3e7))
    seq = 0
    f_csi = open(os.path.join(d, "csi.csv"), "w")
    f_stat = open(os.path.join(d, "stat.csv"), "w")
    f_boot = open(os.path.join(d, "boot.csv"), "w")
    f_lab = open(os.path.join(d, "labels.csv"), "w")
    f_csi.write("host_time,seq,t_us,src_mac,rssi,noise_floor,channel,sig_mode,cwb,first_word_invalid,len,csi_hex\n")
    f_stat.write("host_time,t_us,board,n_rx,n_filtered,n_queue_drop,channel\n")
    f_boot.write("host_time,board,fw,mac_sta,mac_ap,channel\n")
    f_lab.write("host_time,event,value\n")
    f_boot.write(f"{host0:.4f},TX,0.1,{TX_MAC},{TX_AP_MAC},6\n")
    f_boot.write(f"{host0:.4f},RX,0.1,{RX_MAC},{TX_AP_MAC},6\n")
    sec = 0.0
    for state, dur in kich_ban:
        sim.set_state(state)
        f_lab.write(f"{host0 + sec:.4f},STATE,{state}\n")
        for _ in range(int(dur)):
            rate = rng.uniform(88, 99)                      # tốc độ thật dao động quanh 95
            n = int(rate)
            amp, rssi, iq = sim.step(n, rate)
            offs = np.sort(rng.uniform(0, 1, n))
            for i in range(n):
                if rng.random() < 0.01:                     # 1% dòng bị mất trên đường truyền
                    seq += 1
                    continue
                ht = host0 + sec + offs[i] + 0.004
                tu = t_us0 + int((sec + offs[i]) * 1e6)
                f_csi.write(f"{ht:.4f}," + ",".join(map(str, csi_line_fields(seq, tu, rssi[i], iq[i]))) + "\n")
                seq += 1
            sec += 1
            f_stat.write(f"{host0 + sec:.4f},{t_us0 + int(sec * 1e6)},RX,{n},{int(rng.integers(0, 15))},0,6\n")
            if int(sec) % 30 == 0:
                f_boot.write(f"{host0 + sec:.4f},RX,0.1,{RX_MAC},{TX_AP_MAC},6\n")
    for f in (f_csi, f_stat, f_boot, f_lab):
        f.close()
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"session_id": session_id, "room": "MÔ PHỎNG", "tx_rx_distance_m": 3.0,
                   "channel": 6, "members": ["Tiên"], "fw": {"TX": "0.1", "RX": "0.1"},
                   "spec_version": "0.1", "notes": "dữ liệu giả lập – không dùng cho báo cáo"},
                  f, ensure_ascii=False, indent=2)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--buoi", type=int, default=4)
    ap.add_argument("--phut", type=float, default=2, help="số phút cho mỗi trạng thái")
    ap.add_argument("--out", default="data_mo_phong/raw")
    a = ap.parse_args()
    for b in range(1, a.buoi + 1):
        sid = f"20261109_{8 + b:02d}00_mophong{b}"
        print("  đang tạo", tao_buoi(a.out, sid, a.phut, seed=b))
    print(f"\nXong. Bước tiếp:\n  py python/features.py --raw {a.out} --out data_mo_phong/features")


if __name__ == "__main__":
    main()
