import json
import pytest
from backend.app.protocol import parse_line
from research.ie_fingerprint import fingerprint,burst_rate,group

def probe(mac,ts_us,seq,ie,rssi=-30,boot='b'):
    return dict(v=1,type='probe',node='sniffer',boot_id=boot,ts_us=ts_us,seq=0,source_mac=mac,rssi=rssi,
                channel=6,frame_seq=seq,retry=False,ie=ie)

def test_fingerprint_drops_ssid_length():
    assert fingerprint('0:0,1:4,50:8') == fingerprint('0:11,1:4,50:8') == '1:4,50:8'

def test_burst_rate_handles_seq_wrap():
    frames=[probe('02:00:00:00:00:01',i*10_000,(4094+i)%4096,'1:4') for i in range(5)]
    assert burst_rate(frames) == pytest.approx(100)
    assert burst_rate(frames[:2]) is None

def test_two_macs_same_fingerprint_form_one_group():
    rows=group([probe('02:00:00:00:00:01',0,10,'0:0,1:4'),probe('02:00:00:00:00:01',20_000,11,'0:0,1:4'),
                probe('06:00:00:00:00:02',5_000_000,900,'0:9,1:4'),probe('0a:00:00:00:00:03',0,5,'1:8',rssi=-90)],rssi_min=-50)
    assert [(r['fingerprint'],r['macs'],r['bursts'],r['probes']) for r in rows] == [('1:4',2,2,3)]

def test_parser_keeps_ie_and_rejects_garbage():
    assert parse_line(json.dumps(probe('02:00:00:00:00:01',0,1,'0:0,1:4')))['ie'] == '0:0,1:4'
    legacy=probe('02:00:00:00:00:01',0,1,'');del legacy['ie']
    assert parse_line(json.dumps(legacy))['ie'] == ''
    with pytest.raises(ValueError):parse_line(json.dumps(probe('02:00:00:00:00:01',0,1,'0:0;rm')))
