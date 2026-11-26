#!/usr/bin/env python3
"""Mô phỏng 3D một buổi thu của nhánh người (đặc tả v0.3): 1 TX + 2 RX ở một góc phòng; người đi lại, ngồi xuống,
đứng dậy, nằm xuống, cúi nhặt, té ngã, thở; có thể có thêm 1–2 khách. Ghi ra data/raw/<buổi thu>/ đúng định dạng
v0.3 để viết trước phần xử lý (đặc trưng, đếm người, phát hiện ngã, nhịp thở) khi chưa có board.

Muốn xem hình động, chọn kịch bản bằng giao diện: python mo_phong_ui.py (mở trên trình duyệt).

Ví dụ:
    python mo_phong.py --tag sim1 --hinh                        # kịch bản 1 người (~7 phút), có ảnh
    python mo_phong.py --tag dong --kich-ban nhieu-nguoi --hinh # khách vào / ra
    python mo_phong.py --tag nga --plan "EMPTY:10,ACTIVE:20,FALL,DOWN:40@18~,STAND_UP,ACTIVE:10"
    python mo_phong.py --tag yen --kich-ban bat-dong            # ngồi / nằm yên 4 và 7 phút (cảnh báo bất động lâu)
    python mo_phong.py --tag kenh --nhieu "wifi@60:30,khac@200:3"   # ép thêm đợt nhiễu ("tat,..." = bỏ đợt ngẫu nhiên)
    python mo_phong.py --tag demo --phat-lai                    # ghi theo thời gian thực
    python mo_phong.py --tag ngaunhien --so-buoi 20             # 20 buổi kịch bản ngẫu nhiên (~5 phút mỗi buổi)
    python mo_phong.py --tag lau --so-buoi 20 --yen-lau 0.3     # 30 % số buổi có một đoạn yên 4–8 phút
    python mo_phong.py --tag x --nguoi-bam --hinh               # có người bấm phím ngồi trong phòng

Kịch bản (--plan), các mục cách nhau bằng dấu phẩy:
    TRẠNG_THÁI:giây[@nhịp]   EMPTY, NEIGHBOR, ACTIVE, STILL, DOWN, BREATH_ABN
                             @nhịp = nhịp thở/phút cho STILL, DOWN, BREATH_ABN (0 = nín thở)
    DOWN:giây[@nhịp]~        nằm sau ngã nhưng cử động tại chỗ: giãy tay chân, lăn / xoay, cố nhổm dậy rồi tụt lại,
                             không đứng lên được (nhãn vẫn STATE DOWN, thêm NOTE "DOWN cu-dong")
    ĐỘNG_TÁC[:giây]          FALL, SIT_DOWN, STAND_UP, LIE_DOWN, PICK_UP (bỏ trống = ngẫu nhiên trong khoảng ở ACTIONS)
    + hoặc -                 một khách vào / ra (tối đa 2 khách, tổng 3 người)
Nhãn STATE, ACTION, COUNT, RATE được ghi tự động vào labels.csv như người bấm phím: trễ 0–0,8 giây (trung bình 0,3)
so với lúc việc xảy ra thật. Thời điểm thật (giây tính từ đầu mô phỏng) ghi trong meta.json → simulator: truth (mọi
đoạn), down_cu_dong (các đoạn DOWN~), interference (các đợt nhiễu); t0_host = host_time của giây 0 để đổi sang host_time.
Để tránh "kết quả đẹp ảo": mỗi lần động tác có thời lượng, biên độ khác nhau; nhịp và độ sâu thở dao động nhẹ;
ngồi yên lâu thì thỉnh thoảng xê dịch vài cm; DOWN bất động, DOWN~ cử động từng đợt (~35 % lần ngã ở --so-buoi).
Đợt nhiễu chen ngang (interference_for): "wifi" – máy khác chiếm kênh CSI: STAT n_filtered 50–400 khung/giây (thường
0–5), mất 5–40 % gói, nhiễu CSI ×1,5, 1–3 % gói hỏng; "khac" – lò vi sóng…: noise_floor -95 → -85, nhiễu ×3, mất 30 %.

Mô hình kênh 3D (phương pháp ảnh trong phòng hộp chữ nhật):
- Phòng 4 × 3,5 × 2,8 m: tường, sàn bê tông, trần thạch cao (εr, σ theo ITU-R P.2040-2, Bảng 3). Góc (0, 0) là góc demo
  2,5 × 2,5 m. TX (0,2; 0,2), RX1 (2,6; 2,0), RX2 (2,0; 2,6), cao 0,75 m. Ghế / nệm (1,3; 1,3), cửa (3,6; 3,2),
  phòng bên sau tường x = 4.
- Đường truyền cố định: thẳng + phản xạ bậc 1 và 2 trên 6 mặt (40 đường mỗi RX), hệ số phản xạ Fresnel theo góc tới
  và vật liệu (ăng-ten phân cực đứng: tường → TE, sàn / trần → TM), 3 vật tĩnh tán xạ.
- Người: 9 điểm tán xạ theo chiều cao cơ thể (đầu, ngực, bụng, 2 đùi, 2 cẳng chân, 2 tay) ở tư thế đứng / ngồi / nằm,
  nội suy khi chuyển tư thế; chân và tay vung khi đi; ngực, bụng phồng 4–12 mm khi thở. Sóng dội từ người có cả đường
  dội thêm một mặt phòng trước / sau khi gặp người.
- Người che sóng: coi thân là tấm chắn đứng (rộng ~0,45 m, cao theo tư thế), tính nhiễu xạ Fresnel–Kirchhoff cho đường
  thẳng và phản xạ bậc 1 (đứng chắn giữa đường truyền ~9 dB; nằm dưới sàn gần như không chắn đường cao 0,75 m).
- ESP32: AGC tự bù ~90 % sự đổi công suất (trễ 0,1 s, bước 0,5 dB) + dao động ngẫu nhiên 5 % + trôi chậm; nhiễu 5 %;
  biên độ phòng trống ~15; 52 sóng mang con (len 104, thứ tự -26..-1, 1..26); pha mỗi gói lệch ngẫu nhiên; lượng tử
  int8; mất gói trên không (rx_seq nhảy) và mất dòng trên USB (seq nhảy); rx_seq 12 bit quay vòng.
- Tham số phần cứng và độ mạnh tán xạ đã hiệu chỉnh theo CSI thật của WiFall (doi_chieu_wifall.py).
Chưa có: phản xạ bậc ≥ 3; người che phản xạ bậc 2 và sóng dội từ người khác; chuyển động chi tiết của từng khớp
(DOWN~ chỉ dịch 6 điểm tay chân và độ cao thân). Hệ quả: giãy tay chân sát sàn chỉ hơi nổi trên nhiễu ESP32, rõ nhất là
lúc cố nhổm dậy.
Mô hình để thử luồng xử lý – không thay dữ liệu thật và không dùng để báo cáo độ chính xác.
"""
import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.signal import lfilter
from scipy.special import fresnel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from logger import FILES, SPEC_VERSION  # noqa: E402
from nhan import ACTIONS as ACTION_NAMES, STATES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# khoảng thời lượng (s); không ghi thời lượng trong kịch bản thì mỗi lần một giá trị ngẫu nhiên trong khoảng này
ACTIONS = {"FALL": (0.8, 1.6), "SIT_DOWN": (1.2, 2.4), "STAND_UP": (1.3, 2.6), "LIE_DOWN": (2.2, 4.0),
           "PICK_UP": (1.6, 3.0)}
assert set(ACTIONS) == set(ACTION_NAMES), "động tác trong mô phỏng phải khớp nhan.py"
BREATHING = ("STILL", "DOWN", "BREATH_ABN")
NHIEU = ("wifi", "khac")                  # loại đợt nhiễu chen ngang, xem interference_for

KICH_BAN = {
    "mot-nguoi": "EMPTY:20,ACTIVE:30,SIT_DOWN,STILL:40@14,STAND_UP,ACTIVE:15,PICK_UP,ACTIVE:15,LIE_DOWN,"
                 "STILL:40@16,STAND_UP,ACTIVE:15,FALL,DOWN:40@18,BREATH_ABN:30@35,STAND_UP,ACTIVE:15,SIT_DOWN,"
                 "BREATH_ABN:25@0,STAND_UP,ACTIVE:10,EMPTY:20",
    "nhieu-nguoi": "EMPTY:20,ACTIVE:20,+,ACTIVE:40,+,ACTIVE:40,SIT_DOWN,STILL:40,-,STILL:20,-,STILL:20,STAND_UP,"
                   "ACTIVE:15,EMPTY:20",
    "nga": "EMPTY:15,ACTIVE:20,FALL,DOWN:40,STAND_UP,ACTIVE:15,SIT_DOWN,STAND_UP,ACTIVE:10,LIE_DOWN,STILL:20,"
           "STAND_UP,ACTIVE:10,PICK_UP,ACTIVE:10,FALL,DOWN:30,STAND_UP,ACTIVE:10,EMPTY:15",
    "phong-ben": "EMPTY:30,NEIGHBOR:60,EMPTY:30",
    # cảnh báo bất động lâu (ngưỡng demo 5 phút): một lần nằm yên 4 phút (không được báo), một lần ngồi yên 7 phút
    "bat-dong": "EMPTY:15,ACTIVE:30,LIE_DOWN,STILL:240@12,STAND_UP,ACTIVE:30,SIT_DOWN,STILL:420@14,STAND_UP,ACTIVE:20,"
                "EMPTY:15",
}

# ---- hình học (m)
ROOM = (4.0, 3.5)
AREA = (0.0, 2.5, 0.0, 2.5)
NEIGHBOR_ROOM = (4.3, 6.0, 0.3, 3.2)
TX = np.array([0.2, 0.2])
RX = {"RX1": np.array([2.6, 2.0]), "RX2": np.array([2.0, 2.6])}
CHAIR = np.array([1.3, 1.3])
DOOR = np.array([3.6, 3.2])
OPERATOR = np.array([3.3, 2.4])         # người bấm phím ngồi cạnh laptop, ngoài khu demo (--nguoi-bam)
# vật tĩnh (tủ, kệ, bàn): (x, y, z), độ mạnh tán xạ
FURNITURE = [((3.6, 0.4, 0.9), 0.10), ((0.4, 3.1, 0.5), -0.08), ((3.3, 1.9, 0.4), 0.06)]
ROOM_H = 2.8                              # chiều cao trần
ANT_Z = 0.75                              # TX, RX đặt trên kệ / ghế cao ~0,75 m
# ---- sóng
SUB = np.r_[-26:0, 1:27]
FREQS = 2.437e9 + SUB * 312.5e3           # kênh 6
K = 2j * np.pi * FREQS / 3e8
LAM = 3e8 / 2.437e9
# vật liệu (εr, σ S/m) theo ITU-R P.2040-2 (09/2021), Bảng 3: εr = a·f^b, σ = c·f^d, f tính bằng GHz
CONCRETE = (5.24, 0.0462 * 2.437 ** 0.7822)              # bê tông: a 5,24, b 0, c 0,0462, d 0,7822 (1–100 GHz)
PLASTERBOARD = (2.73, 0.0085 * 2.437 ** 0.9395)          # thạch cao: a 2,73, b 0, c 0,0085, d 0,9395 (1–100 GHz)
# 6 mặt phòng: (trục, toạ độ, vật liệu); trục 0/1 = tường, 2 = sàn / trần
PLANES = [(0, 0.0, CONCRETE), (0, ROOM[0], CONCRETE), (1, 0.0, CONCRETE), (1, ROOM[1], CONCRETE),
          (2, 0.0, CONCRETE), (2, ROOM_H, PLASTERBOARD)]
SIGMA = 0.16                              # tổng độ mạnh tán xạ của một người (chỉnh theo WiFall, doi_chieu_wifall.py)
WALL_LOSS = 0.3                           # suy hao khi người ở phòng bên (xuyên tường)
BODY_W = 0.45                             # bề rộng thân người khi coi là tấm chắn (vai)
LEVEL = 15.0                              # biên độ int8 lúc phòng trống – như ESP32-S3 trong WiFall (13–15)
AGC_STD = 0.05                            # dao động khuếch đại ngẫu nhiên mỗi gói (chung mọi sóng mang con)
AGC_ALPHA = 0.9                           # AGC bù bao nhiêu phần sự đổi công suất (0 = không, 1 = hết); khớp WiFall nhất ở 0,85–1
AGC_TAU = 0.1                             # hằng số thời gian AGC (s); bước khuếch đại 0,5 dB
STAND, SIT = 1.0, 0.6                     # "độ cao" tư thế: 1 đứng, 0,6 ngồi, 0 nằm
MAC = {"TX": "1a:00:00:00:00:00", "RX1": "64:e8:33:01:02:03", "RX2": "64:e8:33:01:02:04"}
CHANNEL = 6
N_PERSON = 4                              # 0 = người được giám sát, 1–2 = khách, 3 = người bấm phím


# --------------------------------------------------------------------------- kịch bản
def parse_plan(text):
    items = []
    for part in (p.strip() for p in text.split(",")):
        if part in ("+", "-"):
            items.append((part, 0.0, None))
            continue
        moving = part.endswith("~")                                            # DOWN~: nằm sau ngã có cử động
        name, _, rest = part.rstrip("~").partition(":")
        name = name.upper()
        dur, _, bpm = rest.partition("@")
        try:
            dur = float(dur) if dur else None                                  # động tác: None = ngẫu nhiên
            bpm = float(bpm) if bpm else None
        except ValueError:
            dur = None
        bad_bpm = bpm is not None and (name not in BREATHING or not 0 <= bpm <= 60)
        bad_dur = dur is None and name not in ACTIONS or dur is not None and not 0 < dur <= 3600
        if name not in STATES and name not in ACTIONS or bad_dur or bad_bpm or moving and name != "DOWN":
            sys.exit(f"--plan sai ở '{part}'. Dạng: TRẠNG_THÁI:giây[@nhịp][~], ĐỘNG_TÁC[:giây], + hoặc -.\n"
                     f"Trạng thái: {', '.join(STATES)}. Động tác: {', '.join(ACTIONS)}. "
                     f"@nhịp (0–60) chỉ dùng cho {', '.join(BREATHING)}; ~ (cử động tại chỗ) chỉ dùng cho DOWN.")
        items.append((name + "~" * moving, dur, bpm))                          # giữ "DOWN~" để timeline biết
    return items


def random_plan(rng, minutes=5.0, guests=False, long_still=False):
    """Kịch bản ngẫu nhiên hợp lệ: đi lại, ngồi, cúi, nằm, ngã (khá thường xuyên; ~35 % lần ngã người còn cử động tại
    chỗ – DOWN~), thở thường / bất thường; guests=True: có 1–2 khách vào ra giữa chừng; long_still=True: lần ngồi / nằm
    đầu tiên yên liền 4–8 phút (thử cảnh báo bất động lâu)."""
    out = [f"EMPTY:{rng.integers(10, 31)}", f"ACTIVE:{rng.integers(10, 31)}"]
    posture, n_guest = "stand", 0
    length = lambda: sum(float(x.split(":")[1].split("@")[0]) for x in out if ":" in x)
    pick = lambda opts: opts[0][rng.choice(len(opts[0]), p=opts[1])]
    down = lambda: f"DOWN:{rng.integers(20, 61)}@{rng.integers(10, 23)}" + "~" * (rng.random() < 0.35)

    def rest(still=True):
        nonlocal long_still
        if still and long_still:
            long_still = False
            return f"STILL:{rng.integers(240, 481)}@{rng.integers(10, 23)}"
        if still and rng.random() < 0.8:
            return f"STILL:{rng.integers(15, 61)}@{rng.integers(10, 23)}"
        return f"BREATH_ABN:{rng.integers(15, 41)}@{rng.choice([0, 6, 32, 38])}"
    while length() < minutes * 60:
        if guests and posture != "absent":
            if n_guest < 2 and rng.random() < 0.15:
                out.append("+")
                n_guest += 1
            elif n_guest > 0 and rng.random() < 0.1:
                out.append("-")
                n_guest -= 1
        if posture == "stand":
            c = pick((["ACTIVE", "PICK_UP", "SIT_DOWN", "LIE_DOWN", "FALL", "STILL"],
                      [0.25, 0.12, 0.2, 0.1, 0.23, 0.1]))
            if c == "ACTIVE":
                out.append(f"ACTIVE:{rng.integers(8, 26)}")
            elif c == "STILL":
                out.append(f"STILL:{rng.integers(5, 16)}")
            elif c == "PICK_UP":
                out += ["PICK_UP", f"ACTIVE:{rng.integers(5, 15)}"]
            elif c == "FALL":
                out += ["FALL", down()]
                if rng.random() < 0.3:
                    out.append(rest(still=False))
                posture = "lie"
            else:
                out += [c, rest()]
                posture = "sit" if c == "SIT_DOWN" else "lie"
        elif posture == "sit":
            c = pick((["STAND_UP", "LIE_DOWN", "FALL"], [0.6, 0.25, 0.15]))
            if c == "FALL":
                out += ["FALL", down()]
                posture = "lie"
            elif c == "LIE_DOWN":
                out += ["LIE_DOWN", rest()]
                posture = "lie"
            else:
                out += ["STAND_UP", f"ACTIVE:{rng.integers(5, 16)}"]
                posture = "stand"
        else:
            out += ["STAND_UP", f"ACTIVE:{rng.integers(5, 16)}"]
            posture = "stand"
    if posture != "stand":
        out += ["STAND_UP", f"ACTIVE:{rng.integers(5, 16)}"]
    if long_still:                                            # cả buổi chưa ngồi / nằm lần nào: thêm ở cuối
        out += ["SIT_DOWN", rest(), "STAND_UP", f"ACTIVE:{rng.integers(5, 16)}"]
    out.append(f"EMPTY:{rng.integers(10, 21)}")
    return ",".join(out)


def down_cu_dong(plan, spans):
    """[[giây đầu, giây cuối]] các đoạn DOWN~ (cùng mốc với spans / simulator.truth). Mỗi mục kịch bản trừ +/- sinh
    đúng một đoạn trong spans, theo thứ tự."""
    names = [n for n, _, _ in parse_plan(plan) if n not in ("+", "-")]
    return [[round(a, 3), round(b, 3)] for n, (_, a, b) in zip(names, spans) if n == "DOWN~"]


def walk(rng, area, n, dt, start, end=None, pause=(0.4, 2.0)):
    """Đi theo điểm đích ngẫu nhiên trong `area`, có lúc dừng; `end`: đoạn cuối đi thẳng tới điểm này."""
    x0, x1, y0, y1 = area[0] + 0.3, area[1] - 0.3, area[2] + 0.3, area[3] - 0.3
    pick = lambda: np.array([rng.uniform(x0, x1), rng.uniform(y0, y1)])
    p, goal, v, wait = np.array(start, dtype=float), pick(), rng.uniform(0.5, 1.0), 0.0
    out = np.empty((n, 2))
    for k in range(n):
        if wait > 0:
            wait -= dt
        else:
            d = goal - p
            dist = np.linalg.norm(d)
            if dist < v * dt:
                p, goal, v = goal, pick(), rng.uniform(0.5, 1.0)
                wait = rng.uniform(0.5, pause[1]) if rng.random() < pause[0] else 0.0
            else:
                p = p + d / dist * v * dt
        out[k] = p
    if end is not None:                                          # rẽ về đích sao cho đi ~0,7 m/s (không nhanh hơn)
        left = np.linalg.norm(end - out, axis=1) - (n - 1 - np.arange(n)) * dt * 0.7
        ok = np.flatnonzero(left <= 0)
        j = ok[0] if len(ok) else 0
        out[j:] = np.linspace(out[j], end, n - j)
    raw = away_from_devices(out)
    k = max(1, int(0.8 / dt))                                    # người thật tăng / giảm tốc, rẽ vòng: làm mượt 0,8 s
    out = np.stack([np.convolve(np.pad(c, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, "valid")
                    for c in raw.T], axis=1)
    fade = np.clip(1 - np.arange(n) / k, 0, 1)[:, None]          # giữ đúng điểm đầu / cuối để nối liền đoạn trước, sau
    out += fade * (raw[0] - out[0]) + fade[::-1] * (raw[-1] - out[-1])
    return out


def away_from_devices(xy, r=0.3):
    """Không ai đứng đè lên board: đẩy ra ngoài vòng bán kính r quanh TX, RX."""
    for dev in (TX, *RX.values()):
        v = xy - dev
        dist = np.linalg.norm(v, axis=-1, keepdims=True)
        xy = np.where(dist < r, dev + v / np.maximum(dist, 1e-6) * r, xy)
    return xy


def slow_noise(rng, n, dt, sd, every=10.0):
    """Dao động ngẫu nhiên chậm (đổi hướng mỗi ~`every` giây), độ lệch chuẩn sd."""
    m = int(n * dt / every) + 2
    return np.interp(np.arange(n), np.linspace(0, n - 1, m), rng.normal(0, sd, m))


def breath_wave(rng, n, dt, bpm):
    """Độ dịch của ngực (m). bpm = 0: nín thở. Như người thật: nhịp dao động ±8 %, độ sâu ±25 % quanh mức trung bình."""
    if bpm == 0:
        return np.zeros(n)
    amp = 0.003 if bpm > 25 else 0.008 if bpm < 8 else 0.006       # ngực dịch 4–12 mm theo tài liệu; thở nhanh thì nông
    phase = 2 * np.pi * np.cumsum(bpm / 60 * (1 + slow_noise(rng, n, dt, 0.08))) * dt + rng.uniform(0, 2 * np.pi)
    return amp * np.clip(1 + slow_noise(rng, n, dt, 0.25), 0.3, None) * np.sin(phase)


def adjust(rng, n, dt):
    """Ngồi / nằm yên lâu thì thỉnh thoảng (20–40 giây một lần) xê dịch 3–8 cm trong ~1 giây rồi yên ở chỗ mới."""
    out, k, m = np.zeros((n, 2)), int(rng.uniform(20, 40) / dt), int(1 / dt)
    while k < n:
        ang = rng.uniform(0, 2 * np.pi)
        ramp = (1 - np.cos(np.pi * np.minimum(np.arange(n - k) / m, 1))) / 2
        out[k:] += np.outer(ramp, rng.uniform(0.03, 0.08) * np.array([np.cos(ang), np.sin(ang)]))
        k += int(rng.uniform(20, 40) / dt)
    return out


def fidget(rng, n):
    """Lắc lư rất nhỏ khi ngồi / nằm yên: ~1 mm, đổi trong vài giây (chậm hơn nhịp thở; xê dịch lớn nằm ở adjust)."""
    return np.convolve(rng.normal(0, 0.0173, n + 299), np.ones(300) / 300, "valid")


def struggle(rng, n, dt, yaw0):
    """DOWN~ – ngã rồi không tự dậy được nhưng còn cử động: từng đợt 1–5 s, nghỉ 2–12 s. Mỗi đợt tay chân giãy 3–20 cm
    (0,5–2 lần/giây); ~25 % đợt kèm lăn / xoay người (chỗ nằm dịch ngang tối đa 30 cm, hướng thân đổi tới ±45°); ~25 % đợt
    kèm cố nhổm dậy (h lên 0,2–0,35 rồi tụt về 0). Không bao giờ đứng lên. Số liệu là giá trị khởi đầu ước lượng theo
    mô tả người ngã không tự dậy được (chưa có số đo); có buổi thu thật thì chỉnh lại.
    Trả về độ dịch tay chân (n, 6: đùi, cẳng chân, tay), độ nhổm h (n,), độ xoay thân (n,), độ dịch chỗ nằm (n, 2)."""
    limb, rise, turn, shift = np.zeros((n, 6)), np.zeros(n), np.zeros(n), np.zeros((n, 2))
    k = int(rng.uniform(0.5, 3) / dt)
    while k < n:
        T = rng.uniform(1, 5)
        m = min(int(T / dt), n - k)
        env = np.sin(np.pi * np.arange(m) * dt / T)
        tt = np.arange(m)[:, None] * dt
        limb[k:k + m] = env[:, None] * rng.uniform(0.03, 0.2, 6) * np.sin(
            2 * np.pi * rng.uniform(0.5, 2, 6) * tt + rng.uniform(0, 2 * np.pi, 6))
        c = rng.random()
        if c < 0.25:                                                  # lăn / xoay người, nằm luôn ở chỗ mới
            ramp = (1 - np.cos(np.pi * np.minimum(np.arange(n - k) * dt / T, 1))) / 2
            side = rng.choice([-1, 1]) * np.array([-np.sin(yaw0 + turn[k]), np.cos(yaw0 + turn[k])])
            # chậm hơn 0,1 m/s: body_points vẫn lấy hướng thân theo yaw (nhanh hơn thì coi là đang đi)
            shift[k:] += np.outer(ramp, side * min(rng.uniform(0.1, 0.3), 0.06 * T))
            turn[k:] += ramp * rng.uniform(-0.8, 0.8)
        elif c < 0.5:                                                 # cố nhổm dậy rồi tụt lại
            rise[k:k + m] = rng.uniform(0.2, 0.35) * env
        k += m + int(rng.uniform(2, 12) / dt)
    return limb, rise, turn, shift


def timeline(items, rate, rng, operator=False):
    """Dựng chuyển động của mọi người theo kịch bản, mỗi mẫu CSI một điểm.

    Trả về t, dict mảng (N × người): x, y, h (độ cao tư thế), yaw (hướng thân khi nằm), breath, present, behind;
    danh sách nhãn (giây, event, value); các đoạn để vẽ (tên, giây đầu, giây cuối)."""
    dt = 1.0 / rate
    items = [(n, rng.uniform(*ACTIONS[n]) if d is None else d, b) for n, d, b in items]
    lens = [int(round(d * rate)) for _, d, _ in items]
    N = sum(lens)
    S = {k: np.zeros((N, N_PERSON)) for k in ("x", "y", "yaw", "breath")}
    S["h"] = np.ones((N, N_PERSON))
    S["limb"] = np.zeros((N, N_PERSON, 6))                                       # tay chân giãy (DOWN~)
    S["present"] = np.zeros((N, N_PERSON), bool)
    S["behind"] = np.zeros((N, N_PERSON), bool)
    labels, spans = [], []
    posture, pos, lie_yaw = "absent", DOOR.copy(), 0.0
    guests, open_guest, i = [], [], 0          # khách: [slot, mẫu vào, mẫu ra]
    fail = lambda k, msg: sys.exit(f"--plan mục {k + 1} ('{items[k][0]}'): {msg}")
    for k, ((name, _, bpm), n) in enumerate(zip(items, lens)):
        moving, name = name == "DOWN~", name.rstrip("~")                         # nhãn, đoạn đáp án vẫn là DOWN
        a, sl = i * dt, slice(i, i + n)
        if name == "+":
            free = [g for g in (1, 2) if g not in [x[0] for x in open_guest]]
            if not free:
                fail(k, "tối đa 2 khách")
            open_guest.append([free[0], i, N])
            labels.append((a, "COUNT", "+1"))
            continue
        if name == "-":
            if not open_guest:
                fail(k, "không còn khách nào để ra")
            g = open_guest.pop(0)
            g[2] = i
            guests.append(g)
            labels.append((a, "COUNT", "-1"))
            continue
        p = {key: S[key][sl, 0] for key in S}
        s = (np.arange(n) + 1) / n
        smooth = (1 - np.cos(np.pi * s)) / 2
        if name in ("EMPTY", "NEIGHBOR"):
            if posture != "absent":
                labels.append((a, "COUNT", "-1"))
            posture, pos = "absent", DOOR.copy()
            if name == "NEIGHBOR":
                xy = walk(rng, NEIGHBOR_ROOM, n, dt, [NEIGHBOR_ROOM[0] + 0.5, 1.5])
                p["x"][:], p["y"][:], p["present"][:], p["behind"][:] = xy[:, 0], xy[:, 1], True, True
        elif name == "ACTIVE":
            if posture == "absent":
                labels.append((a, "COUNT", "+1"))
            elif posture != "stand":
                fail(k, f"đang {posture}, cần STAND_UP trước khi đi lại")
            nxt = next((it[0] for it in items[k + 1:] if it[0] not in ("+", "-")), None)
            goal = CHAIR if nxt in ("SIT_DOWN", "LIE_DOWN") else DOOR if nxt in ("EMPTY", "NEIGHBOR") else None
            xy = walk(rng, AREA, n, dt, pos, end=goal)                       # rời phòng: đi ra cửa
            p["x"][:], p["y"][:], p["present"][:] = xy[:, 0], xy[:, 1], True
            posture, pos = "stand", xy[-1].copy()
        elif name in BREATHING:
            if posture == "absent":
                fail(k, "chưa có người trong phòng, cần ACTIVE trước")
            if name == "DOWN" and posture != "lie":
                fail(k, "DOWN là nằm sau ngã, cần FALL (hoặc LIE_DOWN) trước")
            if bpm is None:
                bpm = 35.0 if name == "BREATH_ABN" else float(rng.integers(12, 21))
            shift, rise, turn = np.zeros((n, 2)), np.zeros(n), np.zeros(n)  # DOWN: bất động thật sự
            if name == "STILL":
                shift = adjust(rng, n, dt)
            elif moving:
                p["limb"][:], rise, turn, shift = struggle(rng, n, dt, lie_yaw)
                shift = away_from_devices(np.clip(pos + shift, 0.2, [ROOM[0] - 0.2, ROOM[1] - 0.2])) - pos
                labels.append((a, "NOTE", "DOWN cu-dong"))
            p["x"][:], p["y"][:] = pos[0] + shift[:, 0] + fidget(rng, n), pos[1] + shift[:, 1] + fidget(rng, n)
            pos = pos + shift[-1]
            p["h"][:] = {"stand": STAND, "sit": SIT, "lie": 0.0}[posture] + rise
            p["yaw"][:], p["breath"][:], p["present"][:] = lie_yaw + turn, breath_wave(rng, n, dt, bpm), True
            lie_yaw += turn[-1]
            labels.append((a, "RATE", f"{bpm:g}"))
        else:                                                                   # động tác
            need = {"FALL": ("stand", "sit"), "SIT_DOWN": ("stand",), "PICK_UP": ("stand",),
                    "STAND_UP": ("sit", "lie"), "LIE_DOWN": ("stand", "sit")}[name]
            if posture not in need:
                fail(k, f"cần tư thế {' hoặc '.join(need)}, đang {posture}")
            ang = rng.uniform(0, 2 * np.pi)
            d = np.array([np.cos(ang), np.sin(ang)])
            h0 = {"stand": STAND, "sit": SIT, "lie": 0.0}[posture]
            if name == "FALL":                                                  # nhanh dần, va chạm ở cuối
                kind = "tu-ghe" if posture == "sit" else str(rng.choice(["thang", "khuyu"]))
                if kind == "khuyu":                                             # khuỵu gối xuống rồi đổ nghiêng
                    u = np.where(s < 0.5, (s / 0.5) ** 2 * 0.6, 0.6 + 0.4 * ((s - 0.5) / 0.5) ** 2)
                    xy = pos + np.outer(np.clip((s - 0.5) / 0.5, 0, 1), d * rng.uniform(0.25, 0.5))
                else:                                                           # đổ thẳng một hướng / ngã khỏi ghế
                    u = s ** 2
                    xy = pos + np.outer(u, d * rng.uniform(0.4, 0.8) * (1 if kind == "thang" else 0.8))
                xy[-15:] += rng.normal(0, 0.02, (min(15, n), 2))
                p["h"][:], lie_yaw, posture = h0 * (1 - u), ang, "lie"
                labels.append((a, "NOTE", f"FALL {kind}"))
            elif name == "SIT_DOWN":
                xy, p["h"][:], posture = pos + np.outer(smooth, d * rng.uniform(0.05, 0.15)), STAND - (STAND - SIT) * smooth, "sit"
            elif name == "STAND_UP":
                xy, p["h"][:], posture = pos + np.outer(smooth, d * 0.1), h0 + (STAND - h0) * smooth, "stand"
            elif name == "LIE_DOWN":
                lie_yaw = ang
                xy, p["h"][:], posture = pos + np.outer(smooth, d * 0.3), h0 * (1 - smooth), "lie"
            else:                                                               # PICK_UP: cúi xuống rồi đứng lên
                bend = np.sin(np.pi * s)
                xy, p["h"][:] = pos + np.outer(bend, d * 0.1), STAND - rng.uniform(0.5, 0.8) * bend
            xy = away_from_devices(np.clip(xy, 0.2, [ROOM[0] - 0.2, ROOM[1] - 0.2]))
            p["x"][:], p["y"][:], p["yaw"][:], p["present"][:] = xy[:, 0], xy[:, 1], lie_yaw, True
            pos = xy[-1].copy()
        labels.append((a, "ACTION" if name in ACTIONS else "STATE", name))
        spans.append((name, a, a + n * dt))
        i += n
    guests += open_guest
    for g, a0, b0 in guests:                                                    # khách đi lại, hay dừng lâu
        if b0 <= a0:
            continue
        m = b0 - a0
        xy = walk(rng, (0.0, ROOM[0], 0.0, ROOM[1]), m, dt, DOOR, end=DOOR if b0 < N else None, pause=(0.5, 12.0))
        S["x"][a0:b0, g], S["y"][a0:b0, g], S["present"][a0:b0, g] = xy[:, 0], xy[:, 1], True
        S["h"][a0:b0, g] = sit_when_paused(xy, dt)
        S["breath"][a0:b0, g] = breath_wave(rng, m, dt, float(rng.integers(12, 21)))
    if operator:                                                                # ngồi yên cả buổi, không tính vào COUNT
        S["x"][:, 3], S["y"][:, 3] = OPERATOR[0] + fidget(rng, N), OPERATOR[1] + fidget(rng, N)
        S["h"][:, 3], S["present"][:, 3] = SIT, True
        S["breath"][:, 3] = breath_wave(rng, N, dt, 14.0)
    # người bấm phím trễ 0–0,8 s (trung bình 0,3 s) so với lúc việc xảy ra thật; thời điểm thật nằm trong `spans`
    lag = np.clip(rng.normal(0.3, 0.15, len(labels)), 0, 0.8)
    labels = [(min(a + d, N * dt - dt), ev, val) for (a, ev, val), d in zip(labels, lag)]
    return np.arange(N) * dt, S, sorted(labels, key=lambda e: e[0]), spans


def sit_when_paused(xy, dt, min_s=4.0, ramp=1.2):
    """Khách dừng lâu (≥ min_s giây) thì ngồi xuống, sắp đi tiếp thì đứng lên."""
    still = np.r_[True, np.linalg.norm(np.diff(xy, axis=0), axis=1) < 1e-4]
    edges = np.flatnonzero(np.diff(np.r_[0, still.astype(int), 0]))
    h, r = np.ones(len(xy)), int(ramp / dt)
    for a, b in zip(edges[::2], edges[1::2]):
        if (b - a) * dt >= min_s:
            up = (1 - np.cos(np.pi * np.linspace(0, 1, r))) / 2
            seg = np.full(b - a, SIT)
            seg[:r], seg[-r:] = STAND - (STAND - SIT) * up, SIT + (STAND - SIT) * up
            h[a:b] = seg
    return h


# --------------------------------------------------------------------------- kênh truyền
def sum_paths(amp, L):
    """Σ_p amp·exp(-K·L) trên 52 sóng mang con, amp và L dạng (..., số đường). Tần số cách đều 312,5 kHz nên nhân
    dồn từng bước thay vì tính 52 lần exp cho mỗi đường; dải -26..26 có sóng mang con 0, bỏ đi ở cuối."""
    cur = amp * np.exp(-2j * np.pi * FREQS[0] / 3e8 * L)
    step = np.exp(-2j * np.pi * 312.5e3 / 3e8 * L)
    out = np.empty(L.shape[:-1] + (53,), dtype=complex)
    for k in range(53):
        out[..., k] = cur.sum(axis=-1)
        cur *= step
    return np.delete(out, 26, axis=-1)


def at(xy, z=ANT_Z):
    """Điểm 3D từ toạ độ sàn + độ cao."""
    return np.array([xy[0], xy[1], z], dtype=float)


def gamma(cos_t, mat, axis):
    """Hệ số phản xạ Fresnel của mặt phẳng vật liệu `mat` với góc tới có cos = cos_t. Ăng-ten phân cực đứng:
    trên tường (mặt đứng) điện trường song song mặt → TE; trên sàn / trần nằm trong mặt phẳng tới → TM."""
    er, sig = mat
    ec = er - 1j * sig / (2 * np.pi * 2.437e9 * 8.854e-12)
    root = np.sqrt(ec - (1 - cos_t ** 2))
    if axis < 2:
        return (cos_t - root) / (cos_t + root)
    return (ec * cos_t - root) / (ec * cos_t + root)


def mirror(q, plane):
    ax, c, _ = PLANES[plane]
    q = np.array(q, dtype=float)
    q[..., ax] = 2 * c - q[..., ax]
    return q


def image_paths(src, dst, order=2):
    """Đường phản xạ trên 6 mặt phòng tới bậc `order` (phương pháp ảnh; trong phòng hộp mọi ảnh đều hợp lệ).
    Trả về [(hệ số phức, độ dài, các điểm gãy, dãy mặt)]."""
    seqs = [(i,) for i in range(6)]
    if order >= 2:
        seqs += [(i, j) for i in range(6) for j in range(6) if i != j]
    out = []
    for seq in seqs:
        imgs = [np.array(src, dtype=float)]
        for i in seq:
            imgs.append(mirror(imgs[-1], i))
        D = dst - imgs[-1]
        L = np.linalg.norm(D)
        g = np.prod([gamma(abs(D[PLANES[i][0]]) / L, PLANES[i][2], PLANES[i][0]) for i in seq])
        hits, target = [], np.array(dst, dtype=float)
        for k in reversed(range(len(seq))):                      # đi ngược từ đích để tìm điểm chạm từng mặt
            ax, c, _ = PLANES[seq[k]]
            img = imgs[k + 1]
            target = img + (c - img[ax]) / (target[ax] - img[ax]) * (target - img)
            hits.insert(0, target)
        out.append((g, L, [np.array(src, dtype=float)] + hits + [np.array(dst, dtype=float)], seq))
    return out


def objects_for(seed):
    """Vật tĩnh của một buổi thu: đồ đạc cố định xê dịch ±0,2 m + 3–6 vật lặt vặt (ghế, túi, chai…) đặt ngẫu nhiên.
    Mỗi buổi một khác như ngoài đời – lý do mô hình train buổi này hay sai buổi khác. Cùng seed → cùng phòng."""
    r = np.random.default_rng(seed + 12345)                     # dòng ngẫu nhiên riêng: không đổi phần còn lại
    out = []
    for (x, y, z), st in FURNITURE:
        out.append(((float(np.clip(x + r.uniform(-.2, .2), .1, ROOM[0] - .1)),
                     float(np.clip(y + r.uniform(-.2, .2), .1, ROOM[1] - .1)), z), st))
    for _ in range(int(r.integers(3, 7))):
        while True:
            q = np.array([r.uniform(.2, ROOM[0] - .2), r.uniform(.2, ROOM[1] - .2)])
            if min(np.linalg.norm(q - d) for d in (TX, *RX.values())) > 0.5:
                break
        out.append(((float(q[0]), float(q[1]), float(r.uniform(.1, 1.2))), float(r.choice([-1, 1]) * r.uniform(.02, .08))))
    return out


def parse_nhieu(text):
    """--nhieu "wifi@60:30,khac@200:3" → (có đợt ngẫu nhiên không, [(loại, giây đầu, giây cuối)]); mục "tat" = bỏ
    các đợt ngẫu nhiên."""
    rand, out = True, []
    for part in filter(None, (p.strip() for p in (text or "").split(","))):
        if part == "tat":
            rand = False
            continue
        kind, _, rest = part.partition("@")
        a, _, d = rest.partition(":")
        try:
            a, d = float(a), float(d)
        except ValueError:
            a = d = -1.0
        if kind not in NHIEU or not (0 <= a <= 86400 and 0 < d <= 3600):
            sys.exit(f"--nhieu sai ở '{part}'. Dạng: loại@giây_bắt_đầu:thời_lượng, cách nhau bằng dấu phẩy "
                     f"(loại: {', '.join(NHIEU)}); thêm 'tat' để bỏ các đợt ngẫu nhiên.")
        out.append((kind, a, a + d))
    return rand, out


def interference_for(seed, n, rate, nhieu=None):
    """Các đợt nhiễu chen ngang của buổi thu [(loại, giây đầu, giây cuối)]: ngẫu nhiên theo seed + các đợt ép bằng nhieu.
    - "wifi": thiết bị Wi-Fi khác chiếm kênh CSI (tải dữ liệu…). Đợt ngắn như bản trước (1 đợt / 2 phút, 1–4 s) và đợt
      dài 10–60 s, trung bình 1 đợt / 5 phút.
    - "khac": nhiễu không phải Wi-Fi (lò vi sóng…): RX không giải mã được khung nào nên không đếm được.
    Đợt ngắn 70 % là Wi-Fi vì trong nhà Wi-Fi khác cùng kênh gặp thường hơn lò vi sóng (giá trị khởi đầu, chưa đo)."""
    r = np.random.default_rng(seed + 54321)                     # dòng ngẫu nhiên riêng: không đổi phần còn lại
    rand, out = parse_nhieu(nhieu)
    dur = n / rate
    if rand:
        for _ in range(r.poisson(dur / 120)):
            a = r.uniform(0, dur)
            out.append(("wifi" if r.random() < 0.7 else "khac", a, a + r.uniform(1, 4)))
        for _ in range(r.poisson(dur / 300)):
            a = r.uniform(0, dur)
            out.append(("wifi", a, a + r.uniform(10, 60)))
    return sorted(((k, round(a, 2), round(min(b, dur), 2)) for k, a, b in out if a < dur), key=lambda e: e[1])


def burst_mask(t, bursts, kinds=NHIEU):
    """Mặt nạ (N,) các mẫu nằm trong đợt nhiễu thuộc `kinds`."""
    m = np.zeros(len(t), dtype=bool)
    for k, a, b in bursts:
        if k in kinds:
            m |= (t >= a) & (t < b)
    return m


def static_paths(rx, objects=FURNITURE):
    """Các đường không phụ thuộc người tới RX (toạ độ sàn): thẳng, phản xạ bậc 1–2 trên tường, sàn, trần, vật tĩnh.
    Trả về [(biên độ phức, độ dài, các điểm gãy 3D, dãy mặt)]; dãy mặt () = đường thẳng, None = vật tĩnh."""
    tx, r3 = at(TX), at(rx)
    d0 = np.linalg.norm(r3 - tx)
    paths = [(1 / d0, d0, [tx, r3], ())]
    paths += [(g / L, L, pts, seq) for g, L, pts, seq in image_paths(tx, r3)]
    for xyz, s in objects:
        q = np.array(xyz, dtype=float)
        d1, d2 = np.linalg.norm(q - tx), np.linalg.norm(r3 - q)
        paths.append((s / (d1 * d2), d1 + d2, [tx, q, r3], None))
    return paths


def slit(v1, v2):
    """Trường (chuẩn hoá) đi qua khe từ v1 tới v2 theo tham số Fresnel – tích phân Fresnel C, S."""
    S1, C1 = fresnel(v1)
    S2, C2 = fresnel(v2)
    return (1 + 1j) / 2 * ((C2 - C1) - 1j * (S2 - S1))


def screen_factor(A, B, scr):
    """Hệ số phức của đoạn A→B khi có người (coi là tấm chắn đứng rộng w, cao từ z0 tới z1) chắn ngang: nhiễu xạ
    Fresnel–Kirchhoff, theo Babinet = 1 − trường qua khe cùng cỡ (cùng cơ sở với mô hình chắn người của 3GPP).
    scr: (..., 6) = x, y, w, z0, z1, có hiệu lực."""
    AB = B - A
    Lxy2 = AB[0] ** 2 + AB[1] ** 2
    if Lxy2 < 1e-6:                                             # đoạn gần như thẳng đứng
        return np.ones(scr.shape[:-1], dtype=complex)
    bx, by, w, z0, z1, ok = (scr[..., i] for i in range(6))
    u = ((bx - A[0]) * AB[0] + (by - A[1]) * AB[1]) / Lxy2
    inside = (u > 0.02) & (u < 0.98) & (ok > 0)
    u = np.clip(u, 0.02, 0.98)
    L = np.linalg.norm(AB)
    d1, d2 = u * L, (1 - u) * L
    k = np.sqrt(2 * (d1 + d2) / (LAM * d1 * d2))
    e = ((bx - A[0]) * AB[1] - (by - A[1]) * AB[0]) / np.sqrt(Lxy2)  # lệch ngang có dấu của thân so với tia
    zs = A[2] + u * AB[2]
    f = 1 - slit((e - w / 2) * k, (e + w / 2) * k) * slit((z0 - zs) * k, (z1 - zs) * k)
    return np.where(inside, f, 1)


# điểm tán xạ trên cơ thể (tiến, ngang, cao, độ mạnh) ở 3 tư thế; tư thế giữa chừng nội suy theo h.
# Thứ tự: đầu, ngực, bụng, đùi T/P, cẳng chân T/P, tay T/P. Độ mạnh cộng lại = 1 (nhân với SIGMA).
POSE = {
    "stand": [(0, 0, 1.6, .10), (.05, 0, 1.3, .25), (.05, 0, 1.0, .20), (0, .1, .7, .09), (0, -.1, .7, .09),
              (0, .1, .35, .06), (0, -.1, .35, .06), (0, .22, 1.0, .075), (0, -.22, 1.0, .075)],
    "sit": [(-.05, 0, 1.2, 0), (0, 0, .95, 0), (0, 0, .7, 0), (.25, .1, .5, 0), (.25, -.1, .5, 0),
            (.45, .1, .25, 0), (.45, -.1, .25, 0), (.05, .22, .75, 0), (.05, -.22, .75, 0)],
    "lie": [(.8, 0, .15, 0), (.45, 0, .18, 0), (.1, 0, .15, 0), (-.3, .1, .12, 0), (-.3, -.1, .12, 0),
            (-.65, .1, .1, 0), (-.65, -.1, .1, 0), (.4, .25, .12, 0), (.4, -.25, .12, 0)],
}
POSE = {k: np.array(v, dtype=float) for k, v in POSE.items()}


def body_points(t, S, dt):
    """Điểm tán xạ 3D của mọi người + tấm chắn tương ứng.
    Trả về vị trí (N, P, 3), độ mạnh (N, P), tấm chắn (N, số người, 6)."""
    x, y, h, yaw = S["x"], S["y"], S["h"], S["yaw"]
    v = np.stack([np.gradient(x, dt, axis=0), np.gradient(y, dt, axis=0)], -1)
    spd = np.linalg.norm(v, axis=-1)
    head = np.where(spd > 0.1, np.arctan2(v[..., 1], v[..., 0]), yaw)        # đi: hướng đi; đứng yên / nằm: yaw
    a = np.clip((h - SIT) / (STAND - SIT), 0, 1)[..., None, None]
    b = np.clip(h / SIT, 0, 1)[..., None, None]
    loc = np.where(h[..., None, None] >= SIT, POSE["sit"][:, :3] + a * (POSE["stand"][:, :3] - POSE["sit"][:, :3]),
                   POSE["lie"][:, :3] + b * (POSE["sit"][:, :3] - POSE["lie"][:, :3]))     # (N, người, 9, 3)
    walking = np.clip(spd / 0.8, 0, 1)
    swing = 0.2 * np.sin(2 * np.pi * 0.9 * t)[:, None] * walking               # bước chân ~0,9 sải / giây
    loc[..., 3:7, 0] += np.stack([swing, -swing, swing, -swing], -1)          # chân trái / phải ngược pha
    loc[..., 7:9, 0] += np.stack([-0.7 * swing, 0.7 * swing], -1)              # tay vung ngược chân
    loc[..., 3:9, 0] += S["limb"]                                             # DOWN~: tay chân giãy ...
    loc[..., 3:9, 2] += np.abs(S["limb"])                                     # ... và nhấc khỏi sàn
    loc[..., 1, 0] += S["breath"]                                             # ngực, bụng phồng theo nhịp thở
    loc[..., 2, 0] += S["breath"]                                             # thở bụng: bụng phồng như ngực
    c, s_ = np.cos(head)[..., None], np.sin(head)[..., None]
    px = x[..., None] + c * loc[..., 0] - s_ * loc[..., 1]
    py = y[..., None] + s_ * loc[..., 0] + c * loc[..., 1]
    pts = np.stack([px, py, loc[..., 2]], -1)
    strength = POSE["stand"][:, 3] * S["present"][..., None] * np.where(S["behind"], WALL_LOSS, 1)[..., None]
    lying = 1 - np.clip(h / SIT, 0, 1)
    scr = np.stack([x, y, BODY_W + 0.7 * lying, np.zeros_like(x), 0.3 + 1.4 * np.clip(h, 0, 1),
                    (S["present"] & ~S["behind"]).astype(float)], -1)
    N = len(t)
    return pts.reshape(N, -1, 3), strength.reshape(N, -1), scr


def channel(rx, pts, s, scr, objects=FURNITURE, chunk=4000):
    """CSI sạch (N, 52) tại một RX và CSI phòng trống (52,)."""
    paths = static_paths(rx, objects)
    H0 = sum(a * np.exp(-K * L) for a, L, _, _ in paths)
    shaded = [p for p in paths if p[3] is not None and len(p[3]) <= 1]   # đường thẳng + bậc 1 có thể bị người che
    rest = sum(a * np.exp(-K * L) for a, L, _, seq in paths if seq is None or len(seq) > 1)
    # shortcut: phản xạ bậc 2, vật tĩnh và sóng dội từ người không bị người che; thêm nếu cần nhiều người đứng sát nhau
    tx, r3 = at(TX), at(rx)
    imgs = [(mirror(tx, i), mirror(r3, i), i) for i in range(6)]
    out = np.empty((len(pts), len(FREQS)), dtype=complex)
    for a0 in range(0, len(pts), chunk):
        live = (s[a0:a0 + chunk] != 0).any(axis=0)                             # bỏ điểm của người vắng mặt
        P, Sx = pts[a0:a0 + chunk][:, live], s[a0:a0 + chunk][:, live]
        sc = scr[a0:a0 + chunk][:, (scr[a0:a0 + chunk, :, 5] > 0).any(axis=0)]
        amp_s, L_s = [], []
        for amp, L, ptl, _ in shaded:
            f = np.ones(len(P), dtype=complex)
            for A, B in zip(ptl[:-1], ptl[1:]):
                f *= np.prod(screen_factor(A, B, sc), axis=1) if sc.shape[1] else 1
            amp_s.append(amp * f)
            L_s.append(np.full(len(P), L))
        h = rest + sum_paths(np.stack(amp_s, -1), np.stack(L_s, -1))
        dist = lambda q: np.linalg.norm(P - q, axis=-1)
        d_tx, d_rx = dist(tx), dist(r3)
        inside = ((P[..., 0] > 0) & (P[..., 0] < ROOM[0]) & (P[..., 1] > 0) & (P[..., 1] < ROOM[1]))
        amps, Ls = [SIGMA * Sx / (d_tx * d_rx)], [d_tx + d_rx]                # TX → người → RX
        big = np.tile(POSE["stand"][:, 3] >= 0.09, live.size // 9)[live]        # đầu, thân, đùi: thêm đường dội mặt
        Pb, Sb, dtb, drb, inb = P[:, big], Sx[:, big], d_tx[:, big], d_rx[:, big], inside[:, big]
        for itx, irx, i in imgs:                                               # dội 1 mặt trước / sau khi gặp người
            ax, _, mat = PLANES[i]
            a1, a2 = np.linalg.norm(Pb - itx, axis=-1), np.linalg.norm(Pb - irx, axis=-1)
            g1 = gamma(np.abs(Pb[..., ax] - itx[ax]) / a1, mat, ax) * inb
            g2 = gamma(np.abs(Pb[..., ax] - irx[ax]) / a2, mat, ax) * inb
            amps += [SIGMA * Sb * g1 / (a1 * drb), SIGMA * Sb * g2 / (dtb * a2)]
            Ls += [a1 + drb, dtb + a2]
        h += sum_paths(np.concatenate(amps, axis=1), np.concatenate(Ls, axis=1))
        out[a0:a0 + chunk] = h
    return out, H0


def like_esp32(H, H0, rng, noise, rate=100, noise_x=None, bad=None):
    """Thêm lỗi như phần cứng thật, lượng tử về int8. Trả về phần ảo, phần thực (N, 52) và RSSI (N,).
    AGC của ESP32 tự chỉnh khuếch đại theo công suất thu: bù một phần (AGC_ALPHA) sự đổi công suất, trễ ~AGC_TAU,
    theo bậc 0,5 dB – nên khi người che sóng, biên độ CSI tụt ít hơn công suất thật và có bước nhảy chung.
    noise_x: hệ số nhân nhiễu từng gói (đợt nhiễu); bad: mặt nạ gói CSI hỏng (chồng khung Wi-Fi khác)."""
    N, dt = len(H), 1 / rate
    power = np.mean(np.abs(H) ** 2, axis=1) / np.mean(np.abs(H0) ** 2)
    a = 1 - np.exp(-dt / AGC_TAU)
    p_s = lfilter([a], [1, a - 1], power, zi=[(1 - a) * power[0]])[0]
    g_db = np.round(-AGC_ALPHA * 10 * np.log10(p_s) / 0.5) * 0.5
    gain = 10 ** (g_db / 20) * np.exp(rng.normal(0, AGC_STD, N) + slow_noise(rng, N, dt, 0.01, every=60))
    sto = rng.normal(0, 30e-9, N)[:, None]                                      # lệch thời điểm lấy mẫu → pha nghiêng
    phase = np.exp(1j * (rng.uniform(0, 2 * np.pi, N)[:, None] - 2 * np.pi * SUB * 312.5e3 * sto))
    z = H * (gain * LEVEL / np.median(np.abs(H0)))[:, None] * phase
    sd = noise * LEVEL * (noise_x if noise_x is not None else np.ones(N))[:, None]
    z = z + rng.normal(0, 1, z.shape) * sd + 1j * rng.normal(0, 1, z.shape) * sd
    if bad is not None and bad.any():          # gói hỏng: cả gói to / nhỏ đi 2–4 lần, méo thêm theo sóng mang con
        k = int(bad.sum())
        z[bad] *= np.exp(rng.choice([-1, 1], (k, 1)) * rng.uniform(0.7, 1.4, (k, 1))) * rng.uniform(0.6, 1.4, (k, 52))
    q = lambda v: np.clip(np.round(v), -127, 127).astype(np.int8)
    rssi = np.round(-40 + 10 * np.log10(power) + rng.normal(0, 0.5, N)).astype(int)   # RSSI đo trước AGC
    return q(z.imag), q(z.real), rssi


# --------------------------------------------------------------------------- ghi file
def write_session(args, t, rx_data, labels, spans=None):
    sid = datetime.now().strftime("%Y%m%d_%H%M") + "_" + args.tag
    d = Path(args.data_dir) / "raw" / sid
    d.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(args.seed + 1000)
    N, dur = len(t), float(t[-1]) + 1 / args.rate
    rx_seq = (np.arange(N) + int(rng.integers(4096))) % 4096                    # cùng gói → cùng rx_seq ở mọi RX
    bursts = interference_for(args.seed, N, args.rate, args.nhieu)
    # mỗi đợt Wi-Fi một độ bận kênh u: RX đếm 50–400 khung lạ/giây (n_filtered), gói của TX mất 5–40 % (TX phải nhường
    # kênh, RX bận nhận khung khác) – bận hơn thì mất nhiều hơn. Lò vi sóng…: mất 30 % như bản trước, nâng noise_floor.
    others, lost = np.zeros(N), np.full(N, 0.005)                               # lúc thường mất 0,5 % trên không
    for kind, a, b in bursts:
        m, u = (t >= a) & (t < b), rng.random()
        if kind == "wifi":
            others[m] += 50 + 350 * u
        lost[m] = np.maximum(lost[m], 0.05 + 0.35 * u if kind == "wifi" else 0.3)
    nf = np.where(burst_mask(t, bursts, ("khac",)), -85, -95)
    events = [(off, "labels", [ev, val]) for off, ev, val in labels]
    stats = {"lines": {"BOOT": 0, "CSI": 0, "PRB": 0, "STAT": 0}, "lost_by_seq": {}}
    for board, (im, re, rssi) in rx_data.items():
        air = rng.random(N) > lost                                              # mất trên không
        usb = rng.random(N) > 0.001                                             # mất trên USB: seq nhảy
        seq = np.cumsum(air)
        boot = rng.uniform(5, 60)
        t_us = ((t + boot) * 1e6 + rng.normal(0, 200, N)).astype(np.int64)
        host = t + rng.uniform(0.001, 0.004, N)
        raw = np.stack([im, re], axis=-1).reshape(N, -1)
        for j in np.flatnonzero(air & usb):
            events.append((host[j], "csi", [board, int(seq[j]), int(t_us[j]), int(rx_seq[j]), MAC["TX"],
                                            int(rssi[j]), int(nf[j]), CHANNEL, 0, 0, 0, 104, raw[j].tobytes().hex()]))
        for sec in range(1, int(dur) + 1):
            w = (t >= sec - 1) & (t < sec)
            n_filtered = int(rng.poisson(others[w].mean())) + int(rng.integers(0, 6))   # lúc thường 0–5 khung lạ
            events.append((float(sec), "stat", [int((sec + boot) * 1e6), board, int(np.sum(air[w])), n_filtered, 0,
                                               CHANNEL]))
        for sec in range(0, int(dur), 30):
            events.append((sec + 0.01, "boot", [board, "sim-3d", MAC[board], MAC["TX"], CHANNEL]))
        stats["lines"]["CSI"] += int((air & usb).sum())
        stats["lines"]["STAT"] += int(dur)
        stats["lines"]["BOOT"] += len(range(0, int(dur), 30))
        stats["lost_by_seq"][f"{board}/CSI"] = int((air & ~usb).sum())
    events.sort(key=lambda e: e[0])
    start = time.time()                                                         # host_time của giây 0 mô phỏng
    meta = {"session_id": sid, "room": "Mô phỏng 3D: góc phòng 4 x 3,5 x 2,8 m", "channel": CHANNEL,
            "tx_rx_distance_m": round(float(np.mean([np.linalg.norm(p - TX) for p in RX.values()])), 2),
            "members": [], "simulated": True, "ports": {"RX1": None, "RX2": None, "SNF": None}, "notes": "",
            "fw": {b: "sim-3d" for b in RX}, "spec_version": SPEC_VERSION,
            "simulator": {"engine": "3d", "plan": args.plan, "seed": args.seed, "rate": args.rate,
                          "noise": args.noise, "tx": TX.tolist(), "rx": {b: p.tolist() for b, p in RX.items()},
                          "chair": CHAIR.tolist(), "room": list(ROOM), "area": list(AREA),
                          "operator": OPERATOR.tolist() if args.nguoi_bam else None,
                          "objects": [[list(q), s_] for q, s_ in objects_for(args.seed)],
                          "nhieu": args.nhieu, "interference": [list(x) for x in bursts],
                          "bursts_s": round(float(burst_mask(t, bursts).sum()) / args.rate, 1),
                          "t0_host": round(start, 4),
                          "truth": [[n, round(a, 3), round(b, 3)] for n, a, b in spans or []],
                          "down_cu_dong": down_cu_dong(args.plan, spans or [])}}
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    files = {k: open(d / f"{k}.csv", "w", newline="", encoding="utf-8") for k in FILES}
    writers = {k: csv.writer(f) for k, f in files.items()}
    for k, w in writers.items():
        w.writerow(FILES[k])
    if args.phat_lai:
        print(f"Phát lại theo thời gian thực vào {d} (Ctrl+C để dừng).")
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
    meta["stats"] = {"duration_s": round(dur, 1), **stats, "bad_lines": 0,
                     "label_events": len(labels)}
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return d


# --------------------------------------------------------------------------- hình
COLORS = {"EMPTY": "#d4d4d8", "NEIGHBOR": "#3b82f6", "ACTIVE": "#ef4444", "STILL": "#f59e0b", "DOWN": "#7c3aed",
          "BREATH_ABN": "#db2777", "FALL": "#18181b", "SIT_DOWN": "#0d9488", "STAND_UP": "#65a30d",
          "LIE_DOWN": "#0891b2", "PICK_UP": "#a16207"}


def per_sample(t, spans, labels):
    """Nhãn (trạng thái / động tác) và nhịp thở đáp án tại từng mẫu."""
    dt = t[1] - t[0]
    who = np.full(len(t), "", dtype=object)
    for name, a, b in spans:
        who[int(round(a / dt)):int(round(b / dt))] = name
    bpm = np.full(len(t), np.nan)
    for a, ev, val in labels:
        if ev == "RATE":
            bpm[int(round(a / dt)):] = float(val)
    bpm[~np.isin(who, BREATHING)] = np.nan
    return who, bpm


def mean_amp(im, re):
    """Biên độ trung bình các sóng mang con, làm mượt 0,1 s, chia cho mức 2 giây đầu."""
    amp = np.hypot(im.astype(float), re.astype(float)).mean(axis=1)
    amp = np.convolve(np.pad(amp, (5, 4), mode="edge"), np.ones(10) / 10, "valid")   # đệm biên: không tụt ở hai đầu
    return amp / np.median(amp[:200])


def draw_room(ax, neighbor=False):
    from matplotlib.patches import Rectangle

    ax.add_patch(Rectangle((0, 0), *ROOM, fc="#fafafa", ec="#18181b", lw=2))
    if neighbor:
        x0, x1, y0, y1 = NEIGHBOR_ROOM
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc="#eff6ff", ec="#93c5fd", lw=1))
        ax.text((x0 + x1) / 2, y1 + 0.1, "phòng bên", ha="center", color="#3b82f6", fontsize=8)
    ax.add_patch(Rectangle((AREA[0], AREA[2]), AREA[1] - AREA[0], AREA[3] - AREA[2], fc="none", ec="#71717a",
                           ls="--", lw=1))
    for b, p in RX.items():
        ax.plot([TX[0], p[0]], [TX[1], p[1]], c="#0d9488", lw=1.5, alpha=0.7)
        ax.plot(*p, "o", c="#0d9488", ms=11)
        ax.annotate(b, p, (8, -4), textcoords="offset points")
    ax.plot(*TX, "s", c="#ea580c", ms=11)
    ax.annotate("TX", TX, (8, 6), textcoords="offset points")
    ax.plot(*CHAIR, "P", c="#71717a", ms=10)
    ax.annotate("ghế / nệm", CHAIR, (8, 6), textcoords="offset points", color="#71717a", fontsize=8)
    ax.plot(*DOOR, "D", c="#71717a", ms=7)
    ax.annotate("cửa", DOOR, (6, 6), textcoords="offset points", color="#71717a", fontsize=8)
    ax.set_xlim(-0.2, (NEIGHBOR_ROOM[1] if neighbor else ROOM[0]) + 0.2)
    ax.set_ylim(-0.2, ROOM[1] + 0.3)
    ax.set_aspect("equal")


def save_figure(d, t, S, spans, rx_data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig = plt.figure(figsize=(15, 6.5))
    ax = fig.add_axes([0.03, 0.08, 0.36, 0.86])
    draw_room(ax)
    who, _ = per_sample(t, spans, [])
    inside = S["present"][:, 0] & ~S["behind"][:, 0]
    handles = []
    for g in (1, 2):
        m = S["present"][:, g]
        if m.any():
            ax.plot(S["x"][m, g], S["y"][m, g], ".", ms=1, c="#a1a1aa")
    if S["present"][:, 1:3].any():
        handles.append(Line2D([], [], ls="", marker="o", ms=5, c="#a1a1aa", label="khách"))
    if S["present"][:, 3].any():
        ax.plot(*OPERATOR, "o", ms=9, c="#52525b")
        handles.append(Line2D([], [], ls="", marker="o", ms=6, c="#52525b", label="người bấm phím"))
    for name, col in COLORS.items():
        m = inside & (who == name)
        if not m.any():
            continue
        if name == "FALL":
            ends = [int(round(b / (t[1] - t[0]))) - 1 for nm, _, b in spans if nm == "FALL"]
            ax.plot(S["x"][ends, 0], S["y"][ends, 0], "X", ms=12, c=col)
        else:
            ax.plot(S["x"][m, 0], S["y"][m, 0], ".", ms=1.5, c=col)
        handles.append(Line2D([], [], ls="", marker="X" if name == "FALL" else "o", ms=6, c=col, label=name))
    ax.set_title("Nhìn từ trên xuống (góc demo ở gốc toạ độ)")
    ax.legend(handles=handles, loc="upper right", fontsize=7, ncol=2)

    for r, (board, (im, re, _)) in enumerate(rx_data.items()):
        bx = fig.add_axes([0.45, 0.56 - r * 0.47, 0.53, 0.38])
        bx.plot(t, mean_amp(im, re), c="#18181b", lw=0.6)
        for name, a, b in spans:
            if name in ACTIONS:
                bx.axvline(a, c=COLORS[name], lw=1.2)
            else:
                bx.axvspan(a, b, color=COLORS[name], alpha=0.15, lw=0)
        bx.set_ylabel(f"{board}: biên độ TB")
        bx.set_xlim(t[0], t[-1])
        if r == 0:
            bx.set_title("Biên độ CSI trung bình (so với đầu buổi); vạch dọc = động tác")
    bx.set_xlabel("giây")
    fig.savefig(d / "mo_phong.png", dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------- chương trình chính
def main(argv=None):
    ap = argparse.ArgumentParser(description="Mô phỏng 3D buổi thu nhánh người (1 TX + 2 RX, đặc tả v0.3).")
    ap.add_argument("--tag", required=True, help="tên ngắn, chỉ chữ không dấu, số, '-'")
    ap.add_argument("--kich-ban", choices=sorted(KICH_BAN), default="mot-nguoi", help="kịch bản có sẵn")
    ap.add_argument("--plan", help="kịch bản tự viết (ghi đè --kich-ban), xem đầu file")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rate", type=float, default=100, help="số gói mỗi giây")
    ap.add_argument("--noise", type=float, default=0.05, help="nhiễu đo, tính theo biên độ phòng trống (0,05 như WiFall)")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--hinh", action="store_true", help="lưu ảnh mo_phong.png vào thư mục buổi thu")
    ap.add_argument("--phat-lai", action="store_true", help="ghi file theo thời gian thực")
    ap.add_argument("--nguoi-bam", action="store_true",
                    help="có người bấm phím ngồi yên cạnh laptop suốt buổi (không tính vào COUNT)")
    ap.add_argument("--so-buoi", type=int, help="tạo N buổi với kịch bản ngẫu nhiên (tag-01, tag-02, ...)")
    ap.add_argument("--phut", type=float, default=5.0, help="độ dài mỗi buổi ngẫu nhiên, phút")
    ap.add_argument("--yen-lau", type=float, default=0.0,
                    help="với --so-buoi: tỉ lệ buổi (0–1) có một đoạn ngồi / nằm yên 4–8 phút; mặc định 0")
    ap.add_argument("--nhieu", help='ép thêm đợt nhiễu, ví dụ "wifi@60:30,khac@200:3" (loại@giây bắt đầu:thời lượng; '
                                    'loại wifi hoặc khac); thêm mục "tat" để bỏ các đợt ngẫu nhiên')
    args = ap.parse_args(argv)
    if not args.tag or not all(c.isascii() and c.isalnum() or c == "-" for c in args.tag):
        ap.error("--tag chỉ gồm chữ không dấu, số và '-'")
    if not 10 <= args.rate <= 1000:
        ap.error("--rate phải trong khoảng 10–1000")
    if args.so_buoi is not None and not 1 <= args.so_buoi <= 200 or not 1 <= args.phut <= 60:
        ap.error("--so-buoi trong khoảng 1–200, --phut trong khoảng 1–60")
    if not 0 <= args.yen_lau <= 1 or args.yen_lau and args.so_buoi is None:
        ap.error("--yen-lau trong khoảng 0–1 và chỉ dùng cùng --so-buoi")
    parse_nhieu(args.nhieu)                                 # sai cú pháp thì báo ngay, trước khi tính
    plan_given = args.plan is not None
    args.plan = args.plan or KICH_BAN[args.kich_ban]

    if args.so_buoi is None:
        return simulate(args)
    if args.phat_lai or plan_given:
        ap.error("--so-buoi không dùng cùng --phat-lai / --plan")
    master = np.random.default_rng(args.seed)
    out = []
    for k in range(args.so_buoi):                           # mỗi buổi một kịch bản ngẫu nhiên; 30 % buổi có khách
        one = argparse.Namespace(**vars(args))
        one.tag, one.seed = f"{args.tag}-{k + 1:02d}", args.seed + k
        one.plan = random_plan(master, args.phut, guests=master.random() < 0.3,
                               long_still=args.yen_lau > 0 and master.random() < args.yen_lau)  # 0: không rút số
        out.append(simulate(one))
    print(f"Đã tạo {len(out)} buổi trong {Path(args.data_dir) / 'raw'}")
    return out


def compute(plan, seed, rate=100, noise=0.05, operator=False, nhieu=None):
    """Chạy toàn bộ mô phỏng (không ghi file). Cùng plan + seed + nhieu thì luôn ra cùng kết quả."""
    rng = np.random.default_rng(seed)
    t, S, labels, spans = timeline(parse_plan(plan), rate, rng, operator)
    pts, s, shade = body_points(t, S, 1 / rate)
    objects, bursts = objects_for(seed), interference_for(seed, len(t), rate, nhieu)
    with ThreadPoolExecutor() as ex:                                            # 2 RX tính song song (numpy nhả GIL)
        chans = list(ex.map(lambda p: channel(p, pts, s, shade, objects), RX.values()))
    wifi, khac = (burst_mask(t, bursts, (k,)) for k in NHIEU)
    # Wi-Fi khác chỉ gây nhiễu khi khung chồng lên lúc thu → nhiễu tăng vừa (×1,5), 1–3 % gói hỏng hẳn;
    # lò vi sóng… phủ cả dải → ×3 như bản trước. Cả hai là giá trị khởi đầu, chưa đo.
    r = np.random.default_rng(seed + 54322)                                     # gói hỏng: dòng ngẫu nhiên riêng
    rx_data = {b: like_esp32(H, H0, rng, noise, rate, 1 + 0.5 * wifi + 2 * khac,
                             wifi & (r.random(len(t)) < r.uniform(0.01, 0.03))) for b, (H, H0) in zip(RX, chans)}
    return t, S, labels, spans, rx_data


def simulate(args):
    print("Đang tính kênh truyền...")
    t, S, labels, spans, rx_data = compute(args.plan, args.seed, args.rate, args.noise, args.nguoi_bam, args.nhieu)
    d = write_session(args, t, rx_data, labels, spans)
    if args.hinh:
        save_figure(d, t, S, spans, rx_data)
    print(f"Xong ({t[-1]:.0f} giây, {len(t)} gói mỗi RX): {d}")
    return d


if __name__ == "__main__":
    main()
