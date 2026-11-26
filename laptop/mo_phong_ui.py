#!/usr/bin/env python3
"""Công cụ mô phỏng 3D trên trình duyệt: chọn kịch bản, bấm Chạy, xem người di chuyển và CSI của RX1 / RX2;
khi cần thì lưu thành buổi thu (đặc tả v0.3) vào data/raw/.

    python mo_phong_ui.py                 # mở http://127.0.0.1:8502 bằng trình duyệt mặc định
    python mo_phong_ui.py --port 8600 --khong-mo

Chỉ dùng thư viện chuẩn + numpy (phần tính toán nằm ở mo_phong.py). Server chỉ nghe trên 127.0.0.1.
"""
import argparse
import base64
import json
import webbrowser
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

import mo_phong as sim
import nhip_tho

PAGE = Path(__file__).resolve().parent / "mo_phong_ui.html"
FPS = 25                       # khung gửi sang trình duyệt (trình duyệt tự nội suy lên 60 khung/giây)
HEAT_HZ = 10                   # bản đồ nhiệt sóng mang con
MAX_S = 20 * 60                # giới hạn độ dài một lần chạy
RATE = 100
NAMES = {"EMPTY": "Phòng trống", "NEIGHBOR": "Người ở phòng bên", "ACTIVE": "Đi lại", "STILL": "Yên",
         "DOWN": "Nằm sau ngã", "BREATH_ABN": "Thở bất thường", "FALL": "Ngã", "SIT_DOWN": "Ngồi xuống",
         "STAND_UP": "Đứng dậy", "LIE_DOWN": "Nằm xuống", "PICK_UP": "Cúi nhặt"}
PRESETS = {"mot-nguoi": "Một người – đủ động tác", "nhieu-nguoi": "Có khách vào / ra",
           "nga": "Nhiều lần ngã + động tác dễ nhầm", "phong-ben": "Người đi ở phòng bên",
           "bat-dong": "Yên lâu: nằm 4 phút, ngồi 7 phút"}


def params(req):
    """Kiểm tra dữ liệu gửi lên, trả về kịch bản và các tham số."""
    try:
        seed = int(req.get("seed", 0))
        noise = float(req.get("noise", 0.05))
        phut = float(req.get("phut", 5))
    except (TypeError, ValueError):
        raise ValueError("seed, nhiễu, số phút phải là số")
    if not 0 <= seed <= 10**6 or not 0 <= noise <= 0.2 or not 1 <= phut <= 20:
        raise ValueError("seed 0–1000000, nhiễu 0–0,2, số phút 1–20")
    kind = str(req.get("kich_ban", "mot-nguoi"))
    if kind == "tu-viet":
        plan = str(req.get("plan", "")).strip()
        if not plan or len(plan) > 4000:
            raise ValueError("kịch bản tự viết đang trống hoặc quá dài")
    elif kind == "ngau-nhien":
        plan = sim.random_plan(np.random.default_rng(seed), phut, guests=bool(req.get("co_khach")))
    elif kind in sim.KICH_BAN:
        plan = sim.KICH_BAN[kind]
    else:
        raise ValueError(f"không có kịch bản '{kind}'")
    total = sum(max(sim.ACTIONS[n]) if d is None else d for n, d, _ in sim.parse_plan(plan))
    if total > MAX_S:
        raise ValueError(f"kịch bản dài {total / 60:.1f} phút, tối đa {MAX_S // 60} phút")
    return Namespace(plan=plan, seed=seed, noise=noise, nguoi_bam=bool(req.get("nguoi_bam")), rate=RATE, nhieu=None)


def heat(im, re):
    """Biên độ từng sóng mang con, 10 lần/giây, so với 2 giây đầu, chuẩn hoá về 0–255 (thời gian × 52)."""
    a = np.hypot(im.astype(float), re.astype(float))
    step = RATE // HEAT_HZ
    a = a[:len(a) // step * step].reshape(-1, step, a.shape[1]).mean(axis=1)
    a = a / np.maximum(np.median(a[:2 * HEAT_HZ], axis=0), 1e-6)
    lo, hi = np.percentile(a, [2, 98])
    u8 = np.clip((a - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8)
    return base64.b64encode(u8.tobytes()).decode()


def breath_estimates(spans, rx, win=30.0, step=3.0):
    """Chạy thuật toán nhịp thở (nhip_tho.py) mỗi 3 s trong các đoạn ngồi / nằm yên, cửa sổ 30 s.
    Trả về [[giây cuối cửa sổ, nhịp/phút hoặc null, lý do]]."""
    amps = [np.hypot(im.astype(float), re.astype(float)) for im, re, _ in rx.values()]
    out = []
    for name, a, b in spans:
        if name not in sim.BREATHING:
            continue
        for end in np.arange(a + win, b + 1e-6, step):
            w = [x[int((end - win) * RATE):int(end * RATE)] for x in amps]
            bpm, _, why = nhip_tho.uoc_luong(w, RATE)
            out.append([round(float(end), 1), None if bpm is None else round(bpm, 1), why])
    return out


def run(req):
    p = params(req)
    t, S, labels, spans, rx = sim.compute(p.plan, p.seed, p.rate, p.noise, p.nguoi_bam)
    idx = np.arange(0, len(t), RATE // FPS)
    _, bpm = sim.per_sample(t, spans, labels)
    bits = lambda m: (m[idx].astype(int) * (1 << np.arange(m.shape[1]))).sum(axis=1).tolist()
    amp = {b: sim.mean_amp(im, re) for b, (im, re, _) in rx.items()}
    return {
        "plan": p.plan, "seed": p.seed, "fps": FPS, "heat_hz": HEAT_HZ, "duration": float(t[-1]),
        "geo": {"room": list(sim.ROOM), "area": list(sim.AREA), "neighbor": list(sim.NEIGHBOR_ROOM),
                "tx": sim.TX.tolist(), "rx": {b: v.tolist() for b, v in sim.RX.items()},
                "chair": sim.CHAIR.tolist(), "door": sim.DOOR.tolist(), "operator": sim.OPERATOR.tolist(),
                "furniture": [list(xyz[:2]) for xyz, _ in sim.objects_for(p.seed)],
                "height": sim.ROOM_H, "ant_z": sim.ANT_Z,
                "bounces": {b: [[q[:2].tolist() for q in pts] for _, _, pts, seq in sim.static_paths(v)    # dội 1 tường
                                if seq is not None and len(seq) == 1 and sim.PLANES[seq[0]][0] < 2]
                            for b, v in sim.RX.items()}},
        "x": np.round(S["x"][idx].T, 3).tolist(), "y": np.round(S["y"][idx].T, 3).tolist(),
        "h": np.round(S["h"][idx].T, 2).tolist(), "yaw": np.round(S["yaw"][idx].T, 2).tolist(),
        "present": bits(S["present"]), "behind": bits(S["behind"]),
        "count": (S["present"][idx, :3] & ~S["behind"][idx, :3]).sum(axis=1).tolist(),
        "bpm": np.nan_to_num(bpm[idx], nan=-1).tolist(),
        "amp": {b: np.round(v[idx], 4).tolist() for b, v in amp.items()},
        "heat": {b: heat(im, re) for b, (im, re, _) in rx.items()},
        "spans": [[n, round(a, 2), round(b, 2)] for n, a, b in spans],
        "notes": [[round(a, 2), v] for a, e, v in labels if e == "NOTE"],
        "interference": [list(x) for x in sim.interference_for(p.seed, len(t), RATE, p.nhieu)],
        "down_cu_dong": sim.down_cu_dong(p.plan, spans),
        "breath_est": breath_estimates(spans, rx),
    }


def save(req):
    p = params(req)
    tag = str(req.get("tag", "")).strip()
    if not tag or len(tag) > 40 or not all(c.isascii() and c.isalnum() or c == "-" for c in tag):
        raise ValueError("tên buổi chỉ gồm chữ không dấu, số và '-' (tối đa 40 ký tự)")
    t, S, labels, spans, rx = sim.compute(p.plan, p.seed, p.rate, p.noise, p.nguoi_bam)
    args = Namespace(**vars(p), tag=tag, data_dir=str(sim.ROOT / "data"), phat_lai=False)
    d = sim.write_session(args, t, rx, labels, spans)
    if req.get("hinh"):
        sim.save_figure(d, t, S, spans, rx)
    return {"thu_muc": str(d)}


def info():
    return {"presets": PRESETS, "plans": sim.KICH_BAN, "states": list(sim.STATES), "actions": sim.ACTIONS,
            "breathing": list(sim.BREATHING), "names": NAMES, "colors": sim.COLORS}


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def local_only(self):
        """Chặn trang web lạ gọi vào server qua tên miền trỏ về máy mình (DNS rebinding)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host in ("127.0.0.1", "localhost"):
            return True
        self.reply(403, {"loi": "chỉ mở từ 127.0.0.1"})
        return False

    def do_GET(self):
        if not self.local_only():
            return
        if self.path in ("/", "/index.html"):
            self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/info":
            self.reply(200, info())
        else:
            self.reply(404, {"loi": "không có"})

    def do_POST(self):
        if not self.local_only():
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            return self.reply(413, {"loi": "yêu cầu quá lớn"})
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(req, dict):
                raise ValueError("dữ liệu gửi lên phải là JSON object")
            if self.path == "/api/chay":
                self.reply(200, run(req))
            elif self.path == "/api/luu":
                self.reply(200, save(req))
            else:
                self.reply(404, {"loi": "không có"})
        except SystemExit as e:                                  # parse_plan / timeline báo kịch bản sai
            self.reply(400, {"loi": str(e.code).replace("--plan mục", "Bước").replace("--plan sai ở", "Sai ở")})
        except (ValueError, json.JSONDecodeError) as e:
            self.reply(400, {"loi": str(e)})

    def log_message(self, *_):
        pass


def main():
    ap = argparse.ArgumentParser(description="Giao diện mô phỏng 3D nhánh người (chạy trên trình duyệt).")
    ap.add_argument("--port", type=int, default=8502)
    ap.add_argument("--khong-mo", action="store_true", help="không tự mở trình duyệt")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Công cụ mô phỏng: {url}  (Ctrl+C để tắt)")
    if not args.khong_mo:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã tắt.")


if __name__ == "__main__":
    main()
