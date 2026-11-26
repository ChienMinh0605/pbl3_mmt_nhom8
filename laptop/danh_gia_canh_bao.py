#!/usr/bin/env python3
"""Đánh giá bộ cảnh báo (canh_bao.py) theo SỰ KIỆN trên các buổi mô phỏng, chia theo buổi (GroupKFold).

    python danh_gia_canh_bao.py                                   # mọi buổi trong ../data/sim, 5 phần
    python danh_gia_canh_bao.py --data ../data/sim ../data/sim_canh_bao
    python danh_gia_canh_bao.py --max-buoi 10 --jobs 4            # chạy nhanh
    python danh_gia_canh_bao.py --du-doan ../results/<...>_canh_bao/du_doan.joblib --tham-so so_window_nga=2
                                                                  # chỉ chấm lại với tham số khác, không train

Mỗi lượt train 3 bộ phân loại trên các buổi train (file đặc trưng sẵn trong <data>/features, features_action; buổi chưa
có file thì tính bằng features.py; cột theo train.FEATURE_RE): mức hoạt động (6 s), ≥ 2 người (6 s), động tác (3 s).
Mặc định cách B (--gop muon), tầng 0/1 dùng bộ gọn 19 cột/board (--cot6 g6, features.compact6_features), train
trên window 6 s TRƯỢT của buổi train, nhãn lúc cuối window theo simulator.truth (--tang0 cuoi; file 6 s không chồng
lấn bỏ chỗ chuyển tiếp nên lúc chạy hay gọi đi lại là Yên).
Trên các buổi test, đặc trưng tính TRƯỢT từ dữ liệu thô như dashboard (6 s mỗi 1 s, 3 s mỗi 0,5 s, nhịp thở 30 s mỗi
5 s), không dùng nhãn; cờ kênh từ STAT; chạy canh_bao với 4 cấu hình (biến thể a/b × có/không cờ kênh) rồi so với sự
thật trong meta.json → simulator.truth (thời điểm thật, không trễ như labels.csv). Số người thật lấy từ COUNT trong
labels.csv (trễ ≤ 0,8 s).

Chấm:
- Ngã (chỉ những cú ngã lúc có đúng 1 người, nằm ≥ 10 s): bắt được nếu có cảnh báo NGA trong [lúc ngã, lúc ngã + 30 s].
  Ngã rồi tự đứng dậy trong 10 s thì đúng ra không được báo: đếm riêng số lần bị báo.
- Báo giả: cảnh báo NGA không rơi vào khoảng trên của cú ngã nào; BAT_DONG_LAU ngoài [đầu đoạn yên + T − 15 s,
  cuối đoạn + 15 s] của đoạn yên thật ≥ T; THO_BAT_THUONG / NGUNG_THO / NGA_KHAN_CAP (khẩn cấp còn hợp lệ 90 s sau cú ngã thật) ngoài [đầu, cuối + 30 s] của đoạn
  BREATH_ABN (chấm chung cả nhóm thở: báo "thở bất thường" lúc nín thở không tính là giả).
- Đếm người nguy hiểm: thời gian thật có 1 người mà hệ thống ở chế độ nhiều người (tắt ngã, nhịp thở).
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")    # SVD nhỏ của đặc trưng động tác: nhiều luồng BLAS chậm hơn hẳn

import argparse  # noqa: E402
import json  # noqa: E402
import multiprocessing  # noqa: E402
import sys  # noqa: E402
import warnings  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402
import train as T  # noqa: E402
from canh_bao import ThamSo, chay_lai, kenh_ban  # noqa: E402
from mo_phong import parse_plan  # noqa: E402
from nhan import ACTIONS, ACTIVITY  # noqa: E402
from nhip_tho import uoc_luong  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CAU_HINH = {"a, có cờ kênh": ("a", True), "a, không cờ": ("a", False),
            "b, có cờ kênh": ("b", True), "b, không cờ": ("b", False)}
LOAI = ["NGA", "NGA_KHAN_CAP", "BAT_DONG_LAU", "THO_BAT_THUONG", "NGUNG_THO"]
NHOM_THO = ("THO_BAT_THUONG", "NGUNG_THO", "NGA_KHAN_CAP")
TAU_NGA_MUON = 0.4                                    # P(FALL) = max hai board, mô hình 25 cột mot (sim2: 38/53, 6,7 giả/giờ)
TAU_NHIEU_G6 = 0.8                                    # P(≥2) bộ g6, sim2: lỗi nguy hiểm 0,1 % (212 cột: 0,4 %), nhận ≥2 8 %
XGB_DONG_TAC = {"max_depth": 5}                       # bộ 25 cột: sâu 5 hơn sâu 4 ~0,03 AP, vẫn < 1 MB flash
BAT = 30.0                                            # cảnh báo ngã trong 30 s sau lúc ngã thì tính bắt được
DONG = ("ACTIVE",) + tuple(ACTIONS)                   # trạng thái thật "đang chuyển động" (để tách lỗi đếm người)


# --------------------------------------------------------------------------- dữ liệu một buổi
def gop_tho(kqs):
    """Nhịp thở của từng board → một kết quả: board có đỉnh thở nổi nhất (như kế hoạch: chọn đường truyền có dải thở
    mạnh nhất); không board nào đo được thì 'cu-dong' > 'yeu' > 'khong-thay' (chỉ 'khong-thay' mới tính ngưng thở)."""
    co = [k for k in kqs if k[0] is not None]
    if co:
        return max(co, key=lambda k: k[1])
    return next((k for ly in ("cu-dong", "yeu") for k in kqs if k[2] == ly), kqs[0])


def luoi(t, amp, a, e, rate):
    """Gói trong [a, e) đặt lên lưới thời gian đều; ô không có gói = hàng NaN (nhip_tho coi là gói mất và nội suy,
    thay vì bỏ hàng làm co trục thời gian)."""
    i, j = np.searchsorted(t, [a, e])
    out = np.full((int(round((e - a) * rate)), amp.shape[1]), np.nan)
    k = np.clip(np.round((t[i:j] - a) * rate).astype(int), 0, len(out) - 1)
    out[k] = amp[i:j]
    return out


def truot(d, rate=100.0):
    """Đặc trưng trượt từ dữ liệu thô (không dùng nhãn) + sự thật của một buổi."""
    meta, boards, labels = F.load_session(d)
    t0 = min(v[0][0] for v in boards.values())
    t1 = max(v[0][-1] for v in boards.values())

    def windows(win, step, shape):
        rows = []
        for e in np.arange(t0 + win, t1 + 1e-9, step):
            row = {"t": round(float(e), 3)}
            for name, (t, amp, rssi) in boards.items():
                i, j = np.searchsorted(t, [e - win, e])
                if j - i < 0.7 * rate * win:                          # thiếu mẫu: không dự đoán (như valid = 0)
                    break
                row.update(F.window_features(amp[i:j], rssi[i:j], prefix=name.lower() + "_", shape=shape, rate=rate))
            else:
                rows.append(row)
        return pd.DataFrame(rows)

    tho, tho_rx = [], []
    for e in np.arange(t0 + 30, t1 + 1e-9, 5.0):
        amps = [luoi(t, amp, e - 30, e, rate) for t, amp, _ in boards.values()]
        tho.append((round(float(e), 3), uoc_luong(amps, rate)))
        tho_rx.append((round(float(e), 3), gop_tho([uoc_luong([a], rate) for a in amps])))   # gộp muộn: mỗi board tự đo
    st = pd.read_csv(d / "stat.csv") if (d / "stat.csv").exists() else pd.DataFrame(
        columns=["host_time", "board", "n_rx", "n_filtered"])
    st = st[st["board"].astype(str).str.startswith("RX")]
    ban = list(zip(st["host_time"].round(3), kenh_ban(st["n_rx"], st["n_filtered"], rate)))
    sim = meta.get("simulator") or {}
    th = sim.get("t0_host", t0)                       # buổi cũ không có t0_host: lấy gói CSI đầu (sai số vài ms)
    spans = [(n, th + a, th + b) for n, a, b in sim.get("truth", [])]
    items = [it for it in parse_plan(sim["plan"]) if it[0] not in ("+", "-")] if sim.get("plan") else []
    return {"sid": d.name, "t0": t0, "t1": t1, "x6": windows(6.0, 1.0, False), "xa": windows(3.0, 0.5, True),
            "tho": tho, "tho_rx": tho_rx, "ban": [(t, bool(b)) for t, b in ban], "spans": spans, "L": F.Labels(labels),
            "bpm": [it[2] for it in items] if len(items) == len(spans) else [None] * len(spans),
            "nhieu": [(k, th + a, th + b) for k, a, b in sim.get("interference", [])],
            "cu_dong": [(th + a, th + b) for a, b in sim.get("down_cu_dong", [])],
            "co_nhieu": "interference" in sim}


def nhan_truot(r, cach="da_so"):
    """Window 6 s TRƯỢT của một buổi train (đúng loại window lúc chạy, gồm cả chỗ chuyển tiếp) + nhãn từ
    simulator.truth, thay cho file 6 s không chồng lấn đã bỏ chỗ chuyển tiếp. Mức hoạt động: "da_so" = mức chiếm lâu
    nhất trong window, "cuoi" = mức lúc 0,5 s trước cuối window; động tác (FALL, SIT_DOWN...) tính là Hoạt động."""
    x, spans = r["x6"].copy(), [(ACTIVITY.get(n, 1), a, b) for n, a, b in r["spans"]]
    y = []
    for e in x["t"]:
        if cach == "cuoi":
            y.append(next((m for m, a, b in spans if a <= e - 0.5 < b), np.nan))
            continue
        o = np.zeros(3)
        for m, a, b in spans:
            o[m] += max(min(b, e) - max(a, e - 6.0), 0)
        y.append(o.argmax() if o.sum() >= 3.0 else np.nan)           # ngoài sự thật (trước/sau buổi): bỏ
    x["activity"], x["valid"] = y, 1
    x["n_people"] = [r["L"].people(e - 3.0) for e in x["t"]]
    return x.dropna(subset=["activity"]).astype({"activity": int})


def mot_buoi(dd, d):
    """truot() + đặc trưng để train: file sẵn trong <dd>/features, features_action; chưa có thì tính bằng features."""
    r = truot(d)
    for key, kieu, ham in (("f6", "features", F.session_windows), ("fa", "features_action", F.action_windows)):
        f = dd / kieu / f"{d.name}.csv"
        r[key] = pd.read_csv(f) if f.exists() else ham(d)[1]
    return r


# --------------------------------------------------------------------------- mô hình
def train_mot(df, cols, y, model_key, seed, xgb=None):
    classes, yy = np.unique(y, return_inverse=True)
    if len(classes) < 2:
        return None, classes
    m = T.build_models(cols, len(classes), seed, xgb)[model_key]
    m.set_params(n_jobs=1)                            # mỗi lượt một tiến trình; nhiều luồng trên máy bận chậm hơn hẳn
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        T.fit(m, df[cols].to_numpy(float), yy, True)
    return m, classes


def so_nut(m):
    """Tổng số nút của mô hình cây – thước đo thô dung lượng / thời gian chạy khi đưa lên board."""
    if hasattr(m, "get_booster"):
        return len(m.get_booster().trees_to_dataframe())
    return sum(e.tree_.node_count for e in getattr(m, "estimators_", []))


def mot_luot(d6, da, tests, cols6, colsa, model, seed, gop="chung"):
    """Một lượt GroupKFold: train 3 bộ phân loại trên window của các buổi train → ({buổi test: quan sát}, số nút).
    gop "chung": một bộ mô hình trên cột của mọi RX (cách A, như laptop). "muon": mỗi RX một bộ mô hình chỉ trên cột
    của nó (cách B – mỗi board tự chạy), rồi gộp kết quả trong du_doan."""
    d6 = d6[d6["valid"] == 1].dropna(subset=cols6)
    da = da[da["valid"] == 1].dropna(subset=colsa)
    dn = d6[d6["n_people"] >= 1]                       # tầng 1 chỉ chạy khi có người
    nhom = [""] if gop == "chung" else sorted({c.split("_")[0] + "_" for c in cols6})
    bo = []
    for p in nhom:
        c6 = [c for c in cols6 if c.startswith(p)]
        ca = [c for c in T.select_features(colsa, "mot") if c.startswith(p)] or [c for c in colsa if c.startswith(p)]
        bo.append((*train_mot(d6, c6, d6["activity"].to_numpy(int), model, seed),
                   *train_mot(dn, c6, dn["n_people"].to_numpy() >= 2, model, seed),
                   *train_mot(da, ca, da["action"].to_numpy(str), model, seed, XGB_DONG_TAC), c6, ca))
    nut = {"board": len(bo), "cot_6s": len(bo[0][6]), "cot_3s": len(bo[0][7]),
           "nut_6s": so_nut(bo[0][0]) + so_nut(bo[0][2]), "nut_3s": so_nut(bo[0][4])}
    return {r["sid"]: du_doan(r, bo, gop) for r in tests}, nut


def du_doan(r, bo, gop):
    """→ danh sách quan sát cho canh_bao: [(t, {muc, p_nhieu, dong_tac, p_nga, tho, ban})]. Nhiều bộ (gộp muộn):
    mức hoạt động, động tác = trung bình xác suất; ngã = board nào thấy cũng được (lấy max P(FALL)); nhiều người = cả
    hai board cùng thấy (lấy min P(≥2)) – theo nguyên tắc an toàn: bỏ sót ngã và tắt nhầm phát hiện ngã đều nguy hiểm."""
    obs = {}
    x6 = r["x6"].dropna(subset=[c for b in bo for c in b[6]])
    if len(x6):
        P6 = np.mean([b[0].predict_proba(x6[b[6]].to_numpy(float)) for b in bo], axis=0)
        pn = np.min([b[2].predict_proba(x6[b[6]].to_numpy(float))[:, list(b[3]).index(True)] if b[2] is not None
                     else np.zeros(len(x6)) for b in bo], axis=0)
        for t, a, n in zip(x6["t"], bo[0][1][P6.argmax(1)], pn):
            obs.setdefault(t, {}).update(muc=int(a), p_nhieu=float(n))
    xa = r["xa"].dropna(subset=[c for b in bo for c in b[7]])
    if len(xa):
        Ps = [b[4].predict_proba(xa[b[7]].to_numpy(float)) for b in bo]
        ca = bo[0][5]
        P = np.mean(Ps, axis=0)
        pf = np.max(Ps, axis=0)[:, list(ca).index("FALL")] if "FALL" in ca else 0 * P[:, 0]
        for t, a, f in zip(xa["t"], ca[P.argmax(1)], pf):
            obs.setdefault(t, {}).update(dong_tac=str(a), p_nga=float(f))   # p_nga: chấm lại theo --tau-nga
    for t, kq in r["tho" if gop == "chung" else "tho_rx"]:
        obs.setdefault(t, {})["tho"] = kq
    for t, b in r["ban"]:
        o = obs.setdefault(t, {})
        o["ban"] = o.get("ban", False) or b
    return sorted(obs.items())


# --------------------------------------------------------------------------- chấm
def trong(t, khoang):
    return any(a <= t <= b for a, b in khoang)


def cham(r, canh, so, obs, p):
    """So cảnh báo của một buổi với sự thật → dict đếm (cộng dồn được giữa các buổi)."""
    spans, L = r["spans"], r["L"]
    ten = lambda t: next((n for n, a, b in spans if a <= t < b), None)
    k = {"gio": (r["t1"] - r["t0"]) / 3600, "nga": 0, "nga_bat": 0, "tre": [], "nga_nhieu_nguoi": 0, "dung_day": 0,
         "dung_day_bi_bao": 0, "giay": 0, "giay_bat": 0, "bo_sot": {}, "gia": {x: 0 for x in LOAI}, "gia_do": {},
         "gia_nhieu": {}, "trung": 0,
         "bat_dong": 0, "bat_dong_bat": 0, "tho": 0, "tho_bat": 0, "ngung": 0, "ngung_bat": 0, "dem": {},
         "gio_nhieu": sum(b - a for _, a, b in r["nhieu"]) / 3600}
    nga_t = [c["t"] for c in canh if c["loai"] == "NGA"]
    fall_win = [t for t, o in obs if o.get("dong_tac") == "FALL"]
    so_t, so_v = np.array([t for t, _ in so]), np.array([v for _, v in so])
    he_thong = lambda t: int(so_v[np.searchsorted(so_t, t, side="right") - 1]) if len(so_t) and t >= so_t[0] else 0
    hop_le = {x: [] for x in LOAI}                    # khoảng thời gian mà cảnh báo loại đó là đúng
    for i, (n, a, b) in enumerate(spans):
        if n == "FALL":
            hop_le["NGA"].append((a, a + BAT))
            hop_le["NGA_KHAN_CAP"].append((a, a + 90))  # nâng mức một cú ngã thật (chưa đo được thở), không phải báo giả
            if L.people(a) >= 2:
                k["nga_nhieu_nguoi"] += 1
                continue
            hit = [t for t in nga_t if a <= t <= a + BAT]
            nxt = spans[i + 1] if i + 1 < len(spans) else (None, b, b)
            if nxt[0] == "DOWN" and nxt[2] - nxt[1] < p.cho_nga_s:     # tự đứng dậy ngay: đúng ra không được báo
                k["dung_day"] += 1
                k["dung_day_bi_bao"] += bool(hit)
                continue
            k["nga"] += 1
            k["nga_bat"] += bool(hit)
            k["trung"] += max(len(hit) - 1, 0)
            if hit:
                k["tre"].append(min(hit) - a)
            else:
                ly_do = ("không có window FALL" if not any(a <= t <= a + 5 for t in fall_win) else
                         "đang chế độ nhiều người" if he_thong(a + 3) >= 2 else "có window FALL, không báo trong 30 s")
                k["bo_sot"][ly_do] = k["bo_sot"].get(ly_do, 0) + 1
            if nxt[0] == "DOWN" and any(min(nxt[2], y) > max(nxt[1], x) for x, y in r["cu_dong"]):
                k["giay"] += 1
                k["giay_bat"] += bool(hit)
        elif n == "BREATH_ABN" and L.people(a) <= 1:
            ngung = r["bpm"][i] == 0
            hop = [c["t"] for c in canh if (c["loai"] in ("NGUNG_THO", "NGA_KHAN_CAP") if ngung
                                               else c["loai"] == "THO_BAT_THUONG") and a <= c["t"] <= b + 30]
            k["ngung" if ngung else "tho"] += 1
            k["ngung_bat" if ngung else "tho_bat"] += bool(hop)
        if n == "BREATH_ABN":
            for x in NHOM_THO:
                hop_le[x].append((a, b + 30))
    run = None                                        # đoạn yên thật: các trạng thái thở liền nhau
    for n, a, b in spans + [("END", np.inf, np.inf)]:
        if n in F.BREATHING and run and abs(run[1] - a) < 1e-6:
            run[1] = b
            continue
        if run and run[1] - run[0] >= p.bat_dong_s:
            hop_le["BAT_DONG_LAU"].append((run[0] + p.bat_dong_s - 15, run[1] + 15))
            if L.people(run[0]) <= 1:
                k["bat_dong"] += 1
                k["bat_dong_bat"] += any(c["loai"] == "BAT_DONG_LAU" and trong(c["t"], hop_le["BAT_DONG_LAU"][-1:])
                                         for c in canh)
        run = [a, b] if n in F.BREATHING else None
    for c in canh:
        if trong(c["t"], hop_le[c["loai"]]):
            continue
        k["gia"][c["loai"]] += 1
        if c["loai"] == "NGA":                        # cú ngã giả sinh từ động tác / trạng thái thật nào
            g = ten(c["t_phat_hien"] - 1.5) or "?"
            k["gia_do"][g] = k["gia_do"].get(g, 0) + 1
        for kind, a, b in r["nhieu"]:
            if a <= c["t_phat_hien"] <= b + 6:        # window 3–6 s kết thúc sau đợt nhiễu vẫn còn chồng lên nó
                key = f"{c['loai']}/{kind}"
                k["gia_nhieu"][key] = k["gia_nhieu"].get(key, 0) + 1
                break
    for t, v in so:                                   # mỗi window 6 s trượt 1 s ≈ 1 giây
        that = min(L.people(t), 2)
        key = f"{'chuyen_dong' if ten(t - 3) in DONG else 'giu_so'}|{that}|{min(v, 2)}"
        k["dem"][key] = k["dem"].get(key, 0) + 1
    return k


def cong(a, b):
    for x, v in b.items():
        if isinstance(v, dict):
            a.setdefault(x, {})
            cong(a[x], v)
        else:
            a[x] = a.get(x, 0 if not isinstance(v, list) else []) + v
    return a


# --------------------------------------------------------------------------- báo cáo
def bao_cao(kq, info):
    L = [f"ĐÁNH GIÁ CẢNH BÁO THEO SỰ KIỆN – {info['created']}",
         "[!] DỮ LIỆU GIẢ (mô phỏng): các con số chỉ để thử luồng xử lý, không phải kết quả đề tài.",
         f"Dữ liệu: {', '.join(info['data'])} | {info['n_sessions']} buổi, {info['gio']:.2f} giờ | {info['cv']}",
         f"Mô hình: {info['model']} | cột đặc trưng: 6 s {info['n_cols6']}, 3 s {info['n_colsa']} | "
         f"uu_tien_1_nguong {info['tau']} | ngưỡng P(FALL) {info.get('tau_nga') or 'argmax'}",
         f"Gộp: {info.get('gop', 'chung')} | tầng 0/1 train trên: {info.get('tang0', 'file')}, "
         f"cột {info.get('cot6', 'bai_bao')} | "
         f"mỗi board (lượt cuối): {info.get('moi_board', '-')}",
         f"Tham số: {info['tham_so']}", ""]
    hd = f"{'Cấu hình':16s} {'Ngã bắt được':>14s} {'Trễ TB/max (s)':>15s} {'Ngã có giãy':>12s} " + \
         " ".join(f"{x:>13s}" for x in LOAI) + f" {'Trùng':>6s}"
    L += ["Ngã: bắt được nếu có cảnh báo NGA trong 30 s sau lúc ngã thật. Báo giả: số mỗi giờ theo loại.", hd]
    for name, k in kq.items():
        tre = f"{np.mean(k['tre']):.1f}/{np.max(k['tre']):.1f}" if k["tre"] else "-"
        giay = f"{k['giay_bat']}/{k['giay']}" if k["giay"] else "-"
        L.append(f"{name:16s} {k['nga_bat']:>5d}/{k['nga']:<3d}{k['nga_bat'] / max(k['nga'], 1):5.0%} {tre:>15s} "
                 f"{giay:>12s} " + " ".join(f"{k['gia'][x] / k['gio']:13.2f}" for x in LOAI) + f" {k['trung']:>6d}")
    k0 = next(iter(kq.values()))
    L += ["", f"Ngã lúc có khách (không chấm, chế độ nhiều người tắt ngã): {k0['nga_nhieu_nguoi']}"]
    L += [f"Ngã rồi tự đứng dậy trong {info['tham_so']['cho_nga_s']:g} s (không được báo), số lần bị báo: " +
          ", ".join(f"{name} {k['dung_day_bi_bao']}/{k['dung_day']}" for name, k in kq.items())]
    for name, k in kq.items():
        L.append(f"  {name:16s} ngã bỏ sót: {k['bo_sot'] or '-'} | báo ngã giả sinh từ: {k['gia_do'] or '-'}")
    L += ["", "Sự kiện khác (độ nhạy):"]
    for name, k in kq.items():
        f = lambda a, b: f"{k[a]}/{k[b]}" if k[b] else "-"
        L.append(f"  {name:16s} bất động ≥ T: {f('bat_dong_bat', 'bat_dong'):>6s} | thở nhanh/chậm: "
                 f"{f('tho_bat', 'tho'):>6s} | nín thở: {f('ngung_bat', 'ngung'):>6s}")
    L += ["", f"Báo giả rơi vào đợt nhiễu (simulator.interference; {k0['gio_nhieu'] * 3600:.0f} s nhiễu, "
              f"{info['n_co_nhieu']} buổi có thông tin):"]
    for name, k in kq.items():
        L.append(f"  {name:16s} {k['gia_nhieu'] or '-'}")
    L += ["", "Đếm người (giây; hàng: thật 0/1/≥2, cột: hệ thống 0/1/≥2):"]
    for name in ("a, có cờ kênh", "a, không cờ"):                # biến thể a/b không đổi cách đếm người
        d = kq[name]["dem"]
        for phan in ("chuyen_dong", "giu_so"):
            m = np.array([[d.get(f"{phan}|{a}|{b}", 0) for b in range(3)] for a in range(3)])
            L.append(f"  {name:16s} {'lúc chuyển động' if phan == 'chuyen_dong' else 'lúc giữ số':16s} "
                     f"{m.tolist()} | nguy hiểm (thật 1 → nhiều người): {m[1, 2] / max(m[1].sum(), 1):.1%}")
    return "\n".join(L)


# --------------------------------------------------------------------------- chương trình chính
def main():
    ap = argparse.ArgumentParser(description="Đánh giá cảnh báo theo sự kiện trên dữ liệu mô phỏng.")
    ap.add_argument("--data", nargs="+", default=[str(ROOT / "data" / "sim")],
                    help="thư mục dữ liệu (mỗi thư mục có raw/, features/, features_action/)")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--max-buoi", type=int, help="chỉ dùng N buổi đầu (chạy nhanh)")
    ap.add_argument("--model", choices=["xgb", "rf"], default="xgb")
    ap.add_argument("--tau", type=float, help="ngưỡng P(≥ 2 người); mặc định: cách B TAU_NHIEU_G6 (bộ g6) hoặc "
                                              "ThamSo.uu_tien_1_nguong, cách A "
                                              "đọc models/model_latest_n_people.joblib → uu_tien_1_nguong")
    ap.add_argument("--tau-nga", type=float, help="coi window là FALL khi P(FALL) ≥ ngưỡng này; mặc định: cách B "
                                                  "TAU_NGA_MUON, cách A đọc models/model_latest_action.joblib → "
                                                  "fall_nguong, không có thì argmax")
    ap.add_argument("--gop", choices=["chung", "muon"], default="muon",
                    help="chung: một mô hình trên mọi RX (cách A); muon: mỗi RX một mô hình rồi gộp kết quả (cách B)")
    ap.add_argument("--tang0", choices=["file", "da_so", "cuoi"], default="cuoi",
                    help="window train tầng 0/1: file 6 s không chồng lấn, hoặc window trượt như lúc chạy với nhãn "
                         "theo mức chiếm đa số (da_so) / tại cuối window (cuoi), xem nhan_truot")
    # g6 mặc định: sim2 cách B ngang 212 cột, ít báo giả hơn (results/20261126_090844 so với _085915_canh_bao)
    ap.add_argument("--cot6", choices=["bai_bao", "g6"], default="g6",
                    help="cột tầng 0/1 (window 6 s): bai_bao = 4 đặc trưng × RSSI + từng sóng mang con (212 cột/board), "
                         "g6 = bộ gọn features.compact6_features (19 cột/board, cần --tang0 da_so/cuoi)")
    ap.add_argument("--jobs", type=int, default=4, help="số tiến trình (đặc trưng trượt, các lượt train)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--du-doan", help="file du_doan.joblib của lần chạy trước: chỉ chấm lại, không train")
    ap.add_argument("--tham-so", nargs="*", default=[], metavar="TÊN=GIÁ_TRỊ",
                    help="đổi tham số số của canh_bao.ThamSo, ví dụ so_window_nga=2 so_cua_so_ngung=3")
    args = ap.parse_args()
    F._check_compact6()
    ts = {k: type(getattr(ThamSo(), k))(v) for k, v in (x.split("=", 1) for x in args.tham_so)}

    created = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "results" / f"{created}_canh_bao"
    if args.du_doan:                                  # chấm lại với quy tắc / tham số mới, không train lại
        D, out = joblib.load(args.du_doan), Path(args.du_doan).parent        # ghi đè báo cáo cạnh file dự đoán
    else:
        buoi = [(Path(dd), d) for dd in args.data for d in sorted((Path(dd) / "raw").glob("*"))
                if (d / "csi.csv").exists() and (d / "meta.json").exists()][:args.max_buoi]
        if len(buoi) < 2:
            sys.exit("Cần ít nhất 2 buổi.")
        print(f"{len(buoi)} buổi. Tính đặc trưng trượt từ dữ liệu thô ({args.jobs} tiến trình)...", flush=True)
        ctx = multiprocessing.get_context("spawn")     # fork khi tiến trình cha đã có luồng dễ treo (đã gặp)
        with ProcessPoolExecutor(args.jobs, mp_context=ctx) as ex:
            R = list(ex.map(mot_buoi, *zip(*buoi)))
        S6, SA = {r["sid"]: r.pop("f6") for r in R}, {r["sid"]: r.pop("fa") for r in R}
        if args.tang0 != "file":
            S6 = {r["sid"]: nhan_truot(r, args.tang0) for r in R}
        pick = lambda frames, run: sorted(set.intersection(*[{c for c in f.columns if T.FEATURE_RE.match(c)}
                                                             for f in frames]) & set(run.columns))
        cols6, colsa = T.select_features(pick(S6.values(), R[0]["x6"]), args.cot6), pick(SA.values(), R[0]["xa"])
        if not cols6:
            sys.exit(f"Không có cột {args.cot6} cho tầng 0/1 (file đặc trưng cũ không có g6_: dùng --tang0 cuoi).")
        print(f"Cột đặc trưng: 6 s {len(cols6)}, 3 s {len(colsa)} (giao giữa file đặc trưng và đặc trưng lúc chạy)")
        sids = np.array([r["sid"] for r in R])
        n_split = min(args.folds, len(sids))
        splits = list(GroupKFold(n_splits=n_split).split(sids, groups=sids))
        print(f"Train + dự đoán {n_split} lượt song song...", flush=True)
        obs, cat = {}, lambda S, idx: pd.concat([S[sids[i]] for i in idx], ignore_index=True)
        with ProcessPoolExecutor(min(args.jobs, n_split), mp_context=ctx) as ex:
            jobs = [ex.submit(mot_luot, cat(S6, tr), cat(SA, tr), [R[i] for i in te], cols6, colsa, args.model,
                              args.seed, args.gop) for tr, te in splits]
            for j in jobs:
                o, nut = j.result()
                obs.update(o)
                print(f"  xong lượt: test {', '.join(o)}", flush=True)
        for r in R:
            del r["x6"], r["xa"]
        D = {"R": R, "obs": obs, "info": {"data": [str(Path(x).resolve()) for x in args.data], "model": args.model,
                                          "cv": f"GroupKFold {n_split} phần theo buổi", "n_cols6": len(cols6),
                                          "n_colsa": len(colsa), "gop": args.gop, "moi_board": nut,
                                          "tang0": args.tang0, "cot6": args.cot6}}
        out.mkdir(parents=True, exist_ok=True)
        joblib.dump(D, out / "du_doan.joblib")
    R, obs = D["R"], D["obs"]
    # ngưỡng mặc định: cách B dùng số đã chọn (models/ là mô hình cách A của train.py, ngưỡng không hợp cách B)
    muon = D["info"].get("gop") == "muon"
    tau, tau_nga = args.tau, args.tau_nga
    if tau is None:
        bundle = ROOT / "models" / "model_latest_n_people.joblib"
        tau = TAU_NHIEU_G6 if muon and D["info"].get("cot6") == "g6" else \
            ThamSo().uu_tien_1_nguong if muon or not bundle.exists() else float(
            joblib.load(bundle).get("uu_tien_1_nguong", 0.7))
    if tau_nga is None:
        bundle = ROOT / "models" / "model_latest_action.joblib"
        tau_nga = TAU_NGA_MUON if muon else joblib.load(bundle).get("fall_nguong") if bundle.exists() else None
    if tau_nga is not None:                           # ngưỡng thấp: bắt thêm ngã, bước xác nhận 10 s lọc bớt báo nhầm
        for o in (o for v in obs.values() for _, o in v if "p_nga" in o):
            o["dong_tac"] = "FALL" if o["p_nga"] >= tau_nga else ("NONE" if o["dong_tac"] == "FALL" else o["dong_tac"])
    obs = {s: [(t, {k: x for k, x in o.items() if k != "p_nga"}) for t, o in v] for s, v in obs.items()}
    kq = {name: {} for name in CAU_HINH}
    chi_tiet = {name: {} for name in CAU_HINH}
    for r in R:
        for name, (bt, co) in CAU_HINH.items():
            p = ThamSo(bien_the=bt, co_kenh=co, uu_tien_1_nguong=tau, **ts)
            canh, so = chay_lai(obs[r["sid"]], p)
            cong(kq[name], cham(r, canh, so, obs[r["sid"]], p))
            chi_tiet[name][r["sid"]] = canh

    p0 = ThamSo(uu_tien_1_nguong=tau, **ts)
    info = {**D["info"], "created": created, "n_sessions": len(R), "gio": next(iter(kq.values()))["gio"], "tau": tau, "tau_nga": tau_nga,
            "n_co_nhieu": sum(r["co_nhieu"] for r in R), "du_doan": str(out / "du_doan.joblib"),
            "tham_so": {k: v for k, v in vars(p0).items() if k not in ("bien_the", "co_kenh")}}
    text = bao_cao(kq, info)
    print()
    print(text)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.txt").write_text(text + "\n", encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps({"info": info, "ket_qua": kq, "canh_bao": chi_tiet}, indent=1,
                                                 ensure_ascii=False, default=float), encoding="utf-8")
    print(f"\nĐã lưu: {out}")


if __name__ == "__main__":
    main()
