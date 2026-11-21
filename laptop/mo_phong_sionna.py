#!/usr/bin/env python3
"""Mô phỏng một buổi thu bằng dò tia Sionna RT: người di chuyển, ngồi, té ngã, thở trong phòng 3D → CSI
→ file giống hệt logger.py ghi ra. Dùng để thử thuật toán trước khi có dữ liệu thật (nhất là té ngã).

Ví dụ:
    python mo_phong_sionna.py --tag sim1                          # kịch bản mặc định (~5 phút dữ liệu)
    python mo_phong_sionna.py --tag sim2 --seed 2 --hinh          # thêm ảnh 2D (quỹ đạo + CSI) và ảnh 3D
    python mo_phong_sionna.py --tag khach1 --khach 1              # có thêm 1 người khách đi lại khi chủ nhà ở nhà
    python mo_phong_sionna.py --tag demo --phat-lai               # tính xong thì phát lại theo thời gian thực
                                                                  # → mở dashboard.py để xem như đang thu thật
    python mo_phong_sionna.py --plan "EMPTY:20,ACTIVE:40,FALL:1.5,DOWN:60" --tag nga

Kết quả ghi vào data/raw/<YYYYMMDD_HHMM_tag>/ đúng mục 4 của đặc tả (csi.csv, labels.csv, stat.csv, boot.csv,
probe.csv rỗng, meta.json có "simulated": true). Nhãn STATE và số người (COUNT) được gắn tự động theo kịch bản.

Mô hình:
- Phòng demo 5 m × 4 m × 3 m tường bê tông; phòng bên (3 m) ngăn bởi tường có ô cửa mở 0,9 m.
  TX #1 và RX #2 cao 1 m, cách nhau 3 m. Kênh 6 (2,437 GHz), 64 sóng mang con LLTF, thứ tự giống ESP32.
- Người là khối hộp 0,4 × 0,3 × 1,7 m, vật liệu như mô cơ thể ở 2,4 GHz (εr 52,7, σ 1,7 S/m).
- Hành vi người được giám sát (nhãn theo laptop/nhan.py):
    ACTIVE     đi theo điểm đích ngẫu nhiên 0,5–1,2 m/s, có lúc dừng
    STILL      ngồi yên tại chỗ, thở 12–20 nhịp/phút (ngực dịch ~4 mm)
    FALL       đổ từ đứng xuống nằm, nhanh dần, trong suốt độ dài đoạn (nên đặt 1–2 giây)
    DOWN       nằm bất động trên sàn, thở bình thường
    BREATH_ABN nằm (nếu vừa ngã) hoặc ngồi, thở nhanh nông 30–40 nhịp/phút
    NEIGHBOR   phòng demo trống, người đi ở phòng bên;  EMPTY  không ai
  --khach N: thêm N người khách đi lại trong mọi đoạn mà người được giám sát ở trong phòng.
- Dò tia ở --rt-hz khung/giây, nội suy biên độ lên --rate mẫu/giây, thêm nhiễu đo, mất gói 0,5 %,
  lượng tử về int8 như ESP32.
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from logger import FILES, SPEC_VERSION  # noqa: E402
from nhan import PRESENCE, STATES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LABELS = set(STATES)
DEFAULT_PLAN = "EMPTY:30,ACTIVE:60,STILL:45,ACTIVE:30,FALL:1.5,DOWN:45,BREATH_ABN:30,EMPTY:20,NEIGHBOR:40,EMPTY:20"

# hình học (m): phòng demo x∈[-3,2], y∈[-2,2]; tường ngăn x=2.075; phòng bên x∈[2.15,5]
ROOM = (-3.0, 2.0, -2.0, 2.0)
NEIGHBOR_ROOM = (2.15, 5.0, -2.0, 2.0)
HEIGHT = 3.0
DOOR = (0.9, 1.8)                           # ô cửa trên tường ngăn, theo trục y
TX_POS, RX_POS = (-2.0, 0.0, 1.0), (1.0, 0.0, 1.0)
AP_MAC, RX_MAC = "64:e8:33:0a:0b:0d", "64:e8:33:01:02:03"
NULLS = [0] + list(range(27, 38))           # DC và dải bảo vệ theo thứ tự chỉ số của ESP32
STAND_H, SIT_H, LYING_Z = 1.7, 1.2, 0.2     # chiều cao đứng, ngồi; tâm khối khi nằm (bề dày 0,4 m)
# mỗi người mỗi khung: x, y, z tâm, góc quay quanh trục đứng (yaw), góc ngả (pitch, π/2 = nằm), tỉ lệ chiều cao
PARK = (100.0, 100.0, -50.0, 0.0, 0.0, 1.0)  # chỗ "cất" người không có mặt
N_PEOPLE = 3


# --------------------------------------------------------------------------- kịch bản & hành vi
def parse_plan(text):
    plan = []
    for part in text.split(","):
        name, _, dur = part.strip().partition(":")
        name = name.upper()
        if name not in LABELS or not dur:
            sys.exit(f"--plan sai ở '{part}'. Dạng: NHÃN:giây, nhãn thuộc {sorted(LABELS)}")
        plan.append((name, float(dur)))
    return plan


def walker(rng, area, n, dt, start=None):
    """Đi theo điểm đích ngẫu nhiên (random waypoint), có lúc dừng ngắn. Trả về mảng (n, 2)."""
    x0, x1, y0, y1 = area[0] + 0.4, area[1] - 0.4, area[2] + 0.4, area[3] - 0.4
    pick = lambda: np.array([rng.uniform(x0, x1), rng.uniform(y0, y1)])
    p = np.clip(np.array(start, dtype=float), [x0, y0], [x1, y1]) if start is not None else pick()
    goal, speed, wait = pick(), rng.uniform(0.5, 1.2), 0.0
    out = np.empty((n, 2))
    for i in range(n):
        if wait > 0:
            wait -= dt
        else:
            d = goal - p
            dist = np.linalg.norm(d)
            if dist < speed * dt:
                p, goal, speed = goal, pick(), rng.uniform(0.5, 1.2)
                wait = rng.uniform(0, 2) if rng.random() < 0.4 else 0.0
            else:
                p = p + d / dist * speed * dt
        out[i] = p
    return avoid_devices(out)


def avoid_devices(xy, r=0.4):
    """Đẩy người ra khỏi vòng bán kính r quanh TX/RX: không ai đứng đè lên thiết bị (khối người sẽ che kín ăng-ten)."""
    xy = np.array(xy, dtype=float)
    for dev in (TX_POS, RX_POS):
        v = xy - np.array(dev[:2])
        dist = np.linalg.norm(v, axis=-1, keepdims=True)
        xy = np.where(dist < r, np.array(dev[:2]) + v / np.maximum(dist, 1e-6) * r, xy)
    return xy


def breathing(rng, tt, bpm_lo, bpm_hi, amp):
    """Dịch chuyển của ngực theo nhịp thở (m), tần số ngẫu nhiên trong [bpm_lo, bpm_hi] nhịp/phút."""
    f = rng.uniform(bpm_lo, bpm_hi) / 60
    return amp * np.sin(2 * np.pi * f * tt + rng.uniform(0, 2 * np.pi))


def build_frames(plan, rt_hz, rng, guests=0):
    """Trả về: thời điểm các khung, tư thế (khung × người × 6), nhãn từng khung, đoạn, số người mỗi đoạn."""
    dt = 1.0 / rt_hz
    room_xy = lambda: avoid_devices([rng.uniform(ROOM[0] + 0.6, ROOM[1] - 0.6), rng.uniform(ROOM[2] + 0.6, ROOM[3] - 0.6)])
    frames_all, lab_all, segs, counts, t = [], [], [], [], 0.0
    last = room_xy()                      # chỗ người được giám sát đang đứng
    lying = None                          # (x, y, yaw) nếu đang nằm trên sàn
    guest_last = [None] * guests
    for name, dur in plan:
        n = max(1, int(round(dur * rt_hz)))
        f = np.tile(np.array(PARK), (n, N_PEOPLE, 1))
        tt = np.arange(n) * dt
        p = f[:, 0]                       # người được giám sát
        if name == "ACTIVE":
            xy = walker(rng, ROOM, n, dt, last)
            p[:, :2], p[:, 2], p[:, 3:] = xy, STAND_H / 2, (0.0, 0.0, 1.0)
            last, lying = xy[-1], None
        elif name == "STILL":
            b = breathing(rng, tt, 12, 20, 0.004)
            p[:, 0], p[:, 1], p[:, 2] = last[0] + b, last[1], SIT_H / 2 + 0.5 * b
            p[:, 3:] = (0.0, 0.0, SIT_H / STAND_H)
            lying = None
        elif name == "FALL":
            yaw = rng.uniform(0, 2 * np.pi)
            u = ((np.arange(n) + 1) / n) ** 2                                   # ngã nhanh dần
            d = np.array([np.cos(yaw), np.sin(yaw)]) * (STAND_H / 2 - LYING_Z)  # tâm thân dịch theo hướng ngã
            p[:, :2] = last + np.outer(u, d)
            p[:, 2] = STAND_H / 2 + (LYING_Z - STAND_H / 2) * u
            p[:, 3], p[:, 4], p[:, 5] = yaw, u * np.pi / 2, 1.0
            lying = (*(last + d), yaw)
        elif name in ("DOWN", "BREATH_ABN"):
            lo, hi, amp = (12, 20, 0.004) if name == "DOWN" else (30, 40, 0.002)
            b = breathing(rng, tt, lo, hi, amp)
            if name == "DOWN" or lying is not None:
                if lying is None:
                    lying = (*last, rng.uniform(0, 2 * np.pi))
                p[:, 0], p[:, 1], p[:, 2] = lying[0], lying[1], LYING_Z + b
                p[:, 3:] = (lying[2], np.pi / 2, 1.0)
            else:                                                               # thở bất thường khi đang ngồi
                p[:, 0], p[:, 1], p[:, 2] = last[0] + b, last[1], SIT_H / 2 + 0.5 * b
                p[:, 3:] = (0.0, 0.0, SIT_H / STAND_H)
        elif name == "NEIGHBOR":
            p[:, :2], p[:, 2], p[:, 3:] = walker(rng, NEIGHBOR_ROOM, n, dt), STAND_H / 2, (0.0, 0.0, 1.0)
        if name == "EMPTY" or name == "NEIGHBOR":
            last, lying = room_xy(), None
        home = PRESENCE[name] == 1
        for g in range(guests):                                                 # khách chỉ có mặt khi chủ nhà ở nhà
            if home:
                xy = walker(rng, ROOM, n, dt, guest_last[g])
                f[:, g + 1, :2], f[:, g + 1, 2], f[:, g + 1, 3:] = xy, STAND_H / 2, (0.0, 0.0, 1.0)
                guest_last[g] = xy[-1]
            else:
                guest_last[g] = None
        frames_all.append(f)
        lab_all += [name] * n
        segs.append((name, t, t + n * dt))
        counts.append((1 + guests) if home else 0)
        t += n * dt
    frames = np.concatenate(frames_all)
    return np.arange(len(frames)) * dt, frames, lab_all, segs, counts


# --------------------------------------------------------------------------- dò tia
def make_scene(max_depth, samples):
    import mitsuba as mi
    import sionna.rt as rt

    scene = rt.load_scene()                                     # cảnh rỗng, tự dựng phòng bằng các khối hộp
    scene.frequency = 2.437e9
    scene.bandwidth = 20e6
    scene.tx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.rx_array = scene.tx_array
    concrete = rt.ITURadioMaterial("concrete", "concrete", thickness=0.15)
    body = rt.RadioMaterial("body", relative_permittivity=52.7, conductivity=1.7)

    def box(name, center, size, mat):
        m = mi.load_dict({"type": "cube", "to_world": mi.ScalarTransform4f().scale([s / 2 for s in size])})
        return rt.SceneObject(mi_mesh=m, name=name, radio_material=mat, position=mi.Point3f(*center))

    def wall_x(name, x, ya, yb, mat):
        """Tường mỏng trong mặt phẳng x = const (Sionna tính suy hao xuyên tường theo `thickness` của vật liệu)."""
        m = mi.Mesh(name, vertex_count=4, face_count=2, has_vertex_normals=False, has_vertex_texcoords=False)
        p = mi.traverse(m)
        h, w = HEIGHT / 2, (yb - ya) / 2                      # 2 tam giác, tâm tại gốc, nằm trong mặt phẳng x = 0
        p["vertex_positions"] = mi.Float(np.array([[0, -w, -h], [0, w, -h], [0, w, h], [0, -w, h]], dtype=np.float32).ravel())
        p["faces"] = mi.UInt32(np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32))
        p.update()
        return rt.SceneObject(mi_mesh=m, name=name, radio_material=mat, position=mi.Point3f(x, (ya + yb) / 2, HEIGHT / 2))

    x0, x1, y0, y1 = ROOM[0], NEIGHBOR_ROOM[1], ROOM[2], ROOM[3]
    cx, cy, w, d = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
    walls = [
        box("floor", (cx, cy, -0.05), (w + 0.3, d + 0.3, 0.1), concrete),
        box("ceiling", (cx, cy, HEIGHT + 0.05), (w + 0.3, d + 0.3, 0.1), concrete),
        box("wall_w", (x0 - 0.075, cy, HEIGHT / 2), (0.15, d, HEIGHT), concrete),
        box("wall_e", (x1 + 0.075, cy, HEIGHT / 2), (0.15, d, HEIGHT), concrete),
        box("wall_s", (cx, y0 - 0.075, HEIGHT / 2), (w + 0.3, 0.15, HEIGHT), concrete),
        box("wall_n", (cx, y1 + 0.075, HEIGHT / 2), (w + 0.3, 0.15, HEIGHT), concrete),
        # tường ngăn có ô cửa mở 0,9 m (giống bộ 6 "cửa mở" của bài báo 2)
        wall_x("wall_mid_a", (ROOM[1] + NEIGHBOR_ROOM[0]) / 2, y0, DOOR[0], concrete),
        wall_x("wall_mid_b", (ROOM[1] + NEIGHBOR_ROOM[0]) / 2, DOOR[1], y1, concrete),
    ]
    people = [box(f"p{k}", PARK[:3], (0.4, 0.3, STAND_H), body) for k in range(N_PEOPLE)]
    scene.edit(add=walls + people)
    scene.add(rt.Transmitter("tx", position=mi.Point3f(*TX_POS), display_radius=0.12))
    scene.add(rt.Receiver("rx", position=mi.Point3f(*RX_POS), display_radius=0.12))
    solver = rt.PathSolver()
    freqs = rt.subcarrier_frequencies(64, 312.5e3)

    def cfr(frame):
        for k in range(N_PEOPLE):
            o = scene.get(f"p{k}")
            x, y, z, yaw, pitch, hs = (float(v) for v in frame[k])
            o.position = mi.Point3f(x, y, z)
            o.orientation = mi.Point3f(yaw, pitch, 0.0)                      # pitch = π/2: nằm trên sàn
            o.scaling = mi.Vector3f(1.0, 1.0, hs)                             # người ngồi thấp hơn
        paths = solver(scene, max_depth=max_depth, samples_per_src=samples, los=True,
                       specular_reflection=True, diffuse_reflection=False, refraction=True)
        h = np.asarray(paths.cfr(frequencies=freqs, normalize_delays=False, out_type="numpy")).reshape(-1)[:64]
        return np.roll(h, 32), paths                           # thứ tự -32..31 → thứ tự chỉ số ESP32 (0..31, -32..-1)

    return scene, cfr


def ray_trace(frames, cfr):
    out = np.empty((len(frames), 64), dtype=complex)
    last_key, last_h, t0 = None, None, time.time()
    for i, f in enumerate(frames):
        key = np.round(f, 4).tobytes()
        if key != last_key:                                     # phòng trống / không ai di chuyển → dùng lại
            last_h, _ = cfr(f)
            last_key = key
        out[i] = last_h
        if i % 200 == 0 or i == len(frames) - 1:
            el = time.time() - t0
            eta = el / (i + 1) * (len(frames) - i - 1)
            print(f"\r  dò tia {i + 1}/{len(frames)} khung · {el:.0f} s · còn ~{eta:.0f} s   ", end="", flush=True)
    print()
    return out


# --------------------------------------------------------------------------- CSI giống ESP32
def to_samples(t_frames, H, rate, noise, rng, duration):
    """Nội suy biên độ lên `rate` mẫu/giây, thêm nhiễu đo, mất gói, lượng tử int8."""
    n = int(duration * rate)
    t = np.clip(np.sort(np.arange(n) / rate + rng.normal(0, 0.0005, n)), 0, duration - 1e-6)   # lệch giờ ~0,5 ms
    amp = np.empty((n, 64))
    for k in range(64):
        amp[:, k] = np.interp(t, t_frames, np.abs(H[:, k]))
    dt = t_frames[1] - t_frames[0]
    phase = np.angle(H[np.clip(np.round(t / dt).astype(int), 0, len(t_frames) - 1)])
    empty_level = np.median(np.abs(H[0][[k for k in range(64) if k not in NULLS]]))
    scale = 20.0 / empty_level                                  # biên độ phòng trống ≈ 20 như dữ liệu ESP32 thật
    z = amp * scale * np.exp(1j * phase)
    z = z + rng.normal(0, noise * 20, z.shape) + 1j * rng.normal(0, noise * 20, z.shape)
    z[:, NULLS] = 0
    re = np.clip(np.round(z.real), -127, 127).astype(np.int8)
    im = np.clip(np.round(z.imag), -127, 127).astype(np.int8)
    power = np.maximum(np.mean(amp[:, [k for k in range(64) if k not in NULLS]] ** 2, axis=1), 1e-12)
    rssi = np.round(-45 + 10 * np.log10(power / empty_level ** 2) + rng.normal(0, 0.5, len(t))).astype(int)
    keep = rng.random(len(t)) > 0.005                           # mất gói 0,5 %
    return t, im, re, rssi, keep


def write_session(args, plan, segs, t, im, re, rssi, keep, counts):
    sid = datetime.now().strftime("%Y%m%d_%H%M") + "_" + args.tag
    d = Path(args.data_dir) / "raw" / sid
    d.mkdir(parents=True, exist_ok=False)
    meta = {"session_id": sid, "room": "Phòng mô phỏng Sionna RT 5x4x3 m (+ phòng bên)", "tx_rx_distance_m": 3.0,
            "channel": 6, "members": [], "simulated": True, "ports": {"RX": None, "SNF": None}, "notes": "",
            "simulator": {"engine": "sionna-rt", "plan": args.plan, "seed": args.seed, "rt_hz": args.rt_hz,
                          "rate": args.rate, "noise": args.noise, "max_depth": args.max_depth,
                          "khach": args.khach},
            "fw": {"RX": "sim-sionna"}, "spec_version": SPEC_VERSION}
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    events = [(0.0, "boot", ["RX", "sim-sionna", RX_MAC, AP_MAC, 6])]
    prev = 0
    for (name, a, _), n in zip(segs, counts):
        events.append((a, "labels", ["STATE", name]))
        for _ in range(abs(n - prev)):
            events.append((a, "labels", ["COUNT", "+1" if n > prev else "-1"]))
        prev = n
    for _ in range(prev):
        events.append((segs[-1][2] - 0.01, "labels", ["COUNT", "-1"]))
    seq = 0
    for i in np.flatnonzero(keep):
        seq = int(i) + 1                                        # seq nhảy cóc ở gói bị mất → logger/kiem_tra đếm được
        hexs = np.column_stack([im[i], re[i]]).astype(np.int8).tobytes().hex()
        events.append((t[i], "csi", [seq, int(t[i] * 1e6), AP_MAC, int(rssi[i]), -95, 6, 1, 0, 1, 128, hexs]))
    for s in range(1, int(t[-1]) + 1):
        n_rx = int(np.sum(keep[(t >= s - 1) & (t < s)]))
        events.append((float(s), "stat", [s * 10**6, "RX", n_rx, 0, 0, 6]))
    events.sort(key=lambda e: e[0])

    files = {k: open(d / f"{k}.csv", "w", newline="", encoding="utf-8") for k in FILES}
    writers = {k: csv.writer(f) for k, f in files.items()}
    for k, w in writers.items():
        w.writerow(FILES[k])
    start = time.time()
    if args.phat_lai:
        print(f"Phát lại theo thời gian thực vào {d} (Ctrl+C để dừng). Mở dashboard.py để xem.")
    last_flush = start
    try:
        for off, k, row in events:
            if args.phat_lai:
                time.sleep(max(0.0, start + off - time.time()))
                if time.time() - last_flush > 0.2:
                    for f in files.values():
                        f.flush()
                    last_flush = time.time()
            writers[k].writerow([f"{start + off:.4f}"] + row)
    except KeyboardInterrupt:
        print("\nĐã dừng phát lại.")
    for f in files.values():
        f.close()
    meta["stats"] = {"duration_s": round(float(t[-1]), 1),
                     "lines": {"BOOT": 1, "CSI": int(keep.sum()), "PRB": 0, "STAT": int(t[-1])},
                     "lost_by_seq": {"RX/CSI": int((~keep).sum())}, "bad_lines": 0,
                     "label_events": sum(1 for e in events if e[1] == "labels")}
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return d


# --------------------------------------------------------------------------- hình
def save_figures(d, scene, cfr, t_frames, frames, labels, segs, H):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    colors = {"EMPTY": "#d4d4d8", "ACTIVE": "#ef4444", "STILL": "#f59e0b", "FALL": "#18181b", "DOWN": "#7c3aed",
              "BREATH_ABN": "#db2777", "NEIGHBOR": "#3b82f6"}
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14, 5), gridspec_kw={"width_ratios": [1, 1.4]})
    for (x0, x1, y0, y1), fc in ((ROOM, "#fafafa"), (NEIGHBOR_ROOM, "#eff6ff")):
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=fc, ec="#18181b", lw=1.5))
    ax.plot([TX_POS[0], RX_POS[0]], [TX_POS[1], RX_POS[1]], "--", c="#71717a", lw=1)
    ax.plot(*TX_POS[:2], "s", c="#18181b", ms=10)
    ax.plot(*RX_POS[:2], "o", c="#18181b", ms=10)
    ax.annotate("TX #1", TX_POS[:2], (6, 8), textcoords="offset points")
    ax.annotate("RX #2", RX_POS[:2], (6, 8), textcoords="offset points")
    ax.text(3.6, 1.7, "phòng bên", ha="center", color="#3b82f6")
    ax.plot([2.075, 2.075], DOOR, c="#fafafa", lw=5, solid_capstyle="butt")             # ô cửa
    from matplotlib.lines import Line2D
    lab = np.array(labels)
    guest = frames[:, 1:][frames[:, 1:, 2] > 0]
    ax.plot(guest[:, 0], guest[:, 1], ".", ms=1.5, c="#a1a1aa")
    handles = [Line2D([], [], ls="", marker="o", ms=5, c="#a1a1aa", label="khách")] if len(guest) else []
    for name in colors:
        p = frames[lab == name, 0]
        p = p[p[:, 2] > 0]
        if not len(p):
            continue
        if name == "FALL":                                       # chỉ đánh dấu chỗ người nằm sau khi ngã
            ax.plot(p[-1, 0], p[-1, 1], "X", ms=11, c=colors[name])
        else:
            ax.plot(p[:, 0], p[:, 1], ".", ms=1.5, c=colors[name])
        handles.append(Line2D([], [], ls="", marker="X" if name == "FALL" else "o", ms=6, c=colors[name], label=name))
    ax.set_xlim(ROOM[0] - 0.3, NEIGHBOR_ROOM[1] + 0.3)
    ax.set_ylim(ROOM[2] - 0.3, ROOM[3] + 0.3)
    ax.set_aspect("equal")
    ax.set_title("Quỹ đạo người (nhìn từ trên xuống)")
    ax.legend(handles=handles, loc="lower left", fontsize=8)

    kept = [k for k in range(64) if k not in NULLS]
    a = np.abs(H[:, kept])
    bx.plot(t_frames, a.mean(axis=1) / a[0].mean(), c="#18181b", lw=0.8)
    for name, s, e in segs:
        bx.axvspan(s, e, color=colors[name], alpha=0.18, lw=0)
        bx.text((s + e) / 2, 1.0, name, ha="center", va="bottom", fontsize=8, transform=bx.get_xaxis_transform())
    bx.set_xlabel("giây")
    bx.set_ylabel("biên độ CSI trung bình (so với phòng trống)")
    bx.set_title("CSI dò tia theo thời gian", pad=18)
    fig.tight_layout()
    fig.savefig(d / "mo_phong_2d.png", dpi=130)
    plt.close(fig)

    import mitsuba as mi
    import sionna.rt as rt
    show = next((x for x in ("DOWN", "STILL", "ACTIVE") if x in labels), labels[0])     # ưu tiên cảnh nằm sau ngã
    i = int(np.argmax(lab == show))
    for name in ("ceiling", "wall_s"):                         # bỏ trần và tường trước để nhìn vào trong
        scene.edit(remove=[name])
    cfr(frames[i])                                               # đặt người vào đúng tư thế của khung này
    cam = rt.Camera(position=mi.Point3f(-0.5, -9.0, 7.0), look_at=mi.Point3f(0.5, 0.0, 0.8))
    scene.render_to_file(camera=cam, filename=str(d / "mo_phong_3d.png"), num_samples=64,
                         resolution=(1000, 700))


# --------------------------------------------------------------------------- chương trình chính
def main():
    ap = argparse.ArgumentParser(description="Mô phỏng buổi thu bằng dò tia Sionna RT.")
    ap.add_argument("--tag", required=True, help="tên ngắn, chỉ chữ không dấu, số, '-'")
    ap.add_argument("--plan", default=DEFAULT_PLAN, help=f"kịch bản NHÃN:giây,... (mặc định {DEFAULT_PLAN})")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--khach", type=int, default=0, choices=[0, 1, 2], help="số người khách đi lại cùng lúc")
    ap.add_argument("--rt-hz", type=float, default=10, help="số khung dò tia mỗi giây")
    ap.add_argument("--rate", type=float, default=100, help="số mẫu CSI mỗi giây (như ESP32)")
    ap.add_argument("--noise", type=float, default=0.03, help="độ lệch chuẩn nhiễu đo, tính theo biên độ phòng trống")
    ap.add_argument("--max-depth", type=int, default=3, help="số lần phản xạ tối đa")
    ap.add_argument("--samples", type=int, default=100_000, help="số tia phóng mỗi khung")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--hinh", action="store_true", help="lưu ảnh 2D (quỹ đạo + CSI) và ảnh 3D có đường tia")
    ap.add_argument("--phat-lai", action="store_true", help="ghi file theo thời gian thực để xem trên dashboard")
    args = ap.parse_args()
    if not all(c.isalnum() and c.isascii() or c == "-" for c in args.tag):
        ap.error("--tag chỉ gồm chữ không dấu, số và '-'")

    plan = parse_plan(args.plan)
    rng = np.random.default_rng(args.seed)
    t_frames, frames, labels, segs, counts = build_frames(plan, args.rt_hz, rng, args.khach)
    duration = segs[-1][2]
    print(f"Kịch bản {duration:.0f} giây, {len(frames)} khung dò tia. Đang dựng cảnh Sionna RT (lần đầu mất ~10 s)...")
    scene, cfr = make_scene(args.max_depth, args.samples)
    H = ray_trace(frames, cfr)
    t, im, re, rssi, keep = to_samples(t_frames, H, args.rate, args.noise, rng, duration)
    d = write_session(args, plan, segs, t, im, re, rssi, keep, counts)
    if args.hinh:
        print("Đang vẽ ảnh 2D và render 3D...")
        save_figures(d, scene, cfr, t_frames, frames, labels, segs, H)
    print(f"Xong: {d}")
    print("Kiểm tra: python kiem_tra_buoi_thu.py " + str(d))


if __name__ == "__main__":
    main()
