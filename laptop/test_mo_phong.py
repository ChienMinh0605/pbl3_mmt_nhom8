#!/usr/bin/env python3
"""Tự kiểm tra mô phỏng, giao diện, nhịp thở và luồng logger → features: python test_mo_phong.py."""
import contextlib
import csv
import io
import json
import tempfile
from pathlib import Path

import numpy as np

import mo_phong as sim


def read_csi(d, board):
    rows = [r for r in csv.DictReader(open(Path(d) / "csi.csv", encoding="utf-8")) if r["board"] == board]
    raw = np.array([np.frombuffer(bytes.fromhex(r["csi_hex"]), dtype=np.int8) for r in rows], dtype=float)
    amp = np.hypot(raw[:, 0::2], raw[:, 1::2])                     # byte chẵn = ảo, byte lẻ = thực
    return rows, np.array([float(r["host_time"]) for r in rows]), amp


def labels(d):
    return [(float(r["host_time"]), r["event"], r["value"])
            for r in csv.DictReader(open(Path(d) / "labels.csv", encoding="utf-8"))]


def test_file_format(tmp):
    d = sim.main(["--tag", "dinhdang", "--data-dir", tmp, "--seed", "1",
                  "--plan", "EMPTY:5,ACTIVE:10,+,ACTIVE:5,-,FALL,DOWN:10@15"])
    r1, _, a1 = read_csi(d, "RX1")
    r2, _, _ = read_csi(d, "RX2")
    assert a1.shape[1] == 52 and all(r["len"] == "104" and len(r["csi_hex"]) == 208 for r in r1)
    common = {r["rx_seq"] for r in r1} & {r["rx_seq"] for r in r2}
    assert len(common) > 0.98 * min(len(r1), len(r2)), "RX1 và RX2 phải có chung rx_seq cho cùng gói"
    seq = np.array([int(r["seq"]) for r in r1])
    assert np.all(np.diff(seq) >= 1), "seq phải tăng dần"
    ev = {(e, v) for _, e, v in labels(d)}
    for need in [("STATE", "EMPTY"), ("STATE", "ACTIVE"), ("ACTION", "FALL"), ("STATE", "DOWN"),
                 ("COUNT", "+1"), ("COUNT", "-1"), ("RATE", "15")]:
        assert need in ev, f"thiếu nhãn {need}"


def test_motion_vs_empty(tmp):
    d = sim.main(["--tag", "dodong", "--data-dir", tmp, "--seed", "2", "--plan", "EMPTY:20,ACTIVE:20"])
    _, ht, amp = read_csi(d, "RX1")
    t = ht - ht[0]
    var = lambda m: amp[m].std(axis=0).mean()
    # WiFall (ESP32-S3 thật): đi lại dao động ~0,18, nhiễu nền ~0,075 → gấp ~2,3 lần
    assert var(t > 21) > 1.5 * var(t < 19), "đi lại phải làm biên độ dao động mạnh hơn rõ so với phòng trống"


def breath_peak(amp, fs=100):
    """Thuật toán đơn giản: trừ trung bình trượt 4 s (bỏ lúc xê dịch tư thế), FFT, lấy sóng mang con có dải thở mạnh nhất."""
    k = 400
    x = amp - np.array([np.convolve(np.pad(c, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, "valid")
                        for c in amp.T]).T
    f = np.fft.rfftfreq(len(x), 1 / fs)
    spec = np.abs(np.fft.rfft(x, axis=0))
    band = (f > 0.15) & (f < 0.6)
    return f[band][spec[band, spec[band].sum(axis=0).argmax()].argmax()]


def test_breathing_peak(tmp):
    """Ngồi ở ghế thở 15 nhịp/phút: với nhiễu như ESP32 thật, thuật toán đơn giản phải đúng ít nhất nửa số lần."""
    ok = 0
    for seed in range(8):
        _, _, _, spans, rx = sim.compute("ACTIVE:8,SIT_DOWN,STILL:60@15", seed)
        a0 = int((next(a for n, a, _ in spans if n == "STILL") + 2) * 100)
        ok += any(abs(breath_peak(np.hypot(im[a0:].astype(float), re[a0:].astype(float))) - 0.25) < 0.035
                  for im, re, _ in rx.values())
    assert ok >= 4, f"chỉ đo đúng nhịp thở {ok}/8 lần"


def test_bad_plan():
    for plan in ("ACTIVE:10,DOWN:5", "STILL:10", "ACTIVE:5,SIT_DOWN,ACTIVE:5", "-", "WALK:10", "STILL:5@99"):
        try:
            sim.timeline(sim.parse_plan(plan), 100, np.random.default_rng(0))
        except SystemExit:
            continue
        raise AssertionError(f"kịch bản sai mà không báo lỗi: {plan}")


def test_random_plans():
    rng = np.random.default_rng(0)
    falls, sat, downs = 0, 0, []
    for k in range(40):
        plan = sim.random_plan(rng, 5, guests=k % 2 == 0)
        t, S, labels, _ = sim.timeline(sim.parse_plan(plan), 50, rng, operator=k % 3 == 0)   # không được báo lỗi
        assert 4.5 * 60 < t[-1] < 9 * 60, t[-1]
        falls += sum(1 for _, e, v in labels if (e, v) == ("ACTION", "FALL"))
        sat += int((S["h"][:, 1:3] < 0.8).any())
        downs += [x for x in plan.split(",") if x.startswith("DOWN")]
    assert falls >= 20, f"kịch bản ngẫu nhiên quá ít lần ngã: {falls}"
    assert sat >= 3, f"khách dừng lâu phải ngồi xuống, chỉ thấy {sat} buổi"
    moving = sum(x.endswith("~") for x in downs) / len(downs)
    assert 0.2 < moving < 0.5, f"~35 % đoạn DOWN phải có cử động, thấy {moving:.0%}"


def test_nhip_tho():
    """Thuật toán nhịp thở (nhip_tho.py) trên 12 chỗ ngồi ngẫu nhiên: khi trả lời thì phần lớn đúng và tốt hơn thuật toán
    đơn giản; nín thở ít bị nhầm là có thở; đang đi lại thì không đưa ra nhịp."""
    import nhip_tho as nt
    kq = nt._danh_gia(n_seed=12, in_ra=False)
    assert kq["tra_loi"] >= 0.2 and kq["dung_khi_tra_loi"] >= 0.55, kq
    assert kq["dung_khi_tra_loi"] > kq["don_gian"], kq
    assert kq["nin_tho_bao_nham"] <= 0.3, kq
    walk = 0
    for seed in range(6):
        _, _, _, _, rx = sim.compute("ACTIVE:35", seed)
        walk += nt.uoc_luong([np.hypot(im[300:3300].astype(float), re[300:3300].astype(float))
                              for im, re, _ in rx.values()])[0] is not None
    assert walk == 0, f"đang đi lại mà vẫn đưa ra nhịp thở {walk}/6"


def test_pipeline(tmp):
    """Dòng CSI v0.3 → buổi mô phỏng → features.py (window 6 s và window động tác)."""
    import features
    import logger
    kind, rec = logger.parse_line("CSI,5,123,2207,1a:00:00:00:00:00,-42,-95,6,0,0,0,104," + "01" * 104)
    assert kind == "CSI" and rec["rx_seq"] == 2207 and rec["len"] == 104
    d = sim.main(["--tag", "luong", "--data-dir", tmp, "--seed", "2",
                  "--plan", "EMPTY:15,ACTIVE:15,+,ACTIVE:15,-,SIT_DOWN,STILL:20@15,STAND_UP,ACTIVE:8,FALL,DOWN:15"])
    _, df = features.session_windows(d)
    cols = set(df.columns)
    assert {"rx1_csi_var_00", "rx2_rssi_iqr", "rx1_n_samples", "label", "activity", "n_people"} <= cols
    assert set(df["label_detail"]) >= {"EMPTY", "ACTIVE", "STILL", "DOWN"} and df["valid"].all()
    assert df["n_people"].max() == 2 and (df.loc[df["label_detail"] == "EMPTY", "n_people"] == 0).all()
    assert (df.loc[df["label_detail"] == "STILL", "breath_rate"] == 15).all()
    _, da = features.action_windows(d)
    assert {"FALL", "SIT_DOWN", "STAND_UP", "NONE"} <= set(da["action"]) and "rx2_shape_ratio" in da.columns
    assert (da["n_people"] == 1).all()


def test_batch(tmp):
    out = sim.main(["--tag", "lo", "--data-dir", tmp, "--so-buoi", "2", "--phut", "1", "--nguoi-bam"])
    assert len(out) == 2 and all((d / "csi.csv").exists() for d in out)


def test_physics():
    """Kiểm tra các phần vật lý của mô hình 3D với công thức / số liệu đã biết."""
    g = abs(sim.gamma(1.0, sim.CONCRETE, 0))                      # vuông góc: (√εr − 1)/(√εr + 1) ≈ 0,39
    assert abs(g - (np.sqrt(5.24) - 1) / (np.sqrt(5.24) + 1)) < 0.01, g
    tx, rx = sim.at(sim.TX), sim.at(sim.RX["RX1"])
    floor = [L for _, L, _, seq in sim.static_paths(sim.RX["RX1"]) if seq == (4,)][0]
    assert abs(floor - np.hypot(np.linalg.norm(tx[:2] - rx[:2]), 2 * sim.ANT_Z)) < 1e-9, "đường dội sàn sai độ dài"
    mid = (tx + rx) / 2
    loss = lambda w, z1, dx=0.0: -20 * np.log10(abs(sim.screen_factor(tx, rx, np.array([[[mid[0] + dx, mid[1] - dx,
                                                                                        w, 0, z1, 1]]]))[0, 0]))
    assert 5 < loss(sim.BODY_W, 1.7) < 15, "người đứng chắn giữa đường truyền: 5–15 dB như đo thực tế ở 2,4 GHz"
    assert abs(loss(1.15, 0.3)) < 1, "người nằm dưới sàn gần như không chắn đường truyền cao 0,75 m"
    assert abs(loss(sim.BODY_W, 1.7, dx=0.8)) < 1.5, "người đứng xa đường truyền ~1,1 m chỉ ảnh hưởng nhẹ"


def test_variability():
    """Mỗi lần ngã một thời lượng khác; nhãn bấm trễ 0–0,8 s so với thời điểm thật."""
    plan = sim.parse_plan("ACTIVE:5,FALL,DOWN:5,STAND_UP,ACTIVE:5,FALL,DOWN:5")
    durs, lags = [], []
    for seed in range(10):
        _, _, labels, spans = sim.timeline(plan, 100, np.random.default_rng(seed))
        durs += [b - a for n, a, b in spans if n == "FALL"]
        truth = [a for n, a, _ in spans if n == "FALL"]
        pressed = [a for a, e, v in labels if (e, v) == ("ACTION", "FALL")]
        lags += [p - t for p, t in zip(pressed, truth)]
    assert np.ptp(durs) > 0.3 and all(0.8 <= d <= 1.61 for d in durs), durs
    assert all(0 <= x <= 0.8 for x in lags) and 0.15 < np.mean(lags) < 0.45, lags


def test_down_cu_dong():
    """DOWN~: lúc cử động mạnh nhất CSI dao động rõ hơn lúc nằm bất động, nhưng không bao giờ đứng lên.
    Phần lớn thời gian (giãy tay chân sát sàn) chỉ hơi nổi trên nhiễu; rõ nhất là lúc cố nhổm dậy."""
    def win_std(im, re, a0):                                       # cửa sổ 1 s, làm mượt 0,1 s bỏ bớt nhiễu từng gói
        amp = np.hypot(im[a0:].astype(float), re[a0:].astype(float))
        c = np.cumsum(np.pad(amp, ((1, 0), (0, 0))), axis=0)
        m = (c[10:] - c[:-10]) / 10
        return m[:len(m) // 100 * 100].reshape(-1, 100, 52).std(axis=1).mean(axis=1)
    peak, rise = {"": 0, "~": 0}, {"": 0, "~": 0}
    for seed in range(3):
        for tail in peak:
            _, S, labels, spans, rx = sim.compute(f"ACTIVE:5,FALL,DOWN:60@15{tail}", seed, nhieu="tat")
            a0 = int((next(a for n, a, _ in spans if n == "DOWN") + 1) * 100)
            peak[tail] = max(peak[tail], np.mean([win_std(im, re, a0) for im, re, _ in rx.values()], axis=0).max())
            rise[tail] = max(rise[tail], S["h"][a0:, 0].max())
            assert (np.abs(S["limb"][a0:]).max() > 0.1) == bool(tail), "chỉ DOWN~ mới có tay chân giãy"
            ev = {(e, v) for _, e, v in labels}
            assert ("STATE", "DOWN") in ev and (("NOTE", "DOWN cu-dong") in ev) == bool(tail)
    assert rise[""] == 0 and 0.15 < rise["~"] <= 0.4, f"DOWN~ cố nhổm dậy nhưng không lên quá ~0,4: {rise}"
    assert peak["~"] > 1.5 * peak[""], peak
    plan = "ACTIVE:5,+,FALL,DOWN:10@15~,-,STAND_UP,ACTIVE:3,FALL,DOWN:5"
    spans = sim.timeline(sim.parse_plan(plan), 100, np.random.default_rng(0))[3]
    d = [s[1:] for s in spans if s[0] == "DOWN"]
    assert sim.down_cu_dong(plan, spans) == [[round(a, 3), round(b, 3)] for a, b in d[:1]], "sai đoạn DOWN~"
    for bad in ("ACTIVE:5~", "STILL:5@12~", "FALL~"):
        try:
            sim.parse_plan(bad)
        except SystemExit:
            continue
        raise AssertionError(f"~ chỉ dùng cho DOWN mà không báo lỗi: {bad}")


def test_nhieu(tmp):
    """Đợt Wi-Fi: n_filtered tăng vọt, mất gói, có gói hỏng; đợt lò vi sóng: noise_floor tăng; meta đủ trường mới."""
    d = sim.main(["--tag", "nhieu", "--data-dir", tmp, "--seed", "3", "--nhieu", "tat,wifi@20:15,khac@40:3",
                  "--plan", "EMPTY:50,ACTIVE:10,FALL,DOWN:20@15~,STAND_UP,ACTIVE:5"])
    m = json.loads((Path(d) / "meta.json").read_text(encoding="utf-8"))["simulator"]
    assert m["interference"] == [["wifi", 20.0, 35.0], ["khac", 40.0, 43.0]] and m["bursts_s"] == 18.0, m
    down = [x[1:] for x in m["truth"] if x[0] == "DOWN"]
    assert m["down_cu_dong"] == down and len(down) == 1, (m["down_cu_dong"], down)
    rows, ht, amp = read_csi(d, "RX1")
    rel = ht - m["t0_host"]
    assert 0 < rel[0] < 0.05, "t0_host phải là host_time của giây 0 mô phỏng"
    stat = [(float(r["host_time"]) - m["t0_host"], int(r["n_rx"]), int(r["n_filtered"]))
            for r in csv.DictReader(open(Path(d) / "stat.csv", encoding="utf-8")) if r["board"] == "RX1"]
    wifi = [s for s in stat if 20.5 < s[0] < 35.5]                  # STAT giây k tính các gói trong [k-1, k)
    calm = [s for s in stat if s[0] < 19.5 or s[0] > 44.5]
    assert min(s[2] for s in wifi) >= 20 and max(s[2] for s in calm) <= 5, "n_filtered phải tăng vọt trong đợt Wi-Fi"
    assert np.mean([s[1] for s in wifi]) < np.mean([s[1] for s in calm]) - 3, "đợt Wi-Fi phải làm mất gói"
    nf = np.array([int(r["noise_floor"]) for r in rows])
    assert (nf[(rel > 40.01) & (rel < 42.99)] == -85).all() and (nf[(rel < 39.9) | (rel > 43.1)] == -95).all()
    jump = np.abs(np.log(amp.mean(axis=1) / np.median(amp[rel < 20].mean(axis=1)))) > np.log(1.8)
    w = (rel > 20) & (rel < 35)
    assert 0.003 < jump[w].mean() < 0.05 and jump[rel < 20].mean() < 0.002, "1–3 % gói hỏng, chỉ trong đợt Wi-Fi"
    for bad in ("wifi@60", "abc@1:2", "wifi@-1:3", "wifi@5:0", "wifi@x:3", "khac@5:3:1"):
        try:
            sim.parse_nhieu(bad)
        except SystemExit:
            continue
        raise AssertionError(f"--nhieu sai cú pháp mà không báo lỗi: {bad}")


def test_bat_dong():
    """Có dữ liệu thử cảnh báo bất động lâu: kịch bản bat-dong, --yen-lau cho buổi ngẫu nhiên (mặc định tắt)."""
    still = lambda plan: max([d for n, d, _ in sim.parse_plan(plan) if n == "STILL"], default=0)
    assert still(sim.KICH_BAN["bat-dong"]) >= 360
    rng = np.random.default_rng(1)
    for _ in range(10):
        plan = sim.random_plan(rng, 5, long_still=True)
        assert 240 <= still(plan) <= 480, plan
        sim.timeline(sim.parse_plan(plan), 20, rng)                  # kịch bản hợp lệ
    assert max(still(sim.random_plan(rng, 5)) for _ in range(20)) <= 60, "mặc định không có đoạn yên dài"
    for argv in (["--yen-lau", "0.5"], ["--yen-lau", "2", "--so-buoi", "1"]):
        try:
            with contextlib.redirect_stderr(io.StringIO()):            # argparse in lỗi ra stderr – ở đây là lỗi cố ý
                sim.main(["--tag", "x", *argv])
        except SystemExit:
            continue
        raise AssertionError(f"tham số sai mà không báo lỗi: {argv}")


def test_ui():
    import mo_phong_ui as ui
    r = ui.run({"kich_ban": "tu-viet", "plan": "EMPTY:5,ACTIVE:10,+,FALL,DOWN:10@15~", "nguoi_bam": True})
    n = len(r["count"])
    assert n == len(r["x"][0]) == len(r["amp"]["RX1"]) and max(r["count"]) == 2, "khách + người được giám sát = 2"
    assert len(__import__("base64").b64decode(r["heat"]["RX1"])) % 52 == 0
    assert len(r["down_cu_dong"]) == 1 and all(k in sim.NHIEU and a < b for k, a, b in r["interference"])
    assert set(ui.PRESETS) == set(sim.KICH_BAN), "mỗi kịch bản có sẵn phải có tên trên giao diện"
    for bad in ({"seed": -1}, {"noise": 1}, {"kich_ban": "khong-co"}, {"kich_ban": "tu-viet", "plan": ""}):
        try:
            ui.params(bad)
        except ValueError:
            continue
        raise AssertionError(f"tham số sai mà không báo lỗi: {bad}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        for test in (test_file_format, test_motion_vs_empty, test_breathing_peak, test_pipeline, test_batch, test_nhieu):
            test(tmp)
            print("ĐẠT", test.__name__)
    for test in (test_bad_plan, test_random_plans, test_physics, test_variability, test_down_cu_dong, test_bat_dong,
                 test_nhip_tho, test_ui):
        test()
        print("ĐẠT", test.__name__)
