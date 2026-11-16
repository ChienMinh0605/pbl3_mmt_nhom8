"""Tính đặc trưng cho MỘT window CSI/RSSI – BẢN TẠM để dashboard chạy được.

Tiên sẽ viết bản chính (`features.py`, có khử nhiễu wavelet db4). Khi đó dashboard chuyển sang gọi bản chính,
để đặc trưng lúc chạy thời gian thực tính GIỐNG HỆT lúc train. Bản tạm này chỉ cần:
- tên cột đúng mục 5 của đặc tả: rssi_var, rssi_mad, rssi_range, rssi_iqr, csi_<đặc trưng>_<kk>;
- cách đọc csi_hex đúng mục 3.2: mỗi sóng mang con 2 byte int8, byte đầu là phần ảo, byte sau là phần thực.
"""
import numpy as np

STATS = ("var", "mad", "range", "iqr")
# Mặc định: bỏ sóng mang con 0, 1 và 27–37 (rỗng/lỗi), còn 51. Danh sách thật lấy từ feature_meta.json.
DEFAULT_KEPT = [k for k in range(64) if k not in (0, 1) and not 27 <= k <= 37]


def csi_amplitude(csi_hex, first_word_invalid=False, n_sub=64):
    """csi_hex -> mảng biên độ của n_sub sóng mang con đầu (phần LLTF)."""
    raw = np.frombuffer(bytes.fromhex(csi_hex), dtype=np.int8).astype(float)
    imag, real = raw[0::2][:n_sub], raw[1::2][:n_sub]
    amp = np.hypot(real, imag)
    if first_word_invalid:
        amp[:2] = np.nan          # 4 byte đầu = 2 sóng mang con đầu không hợp lệ
    return amp


def spread_stats(x, axis=0):
    """4 đặc trưng độ phân tán theo bài báo 2: phương sai, MAD (độ lệch tuyệt đối trung bình), max − min, IQR."""
    x = np.asarray(x, dtype=float)
    mean = np.nanmean(x, axis=axis, keepdims=True)
    q75, q25 = np.nanpercentile(x, [75, 25], axis=axis)
    return {
        "var": np.nanvar(x, axis=axis),
        "mad": np.nanmean(np.abs(x - mean), axis=axis),
        "range": np.nanmax(x, axis=axis) - np.nanmin(x, axis=axis),
        "iqr": q75 - q25,
    }


def window_features(amps, rssi, kept=None):
    """amps: ma trận (số mẫu × 64) biên độ; rssi: mảng RSSI. Trả về dict {tên cột: giá trị}."""
    kept = DEFAULT_KEPT if kept is None else kept
    out = {}
    r = spread_stats(rssi)
    for s in STATS:
        out[f"rssi_{s}"] = float(r[s])
    c = spread_stats(np.asarray(amps)[:, kept], axis=0)
    for s in STATS:
        for k, v in zip(kept, c[s]):
            out[f"csi_{s}_{k:02d}"] = float(v)
    return out
