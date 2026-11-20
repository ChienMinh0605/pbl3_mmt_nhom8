"""Gom Probe Request theo dấu vân tay IE (bước đầu theo Uras et al., Computer Networks 218, 2022).

Dấu vân tay = dãy 'mã:độ dài' của IE, bỏ IE 0 (SSID) vì độ dài SSID đổi theo tên mạng máy đang hỏi.
Mỗi nhóm có thể là nhiều máy cùng đời/cùng hệ điều hành: báo cáo này không phải số thiết bị.
shortcut: chưa tách máy trùng dấu vân tay bằng DBSCAN (tốc độ SEQ, khoảng cách khung, RSSI); làm khi có dữ liệu có nhãn.
"""
import argparse,json
from collections import defaultdict
from pathlib import Path
from statistics import median
from research.evaluate import load_records

BURST_GAP_US=500_000  # bài báo: khung cách nhau < 0,5 s thuộc cùng một đợt quét

def fingerprint(ie):
    return ','.join(x for x in ie.split(',') if x and not x.startswith('0:'))

def burst_rate(frames):
    """Độ dốc SEQ theo thời gian (khung/giây) trong một đợt; None nếu < 3 khung. SEQ quay vòng ở 4096."""
    if len(frames)<3:return None
    seq=[frames[0]['frame_seq']]
    for f in frames[1:]:seq.append(seq[-1]+(f['frame_seq']-seq[-1])%4096)
    xs=[(f['ts_us']-frames[0]['ts_us'])/1e6 for f in frames];mx=sum(xs)/len(xs);my=sum(seq)/len(seq)
    den=sum((x-mx)**2 for x in xs)
    return None if den==0 else sum((x-mx)*(y-my) for x,y in zip(xs,seq))/den

def bursts(frames):
    out=[]
    for f in frames:
        if out and f['ts_us']-out[-1][-1]['ts_us']<BURST_GAP_US:out[-1].append(f)
        else:out.append([f])
    return out

def group(probes,rssi_min=-127):
    by_src=defaultdict(list)  # boot_id tách đồng hồ ts_us giữa các lần board khởi động
    for p in probes:
        if p['rssi']>=rssi_min and p.get('ie'):by_src[(p['boot_id'],p['source_mac'])].append(p)
    groups=defaultdict(lambda:dict(macs=set(),probes=0,rssi_max=-127,bursts=0,rates=[],gaps_ms=[]))
    for (_,mac),frames in by_src.items():
        frames.sort(key=lambda f:f['ts_us'])
        for b in bursts(frames):
            g=groups[fingerprint(b[0]['ie'])]
            g['macs'].add(mac);g['probes']+=len(b);g['bursts']+=1;g['rssi_max']=max(g['rssi_max'],*(f['rssi'] for f in b))
            r=burst_rate(b)
            if r is not None:g['rates'].append(r)
            if len(b)>1:g['gaps_ms'].append((b[-1]['ts_us']-b[0]['ts_us'])/1e3/(len(b)-1))
    return [dict(fingerprint=k,macs=len(g['macs']),probes=g['probes'],bursts=g['bursts'],rssi_max=g['rssi_max'],
                 median_rate=median(g['rates']) if g['rates'] else None,
                 median_gap_ms=median(g['gaps_ms']) if g['gaps_ms'] else None)
            for k,g in sorted(groups.items(),key=lambda x:-len(x[1]['macs']))]

def main():
    ap=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('raw',help='raw.jsonl của một phiên (hoặc file JSON lines thô từ serial)')
    ap.add_argument('--rssi-min',type=int,default=-127,help='bỏ Probe yếu hơn ngưỡng này (dBm)')
    ap.add_argument('--json',help='ghi kết quả ra file JSON')
    a=ap.parse_args()
    rows=group((p for _,p in load_records(Path(a.raw)) if p['type']=='probe'),a.rssi_min)
    print(f"{'MAC':>4} {'goi':>5} {'dot':>4} {'RSSI':>5} {'SEQ/s':>6} {'ms/khung':>8}  dau van tay IE (bo SSID)")
    for r in rows:
        rate='-' if r['median_rate'] is None else f"{r['median_rate']:.0f}"
        gap='-' if r['median_gap_ms'] is None else f"{r['median_gap_ms']:.0f}"
        print(f"{r['macs']:4d} {r['probes']:5d} {r['bursts']:4d} {r['rssi_max']:5d} {rate:>6} {gap:>8}  {r['fingerprint']}")
    print(f"\n{len(rows)} nhom dau van tay, {sum(r['macs'] for r in rows)} MAC. Mot nhom co the gom nhieu may cung doi.")
    if a.json:Path(a.json).write_text(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
