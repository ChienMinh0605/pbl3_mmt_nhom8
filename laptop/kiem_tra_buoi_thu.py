#!/usr/bin/env python3
"""Kiểm tra chất lượng một buổi thu do logger.py (hoặc mo_phong.py) ghi ra – đặc tả v0.3, vẫn đọc được v0.2.

Ví dụ:
    python kiem_tra_buoi_thu.py                    # buổi thu mới nhất trong ../data/raw
    python kiem_tra_buoi_thu.py ../data/raw/20261112_1430_phongA
    python kiem_tra_buoi_thu.py --save             # lưu thêm report.txt vào thư mục buổi thu

Báo cáo gồm: tốc độ CSI thực tế của từng RX, số dòng mất, số window hợp lệ, độ khớp rx_seq giữa các RX,
Probe Request theo kênh và theo thiết bị, các đoạn nhãn, động tác, nhịp thở đáp án. Cuối báo cáo là danh sách
ĐẠT / CẢNH BÁO / LỖI.
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_RAW = HERE.parent / "data" / "raw"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nhan import ACTIONS, PRESENCE as BINARY, SHORT_OK  # noqa: E402


# --------------------------------------------------------------------------- đọc file
def read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def seq_losses(rows):
    """Tổng số dòng mất theo seq, và số lần seq quay về (board khởi động lại)."""
    lost, resets, last = 0, 0, None
    for r in rows:
        s = int(r["seq"])
        if last is not None:
            if s > last + 1:
                lost += s - last - 1
            elif s <= last:
                resets += 1
        last = s
    return lost, resets


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def fmt_dur(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# --------------------------------------------------------------------------- báo cáo
class Report:
    def __init__(self):
        self.lines = []
        self.verdicts = []          # (mức, nội dung)

    def h(self, title):
        self.lines += ["", title, "-" * len(title)]

    def p(self, text=""):
        self.lines.append(text)

    def ok(self, msg):
        self.verdicts.append(("ĐẠT", msg))

    def warn(self, msg):
        self.verdicts.append(("CẢNH BÁO", msg))

    def bad(self, msg):
        self.verdicts.append(("LỖI", msg))

    def text(self):
        out = list(self.lines)
        out += ["", "KẾT LUẬN", "--------"]
        order = {"LỖI": 0, "CẢNH BÁO": 1, "ĐẠT": 2}
        for level, msg in sorted(self.verdicts, key=lambda v: order[v[0]]):
            out.append(f"[{level:^8}] {msg}")
        return "\n".join(out)


def label_segments(labels, t_end):
    """Các đoạn nhãn STATE: (nhãn, bắt đầu, kết thúc). Nhãn có hiệu lực tới lần bấm STATE tiếp theo."""
    states = sorted((float(r["host_time"]), r["value"]) for r in labels if r["event"] == "STATE")
    segs = []
    for i, (t, v) in enumerate(states):
        t2 = states[i + 1][0] if i + 1 < len(states) else t_end
        if t2 > t:
            segs.append((v, t, t2))
    return segs


def check_csi(rep, d, csi, stat, args, t0, t1):
    rep.h("1. CSI")
    if not csi:
        rep.p("Không có dòng CSI nào.")
        rep.bad("Không có dữ liệu CSI (RX chưa nối, sai cổng, hoặc firmware chưa gửi dòng CSI).")
        return
    boards = defaultdict(list)                     # v0.2 không có cột board → coi là một RX
    for r in csi:
        boards[r.get("board") or "RX"].append(r)
    rep.p(f"Các RX: {', '.join(f'{b} ({len(v)} dòng)' for b, v in sorted(boards.items()))}")
    for b, rows in sorted(boards.items()):
        rep.p("")
        rep.p(f"[{b}]")
        check_rx(rep, b, rows, stat, args, t0, t1)
    if len(boards) > 1 and "rx_seq" in csi[0]:
        # rx_seq 12 bit quay vòng sau 4096 gói (~41 s ở 100 gói/s) → ghép theo (rx_seq, khung 20 s của host_time)
        seen = {b: {(r["rx_seq"], int(float(r["host_time"]) // 20)) for r in rows} for b, rows in boards.items()}
        common = set.intersection(*seen.values())
        share = len(common) / max(len(v) for v in seen.values())
        rep.p("")
        rep.p(f"Gói nhận được ở mọi RX (cùng rx_seq, cùng lúc): {pct(len(common), max(len(v) for v in seen.values())):.1f}%")
        if share >= 0.9:
            rep.ok("Các RX nhận cùng gói của TX (rx_seq khớp) → ghép RX1 với RX2 được.")
        else:
            rep.warn(f"rx_seq chỉ khớp {share:.0%} giữa các RX: kiểm tra các RX có cùng lọc theo MAC của TX, cùng kênh.")


def check_rx(rep, b, csi, stat, args, t0, t1):
    times = [float(r["host_time"]) for r in csi]
    span = times[-1] - times[0]
    rate = (len(csi) - 1) / span if span > 0 else 0.0
    lost, resets = seq_losses(csi)

    # tốc độ theo từng giây, bỏ giây đầu và cuối (thường không trọn)
    per_sec = Counter(int(t - times[0]) for t in times)
    secs = [per_sec.get(i, 0) for i in range(1, int(span))]
    rep.p(f"Số dòng: {len(csi)} trong {fmt_dur(span)}  →  trung bình {rate:.1f} mẫu/giây "
          f"(mục tiêu {args.rate:g})")
    if secs:
        q = statistics.quantiles(secs, n=20) if len(secs) >= 20 else [min(secs)]
        rep.p(f"Theo từng giây: thấp nhất {min(secs)}, 5% thấp nhất ≤ {q[0]:.0f}, trung vị "
              f"{statistics.median(secs):.0f}, cao nhất {max(secs)}")
    gaps = [b - a for a, b in zip(times, times[1:])]
    big = [g for g in gaps if g > 0.5]
    rep.p(f"Khoảng trống > 0,5 giây giữa hai mẫu: {len(big)} lần" + (f", dài nhất {max(big):.1f} giây" if big else ""))
    rep.p(f"Mất theo seq: {lost} dòng ({pct(lost, len(csi) + lost):.2f}%)"
          + (f"; board khởi động lại {resets} lần" if resets else ""))

    drops = sum(int(r["n_queue_drop"]) for r in stat if r["board"] == b)
    filt = sum(int(r["n_filtered"]) for r in stat if r["board"] == b)
    if any(r["board"] == b for r in stat):
        rep.p(f"Theo dòng STAT của {b}: mất do queue đầy {drops}, khung bị lọc vì sai MAC {filt}")

    macs = Counter(r["src_mac"] for r in csi)
    lens = Counter(int(r["len"]) for r in csi)
    modes = Counter(r["sig_mode"] for r in csi)
    fwi = sum(r["first_word_invalid"] == "1" for r in csi)
    rssi = [int(r["rssi"]) for r in csi]
    rep.p(f"MAC nguồn: {dict(macs)}")
    rep.p(f"Độ dài CSI (len): {dict(lens)}   sig_mode: {dict(modes)}   first_word_invalid: {pct(fwi, len(csi)):.0f}%")
    rep.p(f"RSSI: trung bình {statistics.mean(rssi):.1f} dBm, độ lệch chuẩn {statistics.pstdev(rssi):.1f}")

    # window hợp lệ theo đặc tả
    need = args.valid_ratio * args.rate * args.window
    n_win = int((t1 - t0) // args.window)
    counts = Counter(int((t - t0) // args.window) for t in times)
    valid = sum(1 for w in range(n_win) if counts.get(w, 0) >= need)
    rep.p(f"Window {args.window:g} giây: {valid}/{n_win} hợp lệ (cần ≥ {need:.0f} mẫu mỗi window)")

    if rate >= 0.9 * args.rate:
        rep.ok(f"{b}: tốc độ CSI {rate:.1f} mẫu/giây.")
    elif rate >= args.valid_ratio * args.rate:
        rep.warn(f"{b}: tốc độ CSI {rate:.1f} mẫu/giây, thấp hơn mục tiêu {args.rate:g}. Kiểm tra tốc độ phát của TX, kênh.")
    else:
        rep.bad(f"{b}: tốc độ CSI chỉ {rate:.1f} mẫu/giây: phần lớn window sẽ không hợp lệ.")
    if pct(lost, len(csi) + lost) > 1 or drops:
        rep.warn(f"{b}: mất {lost} dòng theo seq, {drops} bản ghi mất do queue đầy. Cân nhắc gửi dạng nhị phân.")
    else:
        rep.ok(f"{b}: gần như không mất dòng.")
    if resets:
        rep.warn(f"{b} khởi động lại {resets} lần trong buổi thu (mất nguồn, lỗi firmware?).")
    if n_win and valid / n_win < 0.95:
        rep.warn(f"{b}: chỉ {pct(valid, n_win):.0f}% window hợp lệ.")
    if len(macs) > 1:
        rep.bad(f"{b}: CSI đến từ {len(macs)} MAC khác nhau: firmware chưa lọc theo MAC của TX.")
    if len(lens) > 1 or not set(lens) <= {104, 128}:
        rep.warn(f"{b}: độ dài CSI {sorted(lens)} – dự kiến 104 hoặc 128 byte và không đổi: kiểm tra wifi_csi_config_t.")
    if len(modes) > 1:
        rep.warn(f"{b}: trộn nhiều sig_mode {dict(modes)}: các mẫu có thể khác nhau về số sóng mang con.")
    if big:
        rep.warn(f"{b}: có {len(big)} khoảng trống > 0,5 giây (nhiễu chen ngang, mất kết nối hoặc board khởi động lại?).")


def check_probe(rep, probe, stat, t0, t1):
    rep.h("2. Probe Request (sniffer)")
    if not probe:
        rep.p("Không có dòng PRB nào.")
        if any(r["board"] == "SNF" for r in stat):
            rep.warn("Sniffer có chạy (có dòng STAT) nhưng không bắt được Probe Request nào.")
        else:
            rep.warn("Không có dữ liệu từ sniffer (chưa nối hoặc chưa có firmware).")
        return
    minutes = max(1e-9, (t1 - t0) / 60)
    excl = [r for r in probe if r["excluded"] == "1"]
    keep = [r for r in probe if r["excluded"] != "1"]
    rep.p(f"Số dòng: {len(probe)} ({len(probe) / minutes:.1f} mỗi phút); bị loại trừ (board của nhóm): {len(excl)}")
    ch = Counter(int(r["channel"]) for r in probe)
    rep.p("Theo kênh: " + "  ".join(f"{c}:{ch.get(c, 0)}" for c in range(1, 14)))
    stat_ch = sorted({int(r["channel"]) for r in stat if r["board"] == "SNF"})
    if stat_ch:
        rep.p(f"Kênh sniffer đã nghe (theo STAT): {stat_ch}")

    dev = defaultdict(list)
    for r in keep:
        dev[r["mac_hash"]].append((float(r["host_time"]), r["local_admin"] == "1"))
    n_local = sum(1 for v in dev.values() if v[0][1])
    rep.p(f"Số nguồn (mac_hash) khác nhau: {len(dev)}, trong đó {n_local} có bit U/L = 1 (thường là MAC ngẫu nhiên)")
    rep.p("")
    rep.p(f"{'mac_hash':14s} {'U/L':>3s} {'probe':>6s} {'số phút có probe':>17s} {'thấy lần đầu':>13s} {'lần cuối':>9s}")
    for h, v in sorted(dev.items(), key=lambda kv: -len(kv[1]))[:12]:
        mins = {int((t - t0) // 60) for t, _ in v}
        rep.p(f"{h:14s} {int(v[0][1]):>3d} {len(v):>6d} {len(mins):>8d}/{int(minutes) + 1:<8d} "
              f"{fmt_dur(v[0][0] - t0):>13s} {fmt_dur(v[-1][0] - t0):>9s}")
    if len(dev) > 12:
        rep.p(f"... và {len(dev) - 12} nguồn khác")

    # một vòng nhảy kênh 1→13 mất 39 giây; chỉ xét khi buổi thu đủ hai vòng
    missing = [c for c in range(1, 14) if c not in stat_ch] if stat_ch and t1 - t0 >= 80 else []
    if missing:
        rep.warn(f"Sniffer chưa nghe các kênh {missing}: kiểm tra vòng nhảy kênh 1→13.")
    if t1 - t0 >= 600:
        rep.ok(f"Bắt được Probe Request từ {len(dev)} nguồn.")
    else:
        rep.warn(f"Buổi thu chỉ dài {fmt_dur(t1 - t0)}; nhánh thiết bị cần từ 30 phút để đánh giá.")


def check_labels(rep, labels, args, t0, t1):
    rep.h("3. Nhãn")
    segs = label_segments(labels, t1)
    if not segs:
        rep.p("Không có nhãn STATE nào.")
        rep.bad("Buổi thu không có nhãn: không dùng để train được (chỉ dùng để kiểm tra tốc độ).")
        return
    first = segs[0][1]
    rep.p(f"Đoạn đầu chưa có nhãn: {fmt_dur(max(0, first - t0))}")
    rep.p("")
    rep.p(f"{'bắt đầu':>8s} {'dài':>7s}  nhãn")
    for v, a, b in segs:
        rep.p(f"{fmt_dur(a - t0):>8s} {fmt_dur(b - a):>7s}  {v}")

    total = defaultdict(float)
    wins = defaultdict(int)
    for v, a, b in segs:
        total[v] += b - a
        wins[v] += int((b - a) // args.window)
    rep.p("")
    rep.p(f"{'nhãn':10s} {'tổng thời gian':>15s} {'số window':>10s}  nhị phân")
    for v in sorted(total, key=lambda k: -total[k]):
        rep.p(f"{v:10s} {fmt_dur(total[v]):>15s} {wins[v]:>10d}  {BINARY.get(v, 'bỏ')}")
    w0 = sum(n for v, n in wins.items() if BINARY.get(v) == 0)
    w1 = sum(n for v, n in wins.items() if BINARY.get(v) == 1)
    rep.p(f"Window dự kiến: Empty {w0}, Occupied {w1}")

    people, neg = 0, False
    for r in sorted(labels, key=lambda r: float(r["host_time"])):
        if r["event"] == "COUNT":
            people += int(r["value"])
            neg = neg or people < 0
    notes = [r for r in labels if r["event"] == "NOTE"]
    acts = sorted((float(r["host_time"]), r["value"]) for r in labels if r["event"] == "ACTION")
    rates = [r for r in labels if r["event"] == "RATE"]
    if acts:
        c = Counter(v for _, v in acts)
        rep.p("Động tác: " + ", ".join(f"{a} {c.get(a, 0)}" for a in ACTIONS))
    if rates:
        rep.p("Nhịp thở đáp án (RATE): " + ", ".join(f"{fmt_dur(float(r['host_time']) - t0)} → {r['value']}"
                                                    for r in rates[:12]) + (" …" if len(rates) > 12 else ""))
    downs = [t for t, v in ((float(r["host_time"]), r["value"]) for r in labels if r["event"] == "STATE") if v == "DOWN"]
    no_down = [t for t, v in acts if v == "FALL" and not any(0 <= d - t <= 10 for d in downs)]
    unknown = sorted({v for _, v in acts} - set(ACTIONS))
    rep.p(f"Sự kiện đếm người: {sum(r['event'] == 'COUNT' for r in labels)}, số người lúc kết thúc: {people}")
    for r in notes:
        rep.p(f"Ghi chú lúc {fmt_dur(float(r['host_time']) - t0)}: {r['value']}")

    if no_down:
        rep.warn(f"{len(no_down)} lần FALL không có DOWN trong 10 giây sau đó (quên bấm D?).")
    if unknown:
        rep.bad(f"Động tác lạ trong labels.csv: {unknown}")
    if first - t0 > 60:
        rep.warn(f"Bấm nhãn đầu tiên sau {fmt_dur(first - t0)}: đoạn đầu bị bỏ.")
    short = [(v, b - a) for v, a, b in segs if v not in SHORT_OK and b - a < 2 * args.window]
    if short:
        rep.warn(f"{len(short)} đoạn nhãn ngắn hơn {2 * args.window:g} giây (bấm nhầm?).")
    if w0 == 0 and w1 == 0:
        rep.bad("Không có window nào mang nhãn Empty hoặc Occupied (chỉ có PAUSE hoặc các đoạn quá ngắn).")
    elif w0 == 0 or w1 == 0:
        rep.warn(f"Buổi thu chỉ có lớp {'Occupied' if w0 == 0 else 'Empty'}.")
    else:
        rep.ok(f"Có đủ hai lớp: Empty {w0} window, Occupied {w1} window.")
    if neg and people >= 0:
        rep.warn("Số người đếm tay có lúc âm (bấm '-' trước '+').")
    if people > 0:
        rep.warn(f"Lúc kết thúc vẫn còn {people} người theo số đếm tay (quên bấm '-'?).")
    elif people < 0:
        rep.warn(f"Số người đếm tay lúc kết thúc là {people}: số lần bấm '-' nhiều hơn '+'.")


def main():
    ap = argparse.ArgumentParser(description="Kiểm tra chất lượng một buổi thu.")
    ap.add_argument("session", nargs="?", help="thư mục buổi thu (mặc định: buổi mới nhất trong data/raw)")
    ap.add_argument("--rate", type=float, default=100, help="tốc độ CSI mục tiêu (mẫu/giây)")
    ap.add_argument("--window", type=float, default=6, help="độ dài window (giây)")
    ap.add_argument("--valid-ratio", type=float, default=0.7, help="tỉ lệ mẫu tối thiểu để window hợp lệ")
    ap.add_argument("--save", action="store_true", help="lưu report.txt vào thư mục buổi thu")
    args = ap.parse_args()

    if args.session:
        d = Path(args.session)
    else:
        sessions = sorted(p for p in DEFAULT_RAW.glob("*") if p.is_dir()) if DEFAULT_RAW.exists() else []
        if not sessions:
            sys.exit(f"Không thấy buổi thu nào trong {DEFAULT_RAW}")
        d = sessions[-1]
    if not (d / "meta.json").exists():
        sys.exit(f"{d} không phải thư mục buổi thu (thiếu meta.json)")

    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    csi, probe = read_csv(d / "csi.csv"), read_csv(d / "probe.csv")
    stat, labels = read_csv(d / "stat.csv"), read_csv(d / "labels.csv")

    all_t = [fnum(r["host_time"]) for rows in (csi, probe, stat, labels) for r in rows]
    all_t = [t for t in all_t if t is not None]
    if not all_t:
        sys.exit("Buổi thu không có dữ liệu nào.")
    t0, t1 = min(all_t), max(all_t)

    rep = Report()
    rep.p(f"BÁO CÁO BUỔI THU {meta.get('session_id', d.name)}")
    rep.p(f"Thư mục: {d}")
    rep.p(f"Thời lượng: {fmt_dur(t1 - t0)}   phòng: {meta.get('room') or '-'}   kênh: {meta.get('channel') or '-'}   "
          f"TX-RX: {meta.get('tx_rx_distance_m') or '-'} m   firmware: {meta.get('fw') or '-'}")
    if meta.get("simulator", {}).get("engine") == "3d":
        rep.warn("Dữ liệu MÔ PHỎNG 3D (mo_phong.py): dùng để thử thuật toán, không thay cho dữ liệu thật khi đánh giá.")
    elif meta.get("simulated"):
        rep.warn("Dữ liệu GIẢ LẬP (--simulate): không dùng để train.")
    if "stats" not in meta:
        rep.warn("meta.json không có 'stats': logger bị ngắt giữa chừng (dữ liệu đã ghi vẫn dùng được).")

    check_csi(rep, d, csi, stat, args, t0, t1)
    check_probe(rep, probe, stat, t0, t1)
    check_labels(rep, labels, args, t0, t1)

    text = rep.text()
    print(text)
    if args.save:
        (d / "report.txt").write_text(text + "\n", encoding="utf-8")
        print(f"\nĐã lưu {d / 'report.txt'}")


if __name__ == "__main__":
    main()
