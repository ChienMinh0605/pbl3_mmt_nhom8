#!/usr/bin/env python3
"""LOGGER TẠM – ghi một buổi thu đúng mục 4 của đặc tả, trong lúc chờ logger.py chính thức của Chiến.

  py python/logger_tam.py --rx COM9 --ten phongA --phong "Phòng A tầng 2" --khoang-cach 3
  py python/logger_tam.py --rx COM9 --snf COM10 --ten phongA      # thêm board #3 của Phúc

Tạo data/raw/<YYYYMMDD_HHMM_ten>/ gồm: meta.json, csi.csv, probe.csv, stat.csv, boot.csv, labels.csv

Phím ghi nhãn (mục 4.4) – bấm trong cửa sổ Terminal đang chạy logger:
  E = EMPTY   W = WALK   S = STATIC   M = MULTI   N = NEIGHBOR   P = PAUSE
  + / -  = có người vào / ra (đếm thủ công cho nhánh thiết bị)
  T = ghi chú      Q = kết thúc buổi thu
Logger bắt đầu ở PAUSE: sắp xếp xong thì bấm phím trạng thái đầu tiên.
(Tắt bộ gõ tiếng Việt khi bấm phím.)
"""
import argparse
import hashlib
import json
import os
import queue
import secrets
import sys
import threading
import time

from features import PRB_FIELDS, STATE_KEYS, parse_line

CONFIG = "config_local.json"     # chứa salt + MAC loại trừ; KHÔNG đưa lên Git, KHÔNG để trong data/


def load_config():
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {"salt": secrets.token_hex(16), "excluded_macs": []}
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print(f"  đã tạo {CONFIG} (salt ngẫu nhiên). Thêm MAC laptop demo vào excluded_macs.")
    cfg["excluded_macs"] = {m.lower() for m in cfg.get("excluded_macs", [])}
    return cfg


def reader(port, baud, out_q, stop):
    import serial
    ser = serial.Serial(port, baud, timeout=0.5)
    while not stop.is_set():
        raw = ser.readline()
        if raw:
            out_q.put((time.time(), raw.decode("ascii", "ignore")))
    ser.close()


def key_reader(out_q, stop):
    """Đọc phím: Windows dùng msvcrt (không cần Enter); hệ khác: gõ phím rồi Enter."""
    if os.name == "nt":
        import msvcrt
        while not stop.is_set():
            if msvcrt.kbhit():
                out_q.put((time.time(), msvcrt.getwch()))
            else:
                time.sleep(0.02)
    else:
        for line in sys.stdin:
            if line.strip():
                out_q.put((time.time(), line.strip()[0]))
            if stop.is_set():
                break


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rx", required=True, help="cổng COM của board #2")
    ap.add_argument("--snf", help="cổng COM của board #3 (tuỳ chọn)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--ten", required=True, help="tên ngắn của buổi thu, ví dụ phongA")
    ap.add_argument("--phong", default="")
    ap.add_argument("--khoang-cach", type=float, default=3.0)
    ap.add_argument("--kenh", type=int, default=6)
    ap.add_argument("--thanh-vien", default="Tiên")
    ap.add_argument("--out", default="data/raw")
    a = ap.parse_args()

    cfg = load_config()
    sid = time.strftime("%Y%m%d_%H%M_") + a.ten
    d = os.path.join(a.out, sid)
    os.makedirs(d, exist_ok=False)
    meta = {"session_id": sid, "room": a.phong, "tx_rx_distance_m": a.khoang_cach, "channel": a.kenh,
            "members": [m.strip() for m in a.thanh_vien.split(",")], "fw": {},
            "spec_version": "0.1", "notes": ""}

    files = {}
    headers = {
        "CSI": "host_time,seq,t_us,src_mac,rssi,noise_floor,channel,sig_mode,cwb,first_word_invalid,len,csi_hex",
        "STAT": "host_time,t_us,board,n_rx,n_filtered,n_queue_drop,channel",
        "BOOT": "host_time,board,fw,mac_sta,mac_ap,channel",
        "PRB": "host_time,seq,t_us,mac_hash,local_admin,rssi,channel,excluded",
        "LAB": "host_time,event,value",
    }
    names = {"CSI": "csi.csv", "STAT": "stat.csv", "BOOT": "boot.csv", "PRB": "probe.csv", "LAB": "labels.csv"}
    for k, h in headers.items():
        files[k] = open(os.path.join(d, names[k]), "w", encoding="utf-8", newline="")
        files[k].write(h + "\n")

    def label(ev, val):
        files["LAB"].write(f"{time.time():.4f},{ev},{val}\n")
        files["LAB"].flush()

    q, stop = queue.Queue(), threading.Event()
    threading.Thread(target=reader, args=(a.rx, a.baud, q, stop), daemon=True).start()
    if a.snf:
        threading.Thread(target=reader, args=(a.snf, a.baud, q, stop), daemon=True).start()
    kq = queue.Queue()
    threading.Thread(target=key_reader, args=(kq, stop), daemon=True).start()

    state = "PAUSE"
    label("STATE", state)
    print(f"Ghi vào {d}\nĐang ở PAUSE. Bấm E/W/S/M/N/P để đổi trạng thái, +/- đếm người, T ghi chú, Q kết thúc.")
    n_csi = n_prb = drops = 0
    t_last, n_last = time.time(), 0
    try:
        while True:
            try:
                ht, line = q.get(timeout=0.1)
                p = parse_line(line)
                if p:
                    kind, f = p
                    if kind == "CSI":
                        files["CSI"].write(f"{ht:.4f}," + line.strip()[4:] + "\n")
                        n_csi += 1
                    elif kind == "STAT":
                        files["STAT"].write(f"{ht:.4f}," + line.strip()[5:] + "\n")
                        drops += int(f["n_queue_drop"])
                    elif kind == "BOOT":
                        files["BOOT"].write(f"{ht:.4f}," + line.strip()[5:] + "\n")
                        meta["fw"][f["board"]] = f["fw"]
                        cfg["excluded_macs"].update(m.lower() for m in (f["mac_sta"], f["mac_ap"]) if m != "-")
                    elif kind == "PRB":
                        mac = f["src_mac"].lower()
                        h = hashlib.sha256((cfg["salt"] + mac).encode()).hexdigest()[:12]
                        la = (int(mac[:2], 16) >> 1) & 1
                        ex = int(mac in cfg["excluded_macs"])
                        files["PRB"].write(f"{ht:.4f},{f['seq']},{f['t_us']},{h},{la},{f['rssi']},{f['channel']},{ex}\n")
                        n_prb += 1
            except queue.Empty:
                pass
            while not kq.empty():
                _, k = kq.get()
                k = k.lower()
                if k in STATE_KEYS:
                    state = STATE_KEYS[k]
                    label("STATE", state)
                    print(f"\n>>> {state}")
                elif k in "+-":
                    label("COUNT", f"{k}1")
                    print(f"\n>>> COUNT {k}1")
                elif k == "t":
                    note = input("\nGhi chú: ").replace(",", ";")
                    label("NOTE", note)
                elif k == "q":
                    raise KeyboardInterrupt
            if time.time() - t_last >= 5:
                rate = (n_csi - n_last) / (time.time() - t_last)
                print(f"  [{state:8s}] CSI {rate:5.1f} dòng/giây | tổng {n_csi} | mất trong queue {drops}"
                      + (f" | PRB {n_prb}" if a.snf else ""))
                t_last, n_last = time.time(), n_csi
                for fh in files.values():
                    fh.flush()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        label("STATE", "PAUSE")
        for fh in files.values():
            fh.close()
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"\nĐã lưu buổi thu {sid}: {n_csi} dòng CSI.")
        print(f"Kiểm tra:  py python/kiem_tra.py {d}")


if __name__ == "__main__":
    main()
