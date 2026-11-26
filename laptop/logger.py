#!/usr/bin/env python3
"""Thu dữ liệu từ ESP32-C3 #2 (CSI) và #3 (Probe Request), ghi nhãn bằng phím.

Làm theo "Dac_ta_dinh_dang_du_lieu.md" phiên bản 0.3 (1 TX phát ESP-NOW, nhiều RX, nhãn động tác).

Ví dụ:
    python logger.py --list-ports
    python logger.py --rx-port /dev/ttyACM0 --rx-port /dev/ttyACM1 --snf-port /dev/ttyACM2 --tag phongA
    python logger.py --simulate --tag thu --duration 60     # chạy thử, không cần board (giả 2 RX + sniffer)

Phím khi đang thu:
    Trạng thái: E phòng trống   A (hoặc W) đi lại   S ngồi/nằm yên   D nằm bất động sau ngã   B thở bất thường
                N người ở phòng bên   P tạm dừng (bỏ đoạn này)
    Động tác (bấm lúc bắt đầu): F ngã   G ngồi xuống   U đứng dậy   L nằm xuống   C cúi nhặt
    + / = có người vào   - có người ra   R nhịp thở đáp án (gõ số rồi Enter)   T ghi chú   Q kết thúc
"""
import argparse
import csv
import hashlib
import json
import math
import os
import queue
import random
import re
import secrets
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

SPEC_VERSION = "0.3"
HERE = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = HERE.parent / "data"
CONFIG_PATH = HERE / "logger_config.json"

# Các trường của từng loại dòng ESP32 gửi lên (mục 3 của đặc tả)
FIELDS = {
    "BOOT": ["board", "fw", "mac_sta", "mac_ap", "channel"],
    "CSI": ["seq", "t_us", "rx_seq", "src_mac", "rssi", "noise_floor", "channel", "sig_mode", "cwb",
            "first_word_invalid", "len", "csi_hex"],
    "PRB": ["seq", "t_us", "src_mac", "rssi", "channel"],
    "STAT": ["t_us", "board", "n_rx", "n_filtered", "n_queue_drop", "channel"],
}
INT_FIELDS = {
    "BOOT": {"channel"},
    "CSI": {"seq", "t_us", "rx_seq", "rssi", "noise_floor", "channel", "sig_mode", "cwb", "first_word_invalid", "len"},
    "PRB": {"seq", "t_us", "rssi", "channel"},
    "STAT": {"t_us", "n_rx", "n_filtered", "n_queue_drop", "channel"},
}
MAC_FIELDS = {"BOOT": {"mac_sta", "mac_ap"}, "CSI": {"src_mac"}, "PRB": {"src_mac"}}
BOARDS = {"TX", "RX1", "RX2", "RX3", "SNF"}

# Cột của các file trong data/raw/<session_id>/ (mục 4 của đặc tả)
FILES = {
    "boot": ["host_time"] + FIELDS["BOOT"],
    "csi": ["host_time", "board"] + FIELDS["CSI"],             # v0.3: mọi RX ghi chung, cột board
    "probe": ["host_time", "seq", "t_us", "mac_hash", "local_admin", "rssi", "channel", "excluded"],
    "stat": ["host_time"] + FIELDS["STAT"],
    "labels": ["host_time", "event", "value"],
}

from nhan import KEYMAP, PRESENCE  # noqa: E402  (phím ghi nhãn, mục 4.4 của đặc tả)

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
HEX_RE = re.compile(r"^[0-9a-fA-F]*$")


# --------------------------------------------------------------------------- phân tích dòng
class BadLine(ValueError):
    pass


def parse_line(line):
    """Trả về (loại, dict) cho dòng hợp lệ, None cho dòng không thuộc đặc tả; BadLine nếu sai định dạng."""
    parts = line.strip().split(",")
    kind = parts[0]
    if kind not in FIELDS:
        return None
    names = FIELDS[kind]
    values = parts[1:]
    if len(values) != len(names):
        raise BadLine(f"{kind}: cần {len(names)} trường, nhận {len(values)}")
    rec = {}
    for name, v in zip(names, values):
        if name in INT_FIELDS[kind]:
            try:
                rec[name] = int(v)
            except ValueError:
                raise BadLine(f"{kind}.{name} không phải số nguyên: {v!r}")
        elif name in MAC_FIELDS.get(kind, ()):
            v = v.lower()
            if not (MAC_RE.match(v) or (kind == "BOOT" and v == "-")):
                raise BadLine(f"{kind}.{name} không phải MAC: {v!r}")
            rec[name] = v
        else:
            rec[name] = v
    if kind in ("BOOT", "STAT") and rec["board"] not in BOARDS:
        raise BadLine(f"{kind}.board không hợp lệ: {rec['board']!r}")
    if kind == "CSI":
        h = rec["csi_hex"]
        if not HEX_RE.match(h) or len(h) != 2 * rec["len"]:
            raise BadLine(f"CSI: len = {rec['len']} nên csi_hex phải dài {2 * rec['len']} ký tự hex, "
                          f"nhận {len(h)}")
        rec["csi_hex"] = h.lower()
    return kind, rec


def mac_hash(salt, mac):
    return hashlib.sha256((salt + mac).encode()).hexdigest()[:12]


def is_local_admin(mac):
    return int(mac[:2], 16) & 0x02 != 0


# --------------------------------------------------------------------------- cấu hình cục bộ
def load_config(path=None):
    """salt và MAC loại trừ thêm (vd. laptop demo). File này không đưa lên Git."""
    path = path or CONFIG_PATH
    if not path.exists():
        cfg = {"salt": secrets.token_hex(16), "exclude_macs": []}
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"[i] Đã tạo {path.name} với salt ngẫu nhiên. Cả nhóm nên dùng chung file này; KHÔNG đưa lên Git.")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["exclude_macs"] = [m.lower() for m in cfg.get("exclude_macs", [])]
    return cfg


# --------------------------------------------------------------------------- ghi dữ liệu
class SessionLogger:
    def __init__(self, session_dir, salt, exclude_macs, meta, verbose=False):
        self.dir = Path(session_dir)
        self.dir.mkdir(parents=True, exist_ok=False)
        self.salt = salt
        self.exclude = set(exclude_macs)
        self.meta = meta
        self.verbose = verbose
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.start_time = time.time()
        self.counts = {k: 0 for k in FIELDS}
        self.lost = {}              # (nguồn, loại) -> số dòng mất theo seq
        self.last_seq = {}
        self.bad_lines = 0
        self.other_lines = 0
        self.fw = {}
        self.board_of = {}          # nguồn (cổng) -> tên board lấy từ dòng BOOT
        self.last_stat = {}         # board -> bản ghi STAT gần nhất
        self.label = None
        self.people = 0
        self.n_labels = 0
        self.write_meta()
        self.writer = threading.Thread(target=self._write_loop, daemon=True)
        self.writer.start()

    # ---- nhận dòng từ các nguồn (gọi từ nhiều luồng)
    def on_line(self, line, source):
        host_time = time.time()
        try:
            parsed = parse_line(line)
        except BadLine as e:
            with self.lock:
                self.bad_lines += 1
            if self.verbose:
                print(f"\n[{source}] dòng sai định dạng: {e}")
            return
        if parsed is None:
            with self.lock:
                self.other_lines += 1
            if self.verbose and line.strip():
                print(f"\n[{source}] {line.rstrip()}")
            return
        kind, rec = parsed
        with self.lock:
            self.counts[kind] += 1
            if "seq" in rec:
                key = (source, kind)
                last = self.last_seq.get(key)
                if last is not None and rec["seq"] > last + 1:
                    self.lost[key] = self.lost.get(key, 0) + rec["seq"] - last - 1
                self.last_seq[key] = rec["seq"]   # seq nhỏ hơn = board vừa khởi động lại
            if kind == "BOOT":
                self.fw[rec["board"]] = rec["fw"]
                self.board_of[source] = rec["board"]
                for m in (rec["mac_sta"], rec["mac_ap"]):
                    if m != "-":
                        self.exclude.add(m)
            elif kind == "STAT":
                self.last_stat[rec["board"]] = rec
            elif kind == "PRB":
                mac = rec.pop("src_mac")
                rec = {"seq": rec["seq"], "t_us": rec["t_us"], "mac_hash": mac_hash(self.salt, mac),
                       "local_admin": int(is_local_admin(mac)), "rssi": rec["rssi"], "channel": rec["channel"],
                       "excluded": int(mac in self.exclude)}
            if kind == "CSI":                       # chưa nhận BOOT thì tạm lấy tên nguồn (RX1, RX2 theo thứ tự cổng)
                rec["board"] = self.board_of.get(source, source.replace("SIM-", ""))
        name = {"BOOT": "boot", "CSI": "csi", "PRB": "probe", "STAT": "stat"}[kind]
        self.q.put((name, [host_time] + [rec[c] for c in FILES[name][1:]]))

    # ---- nhãn từ bàn phím
    def add_label(self, event, value):
        t = time.time()
        with self.lock:
            self.n_labels += 1
            if event == "STATE":
                self.label = value
            elif event == "COUNT":
                self.people = max(0, self.people + int(value))
        self.q.put(("labels", [t, event, value]))

    # ---- luồng ghi file
    def _write_loop(self):
        files, writers = {}, {}
        for name, header in FILES.items():
            f = open(self.dir / f"{name}.csv", "w", newline="", encoding="utf-8")
            w = csv.writer(f)
            w.writerow(header)
            files[name], writers[name] = f, w
        last_flush = time.time()
        while not (self.stop.is_set() and self.q.empty()):
            try:
                name, row = self.q.get(timeout=0.2)
                if isinstance(row[0], float):
                    row[0] = f"{row[0]:.4f}"
                writers[name].writerow(row)
            except queue.Empty:
                pass
            if time.time() - last_flush >= 1.0:
                for f in files.values():
                    f.flush()
                last_flush = time.time()
        for f in files.values():
            f.close()

    def write_meta(self, final=False):
        meta = dict(self.meta)
        meta["fw"] = dict(self.fw)
        meta["spec_version"] = SPEC_VERSION
        if final:
            with self.lock:
                meta["stats"] = {
                    "duration_s": round(time.time() - self.start_time, 1),
                    "lines": dict(self.counts),
                    "lost_by_seq": {f"{s}/{k}": n for (s, k), n in self.lost.items()},
                    "bad_lines": self.bad_lines,
                    "label_events": self.n_labels,
                }
        tmp = self.dir / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.dir / "meta.json")

    def close(self):
        self.stop.set()
        self.writer.join()
        self.write_meta(final=True)

    # ---- dòng trạng thái
    def snapshot(self):
        with self.lock:
            return {"counts": dict(self.counts), "lost": sum(self.lost.values()), "bad": self.bad_lines,
                    "label": self.label, "people": self.people, "stat": dict(self.last_stat)}


# --------------------------------------------------------------------------- nguồn dữ liệu
class SerialSource(threading.Thread):
    """Đọc từng dòng từ một cổng USB; tự mở lại nếu board bị rút hoặc khởi động lại."""

    def __init__(self, name, port, baud, on_line, stop):
        super().__init__(daemon=True)
        self.name_, self.port, self.baud, self.on_line, self.stop = name, port, baud, on_line, stop

    def run(self):
        import serial  # chỉ cần khi dùng board thật
        while not self.stop.is_set():
            try:
                with serial.Serial(self.port, self.baud, timeout=0.5) as s:
                    print(f"\n[{self.name_}] đã mở {self.port}")
                    # Bỏ 0,5 s đầu: bộ đệm USB của board còn dòng cũ ghi lúc chưa ai đọc (seq nhảy, bị tính là mất)
                    het = time.time() + 0.5
                    while time.time() < het and not self.stop.is_set():
                        s.read(s.in_waiting or 1)
                    buf = b""
                    while not self.stop.is_set():
                        buf += s.read(s.in_waiting or 1)
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            self.on_line(raw.decode("utf-8", errors="replace").rstrip("\r"), self.name_)
            except (serial.SerialException, OSError) as e:
                if self.stop.is_set():
                    break
                print(f"\n[{self.name_}] lỗi cổng {self.port}: {e}. Thử lại sau 2 giây...")
                self.stop.wait(2)


class SimSource(threading.Thread):
    """Sinh dữ liệu giả đúng định dạng đặc tả, để chạy thử khi chưa có firmware."""

    TX_MAC = "1a:00:00:00:00:00"
    PHONES = ["9a:31:87:22:fd:08", "2a:15:c1:57:16:d8", "3c:28:6d:11:22:33", "da:a1:19:44:55:66"]

    def __init__(self, board, on_line, stop, get_label):
        super().__init__(daemon=True)
        self.board, self.on_line, self.stop, self.get_label = board, on_line, stop, get_label
        self.name_ = "SIM-" + board
        self.t0 = time.time()

    def t_us(self):
        return int((time.time() - self.t0) * 1e6)

    def emit(self, line):
        self.on_line(line, self.name_)

    def run(self):
        (self._run_rx if self.board == "RX" else self._run_snf)()

    def _run_rx(self):
        """Giả 2 RX nhận cùng gói ESP-NOW của TX: cùng rx_seq, seq riêng từng board, 52 sóng mang con (len 104).
        Muốn dữ liệu giống thật hơn (người, té ngã, nhịp thở) thì dùng mo_phong.py / mo_phong_ui.py."""
        boards = ("RX1", "RX2")
        rate, rx_seq, next_t, next_stat, next_boot = 100, random.randrange(4096), time.time(), time.time() + 1, 0
        seq, n_sec = dict.fromkeys(boards, 0), dict.fromkeys(boards, 0)
        phase = {b: [random.uniform(0, 6.28) for _ in range(52)] for b in boards}
        while not self.stop.is_set():
            now = time.time()
            if now >= next_boot:
                for i, b in enumerate(boards):
                    self.on_line(f"BOOT,{b},0.3-sim,64:e8:33:01:02:0{i + 3},{self.TX_MAC},6", "SIM-" + b)
                next_boot = now + 30
            if now >= next_stat:
                for b in boards:
                    self.on_line(f"STAT,{self.t_us()},{b},{n_sec[b]},{random.randint(0, 3)},0,6", "SIM-" + b)
                    n_sec[b] = 0
                next_stat += 1
            if now >= next_t:
                rx_seq = (rx_seq + 1) % 4096
                moving = PRESENCE.get(self.get_label()) == 1
                for b in boards:
                    if random.random() < 0.005:       # mất trên không: board này không nhận gói
                        continue
                    seq[b] += 1
                    if random.random() < 0.002:       # mất trên USB: seq nhảy
                        seq[b] += 1
                    raw = bytearray()
                    for k in range(52):
                        a = 15 + 5 * math.sin(k / 7) + random.gauss(0, 4 if moving else 1)
                        ph = phase[b][k] + random.gauss(0, 0.3 if moving else 0.05)
                        raw += bytes([int(a * math.sin(ph)) & 0xFF, int(a * math.cos(ph)) & 0xFF])
                    rssi = int(-42 + random.gauss(0, 3 if moving else 0.7))
                    self.on_line(f"CSI,{seq[b]},{self.t_us()},{rx_seq},{self.TX_MAC},{rssi},-95,6,0,0,0,104,"
                                 f"{raw.hex()}", "SIM-" + b)
                    n_sec[b] += 1
                next_t += 1 / rate
            self.stop.wait(max(0.0, min(next_t, next_stat) - time.time()))

    def _run_snf(self):
        seq, n_sec, ch, next_hop, next_stat, next_boot = 0, 0, 1, time.time() + 3, time.time() + 1, 0
        while not self.stop.is_set():
            now = time.time()
            if now >= next_boot:
                self.emit("BOOT,SNF,0.3-sim,64:e8:33:05:06:07,-,1")
                next_boot = now + 30
            if now >= next_hop:
                ch, next_hop = ch % 13 + 1, now + 3
            if now >= next_stat:
                self.emit(f"STAT,{self.t_us()},SNF,{n_sec},{random.randint(0, 20)},0,{ch}")
                n_sec, next_stat = 0, next_stat + 1
            for mac in self.PHONES:
                if random.random() < 0.004:
                    seq += 1
                    self.emit(f"PRB,{seq},{self.t_us()},{mac},{random.randint(-80, -50)},{ch}")
                    n_sec += 1
            if random.random() < 0.0005:              # board RX gửi probe khi kết nối lại -> phải bị loại trừ
                seq += 1
                self.emit(f"PRB,{seq},{self.t_us()},64:e8:33:01:02:03,-45,{ch}")
            self.stop.wait(0.05)


# --------------------------------------------------------------------------- bàn phím
class Keyboard:
    """Đọc từng phím không cần Enter (Linux/macOS dùng termios, Windows dùng msvcrt)."""

    def __init__(self):
        self.enabled = sys.stdin.isatty()
        self.win = os.name == "nt"
        self.old = None

    def __enter__(self):
        if self.enabled and not self.win:
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *exc):
        self.restore()

    def restore(self):
        if self.old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)

    def resume(self):
        if self.enabled and not self.win:
            import tty
            tty.setcbreak(sys.stdin.fileno())

    def get_key(self, timeout):
        if not self.enabled:
            time.sleep(timeout)
            return None
        if self.win:
            import msvcrt
            end = time.time() + timeout
            while time.time() < end:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(0.02)
            return None
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else None


# --------------------------------------------------------------------------- chương trình chính
def list_ports():
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        print("Chưa cài pyserial: pip install pyserial")
        return
    ports = list(lp.comports())
    if not ports:
        print("Không thấy cổng nào. Kiểm tra cáp USB (cáp phải truyền được dữ liệu).")
    for p in ports:
        print(f"{p.device:15s} {p.description}  [{p.hwid}]")
    print("ESP32-C3 dùng USB Serial/JTAG thường hiện là 'USB JTAG/serial debug unit' (VID:PID 303A:1001).")


def status_line(s, elapsed, prev_counts, dt):
    c = s["counts"]
    rate = lambda k: (c[k] - prev_counts.get(k, 0)) / dt if dt > 0 else 0.0
    rxs, snf = [s["stat"][b] for b in sorted(s["stat"]) if b.startswith("RX")], s["stat"].get("SNF")
    hh, rem = divmod(int(elapsed), 3600)
    mm, ss = divmod(rem, 60)
    label = s["label"] or "CHƯA CÓ NHÃN"
    parts = [f"{hh:02d}:{mm:02d}:{ss:02d}", f"Nhãn: {label}", f"Người: {s['people']}",
             f"CSI {rate('CSI'):5.1f}/s", f"PRB {rate('PRB'):4.1f}/s", f"mất {s['lost']}"]
    if rxs:
        parts.append("RX " + "/".join(f"{r['n_rx']}" for r in rxs) + "/s, drop " + "/".join(str(r["n_queue_drop"]) for r in rxs))
    if snf:
        parts.append(f"SNF kênh {snf['channel']}")
    if s["bad"]:
        parts.append(f"sai {s['bad']}")
    return " | ".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Thu dữ liệu CSI + Probe Request và ghi nhãn (đặc tả v0.3).")
    ap.add_argument("--list-ports", action="store_true", help="liệt kê cổng USB rồi thoát")
    ap.add_argument("--rx-port", action="append", default=[],
                    help="cổng của một RX (vd. /dev/ttyACM0, COM5); lặp lại cho RX1, RX2, ...")
    ap.add_argument("--snf-port", help="cổng của sniffer")
    ap.add_argument("--baud", type=int, default=921600, help="USB Serial/JTAG bỏ qua giá trị này")
    ap.add_argument("--simulate", action="store_true", help="dùng dữ liệu giả thay cho board thật")
    ap.add_argument("--tag", help="tên ngắn của buổi thu, vd. phongA")
    ap.add_argument("--room", default="", help="mô tả phòng")
    ap.add_argument("--distance", type=float, default=None, help="khoảng cách TX-RX (m)")
    ap.add_argument("--channel", type=int, default=None, help="kênh TX phát ESP-NOW")
    ap.add_argument("--members", default="", help="người có mặt, cách nhau bằng dấu phẩy")
    ap.add_argument("--notes", default="")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--duration", type=float, default=None, help="tự dừng sau số giây này")
    ap.add_argument("--verbose", action="store_true", help="in cả các dòng log khác của ESP32")
    args = ap.parse_args()

    if args.list_ports:
        list_ports()
        return
    if not (args.rx_port or args.snf_port or args.simulate):
        ap.error("cần --rx-port và/hoặc --snf-port, hoặc --simulate")
    if not args.tag or not re.match(r"^[A-Za-z0-9-]+$", args.tag):
        ap.error("--tag bắt buộc, chỉ gồm chữ không dấu, số và dấu '-' (vd. phongA)")

    cfg = load_config()
    session_id = datetime.now().strftime("%Y%m%d_%H%M") + "_" + args.tag
    meta = {"session_id": session_id, "room": args.room, "tx_rx_distance_m": args.distance,
            "channel": args.channel, "members": [m.strip() for m in args.members.split(",") if m.strip()],
            "simulated": args.simulate,
            "ports": {**{f"RX{i + 1}": p for i, p in enumerate(args.rx_port)}, "SNF": args.snf_port},
            "notes": args.notes}
    log = SessionLogger(Path(args.data_dir) / "raw" / session_id, cfg["salt"], cfg["exclude_macs"], meta,
                        args.verbose)

    stop = threading.Event()
    sources = []
    if args.simulate:
        sources += [SimSource("RX", log.on_line, stop, lambda: log.label),
                    SimSource("SNF", log.on_line, stop, lambda: log.label)]
    for i, port in enumerate(args.rx_port):
        sources.append(SerialSource(f"RX{i + 1}", port, args.baud, log.on_line, stop))
    if args.snf_port:
        sources.append(SerialSource("SNF", args.snf_port, args.baud, log.on_line, stop))

    print(f"Buổi thu: {session_id}\nThư mục: {log.dir}")
    print("Trạng thái: E trống | A/W đi lại | S yên | D nằm sau ngã | B thở bất thường | N phòng bên | P tạm dừng\n"
          "Động tác:   F ngã | G ngồi xuống | U đứng dậy | L nằm xuống | C cúi nhặt\n"
          "Khác:       +/- người vào/ra | R nhịp thở đáp án | T ghi chú | Q kết thúc")
    for s in sources:
        s.start()

    start = time.time()
    prev, prev_t = {}, start
    try:
        with Keyboard() as kb:
            if not kb.enabled:
                print("[i] Không có bàn phím (stdin không phải terminal): không ghi nhãn được.")
            while True:
                key = kb.get_key(0.2)
                if key:
                    k = key.lower()
                    if k == "q":
                        break
                    if k in KEYMAP:
                        ev, val = KEYMAP[k]
                        log.add_label(ev, val)
                        print(f"\n→ {ev} {val}")
                    elif k == "t":
                        kb.restore()
                        note = input("\nGhi chú: ").replace(",", ";")
                        kb.resume()
                        if note:
                            log.add_label("NOTE", note)
                    elif k == "r":
                        kb.restore()
                        val = input("\nNhịp thở đáp án (nhịp/phút, 0 = nín thở): ").strip().replace(",", ".")
                        kb.resume()
                        try:
                            bpm = float(val)
                        except ValueError:
                            bpm = -1
                        if 0 <= bpm <= 60:
                            log.add_label("RATE", f"{bpm:g}")
                        else:
                            print(f"[!] '{val}' không phải số nhịp hợp lệ (0–60), bỏ qua.")
                now = time.time()
                if now - prev_t >= 2:
                    snap = log.snapshot()
                    line = status_line(snap, now - start, prev, now - prev_t)
                    width = max(20, shutil.get_terminal_size((100, 20)).columns - 1)
                    sys.stdout.write("\r" + line[:width].ljust(width))
                    sys.stdout.flush()
                    prev, prev_t = snap["counts"], now
                if args.duration and now - start >= args.duration:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for s in sources:
            s.join(timeout=2)
        log.close()
        snap = log.snapshot()
        print(f"\n\nĐã lưu {log.dir}")
        print(f"Số dòng: {snap['counts']} | mất theo seq: {snap['lost']} | sai định dạng: {snap['bad']}")
        if snap["label"] is None:
            print("[!] Buổi thu này chưa có nhãn STATE nào.")


if __name__ == "__main__":
    main()
