#!/usr/bin/env python3
"""Xuất mô hình động tác của MỘT board (cách B) sang dạng chạy được trên ESP32-S3, kèm dữ liệu đối chiếu.

    python xuat_board.py                                   # train trên ../data/sim2, ghi vào ../firmware/thu_mo_hinh/main/

Ghi ra (đọc bằng firmware/thu_mo_hinh/main/mo_hinh.c, dac_trung.c):
- mo_hinh.bin: XGBoost 25 cột `mot`/`mon` của RX1 dạng bảng nút (board đi qua bảng bằng một vòng lặp, bảng nằm trong flash).
- du_lieu_thu.bin: vài chục window 3 s CSI thô (int8, đúng như dòng CSI board nhận) của các buổi KHÔNG dùng để train,
  kèm đáp án Python: 25 cột (features.robust_features) và xác suất từng lớp – để so kết quả C với Python.

Định dạng (little-endian, cả x86 lẫn ESP32):
mo_hinh.bin   'MH02', u16 số cột, u16 số lớp, u32 số cây, u32 số nút, f32 base[số lớp], u32 gốc[số cây], rồi mỗi nút
              16 byte: f32 ngưỡng|giá trị lá, i16 cột (-1 = lá), u8 thiếu→trái, u8 0, u32 trái, u32 phải.
              Cây t thuộc lớp t % số lớp; đi trái khi x < ngưỡng.
du_lieu_thu.bin 'DL01', u16 số window, u16 số sóng mang con, u16 số cột, u16 số lớp, rồi mỗi window:
              u16 số gói, u16 0, f32 cột[số cột], f32 xác suất[số lớp], i8 csi[số gói × 2 × số sóng mang con].
"""
import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402
import train as T  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# thứ tự cột trên board = thứ tự robust_features trả về (dac_trung.c ghi đúng thứ tự này)
COT = (["mot_bad"] + [f"mot_b{i}" for i in range(5)] + ["mot_peak", "mot_ratio"] +
       [f"mon_{k}" for k in ["pc1", "cvmed", "cvmax", "b0", "b1", "b2", "b3", "b4", "slope", "pos", "after", "before",
                              "busy", "tail", "head", "lvl", "width"]])
assert len(COT) == 25


def bang_nut(model):
    """XGBoost → bảng nút phẳng, đọc từ JSON của chính mô hình (ngưỡng float32 đúng từng bit, không qua chữ)."""
    j = json.loads(model.get_booster().save_raw("json"))["learner"]
    trees = j["gradient_booster"]["model"]["trees"]
    lop = j["gradient_booster"]["model"]["tree_info"]
    n_class = int(j["learner_model_param"]["num_class"])
    base = [float(x) for x in j["learner_model_param"]["base_score"].strip("[]").split(",")]
    base = base * n_class if len(base) == 1 else base
    assert all(c == t % n_class for t, c in enumerate(lop)), "cây phải xếp vòng theo lớp"
    goc, cot, thieu, val, trai, phai = [], [], [], [], [], []
    for tr in trees:
        o = len(cot)
        goc.append(o)
        L, R = tr["left_children"], tr["right_children"]
        for i in range(len(L)):
            la = L[i] == -1
            cot.append(-1 if la else tr["split_indices"][i])
            thieu.append(int(tr["default_left"][i]))
            val.append(tr["split_conditions"][i])           # lá: giá trị lá nằm ở đây
            trai.append(0 if la else o + L[i])
            phai.append(0 if la else o + R[i])
    return {"n_class": n_class, "base": np.array(base, np.float32), "goc": np.array(goc, np.uint32),
            "cot": np.array(cot, np.int16), "thieu": np.array(thieu, np.uint8), "val": np.array(val, np.float32),
            "trai": np.array(trai, np.uint32), "phai": np.array(phai, np.uint32)}


def du_doan_bang(b, X):
    """Chạy bảng nút đúng như board (float32) → xác suất; dùng để tự kiểm bảng xuất ra."""
    X = np.asarray(X, np.float32)
    M = np.tile(b["base"], (len(X), 1)).astype(np.float64)
    for t, g in enumerate(b["goc"]):
        for r in range(len(X)):
            i = g
            while b["cot"][i] >= 0:
                x = X[r, b["cot"][i]]
                i = (b["trai"][i] if b["thieu"][i] else b["phai"][i]) if np.isnan(x) else \
                    (b["trai"][i] if x < b["val"][i] else b["phai"][i])
            M[r, t % b["n_class"]] += b["val"][i]
    E = np.exp(M - M.max(axis=1, keepdims=True))
    return E / E.sum(axis=1, keepdims=True)


NUT = np.dtype([("val", "<f4"), ("cot", "<i2"), ("thieu", "u1"), ("dem", "u1"), ("trai", "<u4"), ("phai", "<u4")])


def ghi_mo_hinh(b, n_feat, path):
    nut = np.zeros(len(b["cot"]), NUT)                     # một nút 16 byte liền nhau (khớp nut_t trong mo_hinh.h)
    for k in ("val", "cot", "thieu", "trai", "phai"):
        nut[k] = b[k]
    with open(path, "wb") as f:
        f.write(b"MH02" + struct.pack("<HHII", n_feat, b["n_class"], len(b["goc"]), len(b["cot"])))
        f.write(b["base"].tobytes() + b["goc"].tobytes() + nut.tobytes())


def csi_tho(d, board="RX1"):
    """host_time, CSI thô int8 (số gói, 104) của một RX – đúng thứ tự byte trong csi_hex."""
    c = pd.read_csv(d / "csi.csv", dtype={"csi_hex": str})
    c = c[(c["board"] == board) & (c["len"] == 104)]
    raw = np.frombuffer(bytes.fromhex("".join(c["csi_hex"])), dtype=np.int8).reshape(len(c), -1)
    return c["host_time"].to_numpy(float), raw


def main():
    ap = argparse.ArgumentParser(description="Xuất mô hình động tác một board + dữ liệu đối chiếu cho ESP32.")
    ap.add_argument("--data", default=str(ROOT / "data" / "sim2"))
    ap.add_argument("--out", default=str(ROOT / "firmware" / "thu_mo_hinh" / "main"))
    ap.add_argument("--giu-lai", type=int, default=2, help="số buổi cuối không dùng để train (lấy window đối chiếu)")
    ap.add_argument("--so-window", type=int, default=40)
    args = ap.parse_args()
    dd, out = Path(args.data), Path(args.out)
    files = sorted((dd / "features_action").glob("*.csv"))
    train_f, test_f = files[:-args.giu_lai], files[-args.giu_lai:]
    cols = ["rx1_" + c for c in COT]
    df = pd.concat([pd.read_csv(f) for f in train_f], ignore_index=True)
    df = df[df["valid"] == 1].dropna(subset=cols)
    classes, y = np.unique(df["action"].to_numpy(str), return_inverse=True)
    model = T.build_models(cols, len(classes), 0, {"max_depth": 5})["xgb"]
    T.fit(model, df[cols].to_numpy(float), y, True)
    b = bang_nut(model)
    print(f"Train {len(df)} window từ {len(train_f)} buổi; lớp {list(classes)}; {len(b['goc'])} cây, {len(b['cot'])} nút")

    # window đối chiếu: mọi window động tác của các buổi giữ lại + một ít NONE, tính lại đặc trưng từ CSI thô
    rows, rng = [], np.random.default_rng(0)
    for f in test_f:
        t, raw = csi_tho(dd / "raw" / f.stem)
        w = pd.read_csv(f)
        w = w[w["valid"] == 1]
        chon = pd.concat([w[w["action"] != "NONE"], w[w["action"] == "NONE"].sample(frac=1, random_state=0)])
        for _, r in chon.iterrows():
            i, j = np.searchsorted(t, [r["win_start"], r["win_end"]])
            rows.append((raw[i:j], r["action"]))
    rows = rows[:args.so_window]
    amp = lambda r: np.hypot(r[:, 1::2].astype(float), r[:, 0::2].astype(float))   # byte chẵn ảo, lẻ thực
    X = np.array([[F.robust_features(amp(r))[c] for c in COT] for r, _ in rows])
    P = model.predict_proba(X)
    Pb = du_doan_bang(b, X)
    assert np.abs(Pb - P).max() < 1e-4, f"bảng nút lệch mô hình: {np.abs(Pb - P).max()}"
    print(f"Tự kiểm bảng nút: lệch xác suất lớn nhất {np.abs(Pb - P).max():.2e}")

    out.mkdir(parents=True, exist_ok=True)
    ghi_mo_hinh(b, len(COT), out / "mo_hinh.bin")
    with open(out / "du_lieu_thu.bin", "wb") as fh:
        fh.write(b"DL01" + struct.pack("<HHHH", len(rows), 52, len(COT), len(classes)))
        for (r, _), x, p in zip(rows, X, P):
            fh.write(struct.pack("<HH", len(r), 0) + x.astype(np.float32).tobytes() + p.astype(np.float32).tobytes())
            fh.write(r.astype(np.int8).tobytes())
    (out / "lop.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")
    nhan = pd.Series([a for _, a in rows]).value_counts().to_dict()
    print(f"Ghi {out / 'mo_hinh.bin'} ({(out / 'mo_hinh.bin').stat().st_size / 1e6:.2f} MB), "
          f"{out / 'du_lieu_thu.bin'} ({len(rows)} window: {nhan})")


if __name__ == "__main__":
    main()
