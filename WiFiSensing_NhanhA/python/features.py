#!/usr/bin/env python3
"""Module DÙNG CHUNG cho nhánh A: đọc dữ liệu thô, tiền xử lý, trích đặc trưng.
Bám "Đặc tả định dạng dữ liệu" v0.1 – mục 3.2 (dòng CSI), 4 (file buổi thu), 5 (file đặc trưng).

Dùng như thư viện (logger, live, train, mô phỏng đều gọi vào đây), hoặc chạy trực tiếp:
  py python/features.py                                  # mọi buổi trong data/raw → data/features
  py python/features.py --raw data_mo_phong/raw --out data_mo_phong/features
  py python/features.py --session 20261112_1430_phongA   # chỉ một buổi
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ thông số (mục 7)
SPEC_VERSION = "0.1"
CODE_VERSION = "nhanh_a-1.0"
WINDOW_S = 6.0
EXPECTED_RATE_HZ = 100
VALID_RATIO = 0.7
MIN_SAMPLES = int(WINDOW_S * EXPECTED_RATE_HZ * VALID_RATIO)          # 420
# LLTF 64 sóng mang con, thứ tự trong buf của ESP: chỉ số 0..31 = sóng mang 0..+31, 32..63 = -32..-1.
# Bỏ 0 (DC), 1 (bị first_word_invalid), 27..37 (dải bảo vệ, luôn rỗng). Chốt lại sau khi xem dữ liệu C3 thật.
SUBCARRIERS_KEPT = list(range(2, 27)) + list(range(38, 64))           # 51 sóng mang con
CSI_LEN = 128
WAVELET = "db4"
DENOISE_LEVEL = 4            # 6 s ≈ 600 mẫu → db4 tách tối đa 6 mức; dùng 4
MAD_KIND = "median"          # median absolute deviation – CHỐT LẠI theo bài báo 2

# ------------------------------------------------------------------ nhãn (mục 4.4)
STATE_KEYS = {"e": "EMPTY", "w": "WALK", "s": "STATIC", "m": "MULTI", "n": "NEIGHBOR", "p": "PAUSE"}
BINARY_LABEL = {"WALK": 1, "STATIC": 1, "MULTI": 1, "EMPTY": 0, "NEIGHBOR": 0}   # PAUSE: bỏ

CSI_FIELDS = ["seq", "t_us", "src_mac", "rssi", "noise_floor", "channel", "sig_mode", "cwb",
              "first_word_invalid", "len", "csi_hex"]
STAT_FIELDS = ["t_us", "board", "n_rx", "n_filtered", "n_queue_drop", "channel"]
BOOT_FIELDS = ["board", "fw", "mac_sta", "mac_ap", "channel"]
PRB_FIELDS = ["seq", "t_us", "src_mac", "rssi", "channel"]
LINE_FIELDS = {"CSI": CSI_FIELDS, "STAT": STAT_FIELDS, "BOOT": BOOT_FIELDS, "PRB": PRB_FIELDS}


# ------------------------------------------------------------------ đọc dòng từ ESP32 (mục 3)
def parse_line(line):
    """Dòng văn bản từ ESP → (loại, dict) hoặc None nếu không phải dòng hợp lệ (laptop bỏ qua)."""
    parts = line.strip().split(",")
    kind = parts[0]
    fields = LINE_FIELDS.get(kind)
    if fields is None or len(parts) != len(fields) + 1:
        return None
    d = dict(zip(fields, parts[1:]))
    if kind == "CSI":
        try:
            n = int(d["len"])
        except ValueError:
            return None
        if len(d["csi_hex"]) != 2 * n:
            return None
    return kind, d


def hex_to_iq(hex_list, n_bytes=CSI_LEN):
    """Danh sách chuỗi hex (mỗi chuỗi n_bytes byte) → mảng int8 (n, n_bytes)."""
    raw = bytes.fromhex("".join(hex_list))
    return np.frombuffer(raw, dtype=np.int8).reshape(-1, n_bytes)


def iq_to_amplitude(iq):
    """int8 (n,128) xếp [ảo, thực, ảo, thực, ...] → biên độ (n,64) = √(thực² + ảo²)."""
    iq = iq.astype(np.float32)
    im, re = iq[:, 0::2], iq[:, 1::2]
    return np.sqrt(im * im + re * re)


# ------------------------------------------------------------------ đọc file buổi thu (mục 4)
def load_csi(session_dir):
    """csi.csv → (host_time, rssi, amp(n,64), df). Chỉ giữ dòng len = 128."""
    df = pd.read_csv(os.path.join(session_dir, "csi.csv"),
                     dtype={"csi_hex": str, "src_mac": str})
    df = df[(df["len"] == CSI_LEN) & (df["csi_hex"].str.len() == 2 * CSI_LEN)]
    df = df.sort_values("host_time").reset_index(drop=True)
    amp = iq_to_amplitude(hex_to_iq(df["csi_hex"].tolist())) if len(df) else np.zeros((0, 64))
    return df["host_time"].to_numpy(float), df["rssi"].to_numpy(float), amp, df


def load_label_segments(session_dir, t_end):
    """labels.csv → danh sách (bắt_đầu, kết_thúc, STATE). Một nhãn có hiệu lực tới lần bấm STATE kế tiếp."""
    path = os.path.join(session_dir, "labels.csv")
    if not os.path.exists(path):
        return []
    lab = pd.read_csv(path, dtype={"value": str})
    lab = lab[lab["event"] == "STATE"].sort_values("host_time")
    t = lab["host_time"].tolist() + [t_end]
    return [(t[i], t[i + 1], v) for i, v in enumerate(lab["value"].tolist()) if t[i + 1] > t[i]]


def read_meta(session_dir):
    path = os.path.join(session_dir, "meta.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"session_id": os.path.basename(os.path.normpath(session_dir))}


# ------------------------------------------------------------------ tiền xử lý + đặc trưng
def denoise_db4(a):
    """Khử nhiễu wavelet db4, ngưỡng mềm universal, cho từng cột (sóng mang con)."""
    import pywt
    n = a.shape[0]
    level = min(DENOISE_LEVEL, pywt.dwt_max_level(n, pywt.Wavelet(WAVELET).dec_len))
    if level < 1:
        return a
    c = pywt.wavedec(a, WAVELET, level=level, axis=0)
    sigma = np.median(np.abs(c[-1]), axis=0) / 0.6745
    thr = sigma * np.sqrt(2 * np.log(n))
    c = [c[0]] + [np.sign(d) * np.maximum(np.abs(d) - thr, 0) for d in c[1:]]
    return pywt.waverec(c, WAVELET, axis=0)[:n]


def four_stats(x):
    """x (n, k) → Var, MAD, Range, IQR theo từng cột – đều đo ĐỘ DAO ĐỘNG, không đo mức tín hiệu."""
    var = x.var(axis=0)
    if MAD_KIND == "median":
        mad = np.median(np.abs(x - np.median(x, axis=0)), axis=0)
    else:
        mad = np.mean(np.abs(x - x.mean(axis=0)), axis=0)
    rng = x.max(axis=0) - x.min(axis=0)
    q75, q25 = np.percentile(x, [75, 25], axis=0)
    return var, mad, rng, q75 - q25


def feature_columns():
    """Tên cột đặc trưng đúng mục 5: rssi_*, rồi csi_<đặc trưng>_<chỉ số gốc 2 chữ số>."""
    cols = ["rssi_var", "rssi_mad", "rssi_range", "rssi_iqr"]
    for name in ("var", "mad", "range", "iqr"):
        cols += [f"csi_{name}_{k:02d}" for k in SUBCARRIERS_KEPT]
    return cols


def window_features(amp, rssi):
    """Một window: amp (n,64), rssi (n,) → vector theo đúng thứ tự feature_columns()."""
    a = denoise_db4(amp[:, SUBCARRIERS_KEPT].astype(np.float64))
    r = four_stats(np.asarray(rssi, float)[:, None])
    c = four_stats(a)
    return np.concatenate([np.array([v[0] for v in r]), *c])


# ------------------------------------------------------------------ một buổi thu → file đặc trưng
def process_session(session_dir, out_dir):
    meta = read_meta(session_dir)
    sid = meta.get("session_id") or os.path.basename(os.path.normpath(session_dir))
    t, rssi, amp, _ = load_csi(session_dir)
    cols = feature_columns()
    rows = []
    if len(t):
        segs = load_label_segments(session_dir, t[-1])
        for s, e, state in segs:
            if state not in BINARY_LABEL:            # PAUSE hoặc nhãn lạ → bỏ
                continue
            # Window xếp từ đầu mỗi đoạn nhãn → không window nào cắt ngang chỗ đổi nhãn.
            # Phần dư cuối đoạn (< 6 s) chính là window cắt ngang → bỏ.
            for w in range(int((e - s) // WINDOW_S)):
                ws, we = s + w * WINDOW_S, s + (w + 1) * WINDOW_S
                i0, i1 = np.searchsorted(t, ws), np.searchsorted(t, we)
                n = i1 - i0
                row = {"session_id": sid, "win_start": round(ws, 4), "win_end": round(we, 4),
                       "n_samples": n, "valid": int(n >= MIN_SAMPLES),
                       "label_detail": state, "label": BINARY_LABEL[state]}
                feats = window_features(amp[i0:i1], rssi[i0:i1]) if n >= 16 else np.full(len(cols), np.nan)
                row.update(zip(cols, feats))
                rows.append(row)
    df = pd.DataFrame(rows, columns=["session_id", "win_start", "win_end", "n_samples", "valid",
                                     "label_detail", "label"] + cols)
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, f"{sid}.csv"), index=False, float_format="%.6g")
    return sid, df


def write_feature_meta(out_dir):
    meta = {
        "spec_version": SPEC_VERSION,
        "window_s": WINDOW_S,
        "expected_rate_hz": EXPECTED_RATE_HZ,
        "valid_ratio": VALID_RATIO,
        "subcarriers_kept": SUBCARRIERS_KEPT,
        "denoise": {"wavelet": WAVELET, "level": DENOISE_LEVEL, "threshold": "universal, soft"},
        "mad": MAD_KIND,
        "rssi_features": "raw RSSI, không khử nhiễu",
        "windowing": "6 s không chồng lấn, xếp từ đầu mỗi đoạn nhãn STATE; bỏ PAUSE và phần dư cuối đoạn",
        "code_version": CODE_VERSION,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "feature_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/features")
    ap.add_argument("--session", help="chỉ xử lý một session_id")
    a = ap.parse_args()
    dirs = sorted(d for d in glob.glob(os.path.join(a.raw, "*")) if os.path.isdir(d))
    if a.session:
        dirs = [d for d in dirs if os.path.basename(d) == a.session]
    if not dirs:
        sys.exit(f"Không thấy buổi thu nào trong {a.raw}")
    write_feature_meta(a.out)
    for d in dirs:
        sid, df = process_session(d, a.out)
        if df.empty:
            print(f"  {sid}: 0 window (thiếu csi.csv hoặc labels.csv?)")
            continue
        v = df[df.valid == 1]
        by = v.groupby("label_detail").size().to_dict()
        print(f"  {sid}: {len(df)} window, {len(v)} hợp lệ  {by}")
    print(f"\nĐã ghi vào {a.out}/ (kèm feature_meta.json)")


if __name__ == "__main__":
    main()
