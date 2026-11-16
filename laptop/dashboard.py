"""Dashboard thời gian thực cho đề tài Wi-Fi Sensing (Nhóm 8) – phong cách shadcn/ui.

Chạy song song với logger.py:
    Terminal 1:  python logger.py --rx-port /dev/ttyACM0 --snf-port /dev/ttyACM1 --tag demo
                 (hoặc: python logger.py --simulate --tag demo)
    Terminal 2:  streamlit run dashboard.py      → mở http://localhost:8501
    (thư mục dữ liệu khác: streamlit run dashboard.py -- --data-dir /duong/dan/data)

Dashboard đọc phần mới của các file trong data/raw/<buổi thu>/ mỗi vài giây:
- Nhánh người: 6 giây CSI gần nhất → đặc trưng (dac_trung.py) → models/model_latest.joblib → Empty/Occupied.
  Chống nhấp nháy: trạng thái hiển thị chỉ đổi khi mô hình đoán khác liên tục ≥ 6 giây (bật/tắt ở thanh bên).
- Nhánh thiết bị: BẢN TẠM, đếm số nguồn (mac_hash) thấy trong 60 giây gần nhất. Sẽ thay bằng máy trạng thái
  Sherlock của Phúc.
"""
import argparse
import csv
import html
import json
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import altair as alt
import joblib
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dac_trung import DEFAULT_KEPT, csi_amplitude, window_features  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WINDOW_S, RATE, VALID_RATIO = 6.0, 100, 0.7
DEVICE_WINDOW_S = 60
HOLD_S = 6.0                 # chống nhấp nháy: phải đoán khác liên tục bao lâu mới đổi trạng thái
HISTORY_S = 1800
STALE_S = 5
OCCUPIED_LABELS = {"WALK": 1, "STATIC": 1, "MULTI": 1, "EMPTY": 0, "NEIGHBOR": 0}

# màu theo shadcn/ui: đen – xám (zinc) làm nền, đỏ nhạt (red) làm màu nhấn cho "có người"
INK, MUTED, BORDER, SOFT = "#18181b", "#71717a", "#e4e4e7", "#f4f4f5"
RED, RED_LIGHT, RED_SOFT, RED_BG, RED_TEXT = "#ef4444", "#f87171", "#fecaca", "#fef2f2", "#b91c1c"


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--model", default=str(ROOT / "models" / "model_latest.joblib"))
    args, _ = ap.parse_known_args(sys.argv[1:])
    return args


ARGS = parse_args()
RAW = Path(ARGS.data_dir) / "raw"


# --------------------------------------------------------------------------- đọc phần mới của file CSV
class Tail:
    """Mỗi lần gọi read() trả về các dòng mới (đã đủ dòng) kể từ lần trước."""

    def __init__(self, path, start_from_end_bytes=None):
        self.path, self.pos, self.header = Path(path), None, None
        self.start_from_end_bytes = start_from_end_bytes

    def read(self):
        if not self.path.exists():
            return []
        with open(self.path, "rb") as f:
            if self.header is None:
                first = f.readline()
                if not first.endswith(b"\n"):
                    return []
                self.header = next(csv.reader([first.decode("utf-8")]))
                self.pos = f.tell()
                size = self.path.stat().st_size
                if self.start_from_end_bytes and size - self.pos > self.start_from_end_bytes:
                    f.seek(size - self.start_from_end_bytes)
                    f.readline()                      # bỏ dòng bị cắt dở
                    self.pos = f.tell()
            f.seek(self.pos)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return []
        self.pos += end + 1
        lines = data[:end + 1].decode("utf-8", errors="replace").splitlines()
        return [dict(zip(self.header, row)) for row in csv.reader(lines) if len(row) == len(self.header)]


# --------------------------------------------------------------------------- trạng thái của một buổi thu
class Live:
    def __init__(self, session_dir):
        self.dir = Path(session_dir)
        self.meta = self._meta()
        self.kept = DEFAULT_KEPT
        self.csi = deque(maxlen=int(RATE * 30))          # 30 giây CSI gần nhất
        self.probe = deque()
        self.tails = {
            "csi": Tail(self.dir / "csi.csv", start_from_end_bytes=400_000),
            "probe": Tail(self.dir / "probe.csv"),
            "stat": Tail(self.dir / "stat.csv"),
            "labels": Tail(self.dir / "labels.csv"),
        }
        self.last_stat, self.label, self.people = {}, None, 0
        self.latest_t = None
        self.hist = deque()             # (t, xác suất, trạng thái thô, trạng thái hiển thị, nhãn, số thiết bị)
        self.events = deque(maxlen=60)  # (t, loại, nội dung)
        self.shown = None               # trạng thái đang hiển thị (True = có người)
        self.shown_since = None
        self.pending_since = None
        self.prev_devices = None
        self.stale_reported = False
        self.drops_seen = 0

    def _meta(self):
        try:
            return json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def event(self, t, kind, text):
        self.events.append((t, kind, text))

    def update(self):
        for r in self.tails["csi"].read():
            try:
                amp = csi_amplitude(r["csi_hex"], r["first_word_invalid"] == "1")
            except ValueError:
                continue
            self.csi.append((float(r["host_time"]), float(r["rssi"]), amp))
        for r in self.tails["probe"].read():
            if r["excluded"] != "1":
                self.probe.append((float(r["host_time"]), r["mac_hash"]))
        for r in self.tails["stat"].read():
            self.last_stat[r["board"]] = r
            if r["board"] == "RX" and int(r["n_queue_drop"]) > 0:
                self.drops_seen += int(r["n_queue_drop"])
                self.event(float(r["host_time"]), "Cảnh báo", f"#2 mất {r['n_queue_drop']} bản ghi vì queue đầy")
        for r in self.tails["labels"].read():
            t = float(r["host_time"])
            if r["event"] == "STATE":
                self.label = r["value"]
                self.event(t, "Nhãn", f"Bấm nhãn {r['value']}")
            elif r["event"] == "COUNT":
                self.people = max(0, self.people + int(r["value"]))
                self.event(t, "Đếm người", f"{'Có người vào' if r['value'] == '+1' else 'Có người ra'} · còn {self.people}")
            elif r["event"] == "NOTE":
                self.event(t, "Ghi chú", r["value"])
        times = ([self.csi[-1][0]] if self.csi else []) + ([self.probe[-1][0]] if self.probe else [])
        if times:
            self.latest_t = max(times)
        if self.latest_t:
            while self.probe and self.probe[0][0] < self.latest_t - HISTORY_S:
                self.probe.popleft()

    # ---- nhánh người
    def human(self, bundle):
        if not self.csi:
            return {"status": "Chưa có dữ liệu CSI"}
        t_end = self.csi[-1][0]
        win = [x for x in self.csi if x[0] > t_end - WINDOW_S]
        need = VALID_RATIO * RATE * WINDOW_S
        if len(win) < need:
            return {"status": f"Không đủ mẫu ({len(win)}/{need:.0f})", "n": len(win)}
        if bundle is None:
            return {"status": "Chưa có mô hình", "n": len(win)}
        feats = window_features(np.vstack([x[2] for x in win]), [x[1] for x in win], self.kept)
        cols = bundle["feature_columns"]
        missing = [c for c in cols if c not in feats]
        if missing:
            return {"status": f"Mô hình cần cột {missing[0]}", "n": len(win)}
        X = np.array([[feats[c] for c in cols]])
        if np.isnan(X).any():
            return {"status": "Đặc trưng bị trống", "n": len(win)}
        p = float(bundle["model"].predict_proba(X)[0, 1])
        return {"status": "ok", "proba": p, "raw": p >= 0.5, "n": len(win), "t": t_end}

    def apply_smoothing(self, h, enabled):
        """Cập nhật trạng thái hiển thị. Bật chống nhấp nháy: chỉ đổi khi đoán khác liên tục ≥ HOLD_S giây."""
        t, raw = h["t"], h["raw"]
        if self.shown is None:
            self.shown, self.shown_since = raw, t
            return
        if raw == self.shown:
            self.pending_since = None
            return
        if not enabled:
            change = True
        else:
            self.pending_since = self.pending_since or t
            change = t - self.pending_since >= HOLD_S
        if change:
            self.event(t, "Trạng thái", f"{state_name(self.shown)} → {state_name(raw)}")
            self.shown, self.shown_since, self.pending_since = raw, t, None

    # ---- nhánh thiết bị (BẢN TẠM)
    def devices(self):
        if not self.latest_t:
            return 0
        return len({h for t, h in self.probe if t > self.latest_t - DEVICE_WINDOW_S})


def state_name(occupied):
    return "Có người" if occupied else "Phòng trống"


def ago(sec):
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec} giây trước"
    if sec < 3600:
        return f"{sec // 60} phút trước"
    return f"{sec // 3600} giờ trước"


def clock(t):
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


@st.cache_resource
def load_model(path, mtime):
    try:
        return joblib.load(path)
    except Exception as e:                               # noqa: BLE001
        st.warning(f"Không đọc được mô hình {path}: {e}")
        return None


def list_sessions():
    if not RAW.exists():
        return []
    return sorted((p for p in RAW.iterdir() if p.is_dir()), reverse=True)


# --------------------------------------------------------------------------- giao diện: CSS kiểu shadcn
st.set_page_config(page_title="Wi-Fi Sensing – Nhóm 8", page_icon="📶", layout="wide")
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, [class*="st-"], .stMarkdown, .stApp, button, input {{ font-family: 'Inter', system-ui, sans-serif; }}
.stApp {{ background: #ffffff; }}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"], #MainMenu, footer {{ visibility: hidden; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1320px; }}
section[data-testid="stSidebar"] {{ background: #fafafa; border-right: 1px solid {BORDER}; }}
.card {{ background:#fff; border:1px solid {BORDER}; border-radius:14px; padding:20px 22px;
         box-shadow:0 1px 2px rgba(0,0,0,.05); color:{INK}; }}
.grid4 {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin:4px 0 18px; }}
@media (max-width: 1100px) {{ .grid4 {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
.k-top {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
.k-top > .muted {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.muted {{ color:{MUTED}; font-size:14px; }}
.k-val {{ font-size:26px; font-weight:600; letter-spacing:-0.02em; margin:8px 0 16px; line-height:1.15; }}
.k-main {{ font-size:14px; font-weight:500; }}
.badge {{ display:inline-flex; align-items:center; gap:6px; border:1px solid {BORDER}; border-radius:8px;
          padding:2px 8px; font-size:12px; font-weight:500; color:{INK}; white-space:nowrap; background:#fff; }}
.dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
.badge.red {{ background:{RED_BG}; border-color:{RED_SOFT}; color:{RED_TEXT}; }}
.card.hot {{ background:{RED_BG}; border-color:{RED_SOFT}; }}
.card.hot .k-val {{ color:{RED_TEXT}; }}
.hdr {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; gap:12px; flex-wrap:wrap; }}
.hdr h1 {{ font-size:24px; font-weight:600; letter-spacing:-0.02em; margin:0; padding:0; color:{INK}; }}
.ctitle {{ font-size:16px; font-weight:600; color:{INK}; margin:0; }}
.tbl {{ width:100%; border-collapse:collapse; font-size:14px; color:{INK}; }}
.tbl th {{ text-align:left; font-weight:500; color:{MUTED}; padding:8px 10px; border-bottom:1px solid {BORDER}; background:#fafafa; }}
.tbl td {{ padding:9px 10px; border-bottom:1px solid {SOFT}; vertical-align:middle; }}
.st-key-card_chart, .st-key-card_csi, .st-key-card_events {{ border:1px solid {BORDER} !important; border-radius:14px !important;
          box-shadow:0 1px 2px rgba(0,0,0,.05); padding:18px 20px !important; background:#fff; }}
.st-key-span {{ display:flex; justify-content:flex-end; }}
.side-brand {{ display:flex; align-items:center; gap:10px; font-weight:600; font-size:16px; color:{INK}; margin-bottom:6px; }}
.side-logo {{ width:28px; height:28px; border-radius:8px; background:{INK}; color:#fff; display:flex;
              align-items:center; justify-content:center; font-size:13px; font-weight:600; }}
</style>
""", unsafe_allow_html=True)


def badge(text, dot=None, red=False):
    d = f'<span class="dot" style="background:{dot}"></span>' if dot else ""
    return f'<span class="badge{" red" if red else ""}">{d}{html.escape(text)}</span>'


def kpi(title, value, tag, main, sub, hot=False):
    return (f'<div class="card{" hot" if hot else ""}"><div class="k-top"><span class="muted">{html.escape(title)}</span>{tag}</div>'
            f'<div class="k-val">{html.escape(value)}</div><div class="k-main">{html.escape(main)}</div>'
            f'<div class="muted" style="margin-top:2px">{html.escape(sub)}</div></div>')


def axis_cfg(chart):
    return (chart.configure_view(strokeWidth=0)
            .configure_axis(grid=True, gridColor=SOFT, domain=False, ticks=False, labelColor=MUTED,
                            labelFont="Inter", labelFontSize=11, titleColor=MUTED, titleFont="Inter",
                            titleFontWeight="normal", titleFontSize=11)
            .configure_legend(labelFont="Inter", labelColor=MUTED, titleColor=MUTED, orient="top",
                              titleFontWeight="normal"))


def segments(times, values):
    """Gộp các điểm liên tiếp cùng giá trị thành đoạn (bắt đầu, kết thúc, giá trị)."""
    out = []
    for i, (t, v) in enumerate(zip(times, values)):
        t2 = times[i + 1] if i + 1 < len(times) else t + 2
        if out and out[-1][2] == v and abs(out[-1][1] - t) < 10:
            out[-1][1] = t2
        else:
            out.append([t, t2, v])
    return out


# --------------------------------------------------------------------------- thanh bên
sessions = list_sessions()
with st.sidebar:
    st.markdown('<div class="side-brand"><div class="side-logo">W8</div>Wi-Fi Sensing</div>'
                f'<div class="muted" style="margin-bottom:18px">Nhóm 8 · PBL3 Mạng máy tính</div>',
                unsafe_allow_html=True)
    if not sessions:
        st.info(f"Chưa có buổi thu nào trong {RAW}. Chạy logger.py trước.")
        st.stop()
    st.markdown('<div class="muted" style="font-weight:500">Buổi thu</div>', unsafe_allow_html=True)
    follow = st.toggle("Tự theo dõi buổi mới nhất", value=True)
    names = [p.name for p in sessions]
    chosen = names[0] if follow else st.selectbox("Chọn buổi thu", names, label_visibility="collapsed")
    st.markdown('<div class="muted" style="font-weight:500;margin-top:14px">Hiển thị</div>', unsafe_allow_html=True)
    smooth = st.toggle("Chống nhấp nháy", value=True,
                       help=f"Chỉ đổi trạng thái khi mô hình đoán khác liên tục ít nhất {HOLD_S:g} giây.")
    refresh = st.slider("Cập nhật mỗi (giây)", 1, 10, 2)

    model_path = Path(ARGS.model)
    bundle = load_model(str(model_path), model_path.stat().st_mtime) if model_path.exists() else None
    st.markdown('<div class="muted" style="font-weight:500;margin-top:14px">Mô hình</div>', unsafe_allow_html=True)
    if bundle:
        cvm = bundle.get("cv_metrics", {})
        warn = badge("Dữ liệu giả", "#f59e0b") if bundle.get("simulated") else badge("Dữ liệu thật", "#22c55e")
        st.markdown(
            f'<div class="card" style="padding:14px 16px"><div class="k-top"><b>{html.escape(bundle["model_name"])}</b>'
            f'{warn}</div><div class="muted" style="margin-top:6px">{len(bundle["feature_columns"])} đặc trưng · '
            f'{html.escape(bundle["feature_set"])}<br>F1 theo buổi: {cvm.get("f1", 0):.3f}<br>'
            f'Tạo lúc {html.escape(bundle["created"])}</div></div>', unsafe_allow_html=True)
    else:
        st.error("Chưa có models/model_latest.joblib – chạy train.py")

if st.session_state.get("session") != chosen:
    st.session_state.session = chosen
    st.session_state.live = Live(RAW / chosen)


# --------------------------------------------------------------------------- nội dung chính
@st.fragment(run_every=refresh)
def panel():
    live: Live = st.session_state.live
    live.update()
    h = live.human(bundle)
    n_dev = live.devices()
    now = time.time()
    age = now - live.latest_t if live.latest_t else None

    if h.get("status") == "ok":
        live.apply_smoothing(h, smooth)
        if not live.hist or h["t"] > live.hist[-1][0]:
            live.hist.append((h["t"], h["proba"], h["raw"], live.shown, live.label, n_dev))
        while live.hist and live.hist[0][0] < h["t"] - HISTORY_S:
            live.hist.popleft()
    if live.prev_devices is not None and live.latest_t and (live.prev_devices == 0) != (n_dev == 0):
        live.event(live.latest_t, "Thiết bị", "Phát hiện thiết bị" if n_dev else "Không còn thiết bị")
    live.prev_devices = n_dev
    if age is not None and age > STALE_S and not live.stale_reported:
        live.event(now, "Cảnh báo", "Không có dữ liệu mới")
        live.stale_reported = True
    elif age is not None and age <= STALE_S:
        live.stale_reported = False

    # ---- tiêu đề
    meta = live.meta
    if age is None:
        live_badge = badge("Chưa có dữ liệu", "#a1a1aa")
    elif age > STALE_S:
        live_badge = badge(f"Mất dữ liệu · {ago(age)}", "#ef4444")
    else:
        live_badge = badge("Đang nhận dữ liệu", "#22c55e")
    sim_badge = badge("Dữ liệu giả lập", "#f59e0b") if meta.get("simulated") else ""
    st.markdown(
        f'<div class="hdr"><div><h1>Tổng quan</h1><div class="muted">Buổi thu {html.escape(meta.get("session_id", live.dir.name))}'
        f' · {html.escape(meta.get("room") or "chưa ghi phòng")}</div></div>'
        f'<div style="display:flex;gap:8px">{sim_badge}{live_badge}</div></div>', unsafe_allow_html=True)

    # ---- 4 thẻ số liệu
    if h.get("status") == "ok":
        occ = live.shown
        held = ago(h['t'] - live.shown_since).replace(' trước', '') if live.shown_since else "-"
        c1 = kpi("Trạng thái phòng", state_name(occ),
                 badge(f"{h['proba']:.0%}", RED if occ else "#22c55e", red=occ),
                 f"Xác suất có người {h['proba']:.0%}",
                 f"Ổn định {held} · nhãn đang ghi: {live.label or 'chưa có'}", hot=occ)
    else:
        c1 = kpi("Trạng thái phòng", "—", badge("chờ"), h["status"], f"Nhãn đang ghi: {live.label or 'chưa có'}")
    c2 = kpi("Thiết bị gần đây", str(n_dev), badge(f"{DEVICE_WINDOW_S} giây"),
             "Có thiết bị phát Probe Request" if n_dev else "Không thấy thiết bị",
             "Bản tạm · chờ máy trạng thái Sherlock")
    rx, snf = live.last_stat.get("RX"), live.last_stat.get("SNF")
    rate = int(rx["n_rx"]) if rx else None
    c3 = kpi("Tốc độ CSI", f"{rate} mẫu/s" if rate is not None else "—",
             badge(f"mất {live.drops_seen}", "#22c55e" if live.drops_seen == 0 else "#f59e0b"),
             f"Window {WINDOW_S:g} s: {h.get('n', 0)} mẫu", f"Cần ≥ {VALID_RATIO * RATE * WINDOW_S:.0f} mẫu để dự đoán")
    c4 = kpi("Sniffer", f"Kênh {snf['channel']}" if snf else "—", badge("1 → 13"),
             f"Dữ liệu mới nhất {ago(age)}" if age is not None else "Chưa có dữ liệu",
             f"Số người đếm tay: {live.people}")
    st.markdown(f'<div class="grid4">{c1}{c2}{c3}{c4}</div>', unsafe_allow_html=True)

    # ---- biểu đồ xác suất + dải thời gian
    with st.container(border=True, key="card_chart"):
        top_l, top_r = st.columns([1, 1], vertical_alignment="center")
        top_l.markdown('<p class="ctitle">Xác suất có người</p><div class="muted">Mô hình dự đoán so với nhãn '
                       'đang ghi trên logger</div>', unsafe_allow_html=True)
        span = top_r.segmented_control("Khoảng thời gian", ["5 phút", "10 phút", "30 phút"], default="10 phút",
                                       key="span", label_visibility="collapsed") or "10 phút"
        span_s = int(span.split()[0]) * 60
        hist = [x for x in live.hist if live.hist and x[0] >= live.hist[-1][0] - span_s]
        if len(hist) >= 2:
            df = pd.DataFrame({
                "time": [datetime.fromtimestamp(x[0]) for x in hist],
                "proba": [x[1] for x in hist],
                "truth": [OCCUPIED_LABELS.get(x[4]) for x in hist],
            })
            xdom = alt.Scale(domain=[df["time"].min().isoformat(), df["time"].max().isoformat()])
            base = alt.Chart(df).encode(x=alt.X("time:T", title=None, scale=xdom,
                                                axis=alt.Axis(format="%H:%M:%S", tickCount=6)))
            area = base.mark_area(
                line={"color": RED, "strokeWidth": 1.5}, interpolate="monotone",
                color=alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                                   stops=[alt.GradientStop(color="#ffffff", offset=0),
                                          alt.GradientStop(color=RED_SOFT, offset=1)]),
            ).encode(y=alt.Y("proba:Q", title=None, scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
                     tooltip=[alt.Tooltip("time:T", format="%H:%M:%S", title="Lúc"),
                              alt.Tooltip("proba:Q", format=".0%", title="Xác suất")])
            truth = base.mark_line(interpolate="step-after", strokeDash=[4, 4], color=INK, strokeWidth=1).encode(y="truth:Q")
            rule = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(color=RED_SOFT, strokeDash=[2, 2]).encode(y="y:Q")
            st.altair_chart(axis_cfg((area + truth + rule).properties(height=230)), use_container_width=True)

            rows = []
            times = [x[0] for x in hist]
            for name, vals in (("Dự đoán", [state_name(x[3]) for x in hist]),
                               ("Nhãn thật", [({1: "Có người", 0: "Phòng trống"}.get(OCCUPIED_LABELS.get(x[4]), "Chưa có nhãn"))
                                              for x in hist])):
                for a, b, v in segments(times, vals):
                    rows.append({"dòng": name, "từ": datetime.fromtimestamp(a), "đến": datetime.fromtimestamp(b), "trạng thái": v})
            band = alt.Chart(pd.DataFrame(rows)).mark_bar(cornerRadius=3).encode(
                x=alt.X("từ:T", title=None, axis=None, scale=xdom), x2="đến:T",
                y=alt.Y("dòng:N", title=None, sort=["Dự đoán", "Nhãn thật"],
                        axis=alt.Axis(grid=False, labelPadding=8, labelLimit=120, labelFontSize=12)),
                color=alt.Color("trạng thái:N", legend=None,
                                scale=alt.Scale(domain=["Có người", "Phòng trống", "Chưa có nhãn"],
                                                range=[RED_LIGHT, BORDER, "#fafafa"])),
                tooltip=["dòng", "trạng thái", alt.Tooltip("từ:T", format="%H:%M:%S"), alt.Tooltip("đến:T", format="%H:%M:%S")],
            ).properties(height=64)
            st.altair_chart(axis_cfg(band.configure_scale(bandPaddingInner=0.35)), use_container_width=True)
            st.markdown(
                f'<div class="muted" style="display:flex;gap:16px;font-size:12px;margin-top:-6px">'
                f'<span><span class="dot" style="background:{RED_LIGHT}"></span> Có người</span>'
                f'<span><span class="dot" style="background:{BORDER}"></span> Phòng trống</span>'
                f'<span><span style="display:inline-block;width:16px;border-top:1px dashed {INK};vertical-align:middle"></span>'
                f' Nhãn thật (biểu đồ trên)</span>'
                f'<span><span style="display:inline-block;width:16px;border-top:1.5px solid {RED};vertical-align:middle"></span>'
                f' Xác suất mô hình</span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="muted" style="padding:40px 0;text-align:center">Đang chờ dự đoán đầu tiên · '
                        f'{html.escape(h.get("status", ""))}</div>', unsafe_allow_html=True)

    # ---- hàng dưới: biên độ CSI + sự kiện
    left, right = st.columns([1, 1], gap="medium")
    with left:
        with st.container(border=True, key="card_csi"):
            st.markdown('<p class="ctitle">Biên độ CSI</p><div class="muted">Trung bình các sóng mang con · 30 giây gần nhất</div>',
                        unsafe_allow_html=True)
            if live.csi:
                pts = list(live.csi)[::2]
                df = pd.DataFrame({"time": [datetime.fromtimestamp(x[0]) for x in pts],
                                   "amp": [float(np.nanmean(x[2][live.kept])) for x in pts]})
                ch = alt.Chart(df).mark_line(color=RED_LIGHT, strokeWidth=1).encode(
                    x=alt.X("time:T", title=None, axis=alt.Axis(format="%H:%M:%S", tickCount=4)),
                    y=alt.Y("amp:Q", title=None, scale=alt.Scale(zero=False)))
                st.altair_chart(axis_cfg(ch.properties(height=210)), use_container_width=True)
            else:
                st.markdown('<div class="muted" style="padding:40px 0;text-align:center">Chưa có dữ liệu CSI</div>',
                            unsafe_allow_html=True)
    with right:
        with st.container(border=True, key="card_events"):
            st.markdown('<p class="ctitle">Sự kiện gần đây</p><div class="muted">Đổi trạng thái, nhãn, cảnh báo</div>',
                        unsafe_allow_html=True)
            evs = list(live.events)[-8:][::-1]
            if evs:
                body = "".join(
                    f'<tr><td class="muted" style="width:84px">{clock(t)}</td>'
                    f'<td style="width:110px">{badge(k, red=(k == "Trạng thái"))}</td>'
                    f'<td>{html.escape(v)}</td></tr>' for t, k, v in evs)
                st.markdown(f'<table class="tbl"><thead><tr><th>Lúc</th><th>Loại</th><th>Nội dung</th></tr></thead>'
                            f'<tbody>{body}</tbody></table>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="muted" style="padding:40px 0;text-align:center">Chưa có sự kiện nào</div>',
                            unsafe_allow_html=True)


panel()
