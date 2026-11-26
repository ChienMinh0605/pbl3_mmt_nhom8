#!/usr/bin/env python3
"""Tự kiểm tra quy tắc cảnh báo (canh_bao.py) bằng chuỗi dự đoán tự tạo: python test_canh_bao.py."""
import numpy as np

from canh_bao import ThamSo, chay_lai, kenh_ban

KHONG_THAY, BINH_THUONG = (None, 0.0, "khong-thay"), (15.0, 20.0, "")


def dung(doan, ban=(), p_nhieu=0.1, tho=()):
    """doan: [(mức, giây, động tác đầu đoạn | None)] → quan sát: mức mỗi 1 s, động tác mỗi 0,5 s (động tác đầu đoạn
    được thấy ở window kết thúc 1,5 s sau đầu đoạn); ban: [(a, b)] giây kênh bận; tho: [(t, kết quả uoc_luong)]."""
    obs, t0 = [], 0.0
    for muc, dur, dt in doan:
        for t in np.arange(t0, t0 + dur, 0.5):
            kw = {"dong_tac": dt if dt and t == t0 + 1.5 else "NONE"}
            if t % 1 == 0:
                kw.update(muc=muc, p_nhieu=p_nhieu, ban=any(a <= t <= b for a, b in ban))
            obs.append((float(t), kw))
        t0 += dur
    return obs + [(float(t), {"tho": r}) for t, r in tho]


def loai(obs, **kw):
    """dung() cho mỗi động tác một window: mặc định so_window_nga = 2 thì không phát hiện được, nên các test logic
    khác đặt 1 (test_so_window_nga thử riêng)."""
    return [(a["loai"], a["t"]) for a in chay_lai(obs, ThamSo(**{"so_window_nga": 1, **kw}))[0]]


def test_nga_roi_nam():
    obs = dung([(1, 30, None), (2, 60, "FALL")])
    for bt in "ab":
        assert loai(obs, bien_the=bt) == [("NGA", 41.5)], loai(obs, bien_the=bt)   # 31,5 + 10 s


def test_so_window_nga():
    obs = dung([(1, 30, None), (2, 60, "FALL")])
    assert loai(obs, so_window_nga=2) == [], "một window FALL lẻ chưa đủ"
    assert loai(obs + [(32.0, {"dong_tac": "FALL"})], so_window_nga=2) == [("NGA", 42.0)]


def test_nga_roi_dung_day():
    obs = dung([(1, 30, None), (2, 4, "FALL"), (1, 30, "STAND_UP")])
    assert loai(obs, bien_the="a") == loai(obs, bien_the="b") == []


def test_nga_roi_giay():
    obs = dung([(1, 30, None), (2, 3, "FALL"), (1, 40, None)])          # giãy tại chỗ = Hoạt động, không đứng dậy
    assert loai(obs, bien_the="a") == [("NGA", 41.5)], "biến thể a: cử động tại chỗ không được huỷ"
    assert loai(obs, bien_the="b") == [], "biến thể b: Hoạt động liên tục ≥ huy_hoat_dong_s thì huỷ"
    obs = dung([(1, 30, None), (2, 3, "FALL"), (1, 5, None), (2, 40, None)])    # giãy 5 s rồi nằm yên
    assert loai(obs, bien_the="b") == [("NGA", 41.5)], "biến thể b: giãy ngắn hơn huy_hoat_dong_s không huỷ"


def test_bat_dong_lau():
    assert [x for x, _ in loai(dung([(1, 20, None), (2, 301, None)]))] == ["BAT_DONG_LAU"]
    assert loai(dung([(1, 20, None), (2, 290, None)])) == []
    assert loai(dung([(1, 20, None), (2, 301, None)], p_nhieu=0.9)) == [], "nhiều người: không báo bất động"
    xe_dich = dung([(1, 20, None), (2, 150, None), (1, 5, None), (2, 160, None)])
    assert [x for x, _ in loai(xe_dich)] == ["BAT_DONG_LAU"], "xê dịch vài giây không ngắt đoạn Yên"
    assert loai(xe_dich, bat_dong_ngat_s=0) == []
    assert loai(dung([(1, 20, None), (2, 150, None), (1, 15, None), (2, 160, None)])) == [], "đứng dậy đi lại thì ngắt"


def test_nga_luc_kenh_ban():
    obs = dung([(1, 30, None), (2, 60, "FALL")], ban=[(28, 40)])
    assert loai(obs, co_kenh=False) == loai(obs) == [("NGA", 41.5)], "nằm Yên lúc kênh bận: không gì bị che, báo đúng hạn"
    obs = dung([(1, 30, None), (2, 3, "FALL"), (1, 30, "STAND_UP")], ban=[(28, 40)])
    assert loai(obs, bien_the="a") == [("NGA", 55.0)], "STAND_UP lúc kênh bận không được tin là huỷ: chờ tới 10 s " \
        "sau window bận cuối (45)"
    assert loai(obs, bien_the="b") == [], "b: đi lại đủ 10 s sau khi kênh sạch thì huỷ"
    obs = dung([(1, 30, None), (2, 3, "FALL"), (1, 12, None), (2, 40, None)], ban=[(34, 38)])
    assert loai(obs, bien_the="b") == [("NGA", 53.0)], "b: Hoạt động lúc kênh bận không được nối để huỷ ngã (window " \
        "6 s cuối chồng giây bận kết thúc lúc 43 → hạn 53)"
    obs = dung([(1, 30, None), (2, 3, "FALL"), (1, 200, None)], ban=[(28, 233)])
    assert loai(obs, bien_the="b") == [("NGA", 91.5)], "kênh bận mãi: chờ tối đa 60 s rồi vẫn báo, không bao giờ huỷ"
    obs = dung([(0, 20, None), (1, 13, None), (2, 60, "FALL")], ban=[(15, 60)])
    assert loai(obs) == [("NGA", 44.5)], "người bước vào lúc kênh bận: số người 0 cũ không được tắt phát hiện ngã"
    obs = dung([(1, 30, None), (2, 3, "FALL"), (0, 10, None), (2, 40, None)], ban=[(32, 45)])
    assert loai(obs, bien_the="b", co_kenh=False, huy_trong_s=4) == [] and \
        loai(obs, bien_the="b", huy_trong_s=4) == [("NGA", 52.0)], \
        "Trống lúc kênh bận không được tin là đã đi khỏi"


def test_nga_roi_di_khoi():
    obs = dung([(1, 30, None), (2, 3, "FALL"), (0, 40, None)])
    assert loai(obs, bien_the="b") == [("NGA", 41.5)], "mặc định tắt huỷ khi Trống (chờ dữ liệu thật)"
    assert loai(obs, bien_the="b", huy_trong_s=4) == [], "b: Trống liên tục ≥ huy_trong_s (đi khỏi phòng) thì huỷ"
    assert loai(obs, bien_the="a") == [("NGA", 41.5)]
    obs = dung([(1, 30, None), (2, 4, "FALL"), (0, 3, None), (2, 40, None)])
    assert loai(obs, bien_the="b", huy_trong_s=4) == [("NGA", 41.5)], "Trống lẻ vài giây (nằm bất động bị gọi nhầm) không huỷ"


def test_nhieu_nguoi():
    assert loai(dung([(1, 30, None), (2, 60, "FALL")], p_nhieu=0.9)) == [], "chế độ nhiều người: tắt ngã"
    assert loai(dung([(1, 30, None), (2, 60, "FALL")], p_nhieu=0.6)) == [("NGA", 41.5)], "phân vân thì chọn 1"
    assert loai(dung([(1, 30, None), (2, 60, "FALL")], p_nhieu=0.6), uu_tien_1_nguong=0.5) == []
    assert loai(dung([(1, 30, None), (2, 60, "FALL")], p_nhieu=0.9), so_window_nhieu=40) == [("NGA", 41.5)], \
        "chưa đủ window liên tiếp: vẫn 1 người"
    assert loai(dung([(1, 30, None), (2, 60, "FALL")], p_nhieu=0.9), so_window_nhieu=5) == []


def test_nhip_tho():
    yen = [(1, 30, None), (2, 200, None)]
    assert loai(dung(yen, tho=[(60, BINH_THUONG), (70, KHONG_THAY), (75, KHONG_THAY), (80, KHONG_THAY)])) == [
        ("NGUNG_THO", 80.0)]
    assert loai(dung(yen, tho=[(60, BINH_THUONG), (70, KHONG_THAY), (75, KHONG_THAY)])) == [], "mới 2 cửa sổ"
    assert loai(dung(yen, tho=[(60, KHONG_THAY), (70, KHONG_THAY), (75, KHONG_THAY)])) == [], "chưa đo được nhịp"
    assert loai(dung(yen, tho=[(60, BINH_THUONG), (70, KHONG_THAY), (75, (None, 0.0, "cu-dong")),
                               (80, KHONG_THAY)])) == [], "cử động giữa chừng: đếm lại"
    assert loai(dung(yen, tho=[(60, (30.0, 20.0, "")), (65, (31.0, 20.0, ""))])) == [("THO_BAT_THUONG", 60.0)]
    assert loai(dung(yen, tho=[(60, (30.0, 20.0, "")), (65, BINH_THUONG), (70, (31.0, 20.0, ""))]),
                so_cua_so_tho=2) == [], "hai lần bất thường không liên tiếp"
    assert loai(dung(yen, tho=[(60, (30.0, 20.0, "")), (65, (31.0, 20.0, ""))]), so_cua_so_tho=2) == [
        ("THO_BAT_THUONG", 65.0)]
    assert loai(dung(yen, tho=[(60, (30.0, 20.0, ""))], p_nhieu=0.9)) == [], "nhiều người: tắt nhịp thở"
    nga = dung([(1, 30, None), (2, 200, "FALL")], tho=[(80, KHONG_THAY), (85, KHONG_THAY), (90, KHONG_THAY)])
    assert loai(nga) == [("NGA", 41.5), ("NGA_KHAN_CAP", 90.0)]


def test_kenh_ban():
    assert not kenh_ban(99, 2) and kenh_ban(99, 120) and kenh_ban(70, 0)


def test_luoi_gop_tho():
    from danh_gia_canh_bao import gop_tho, luoi
    g = luoi(np.array([0.0, 0.01, 0.03]), np.array([[1.0], [2.0], [3.0]]), 0.0, 0.05, 100)
    assert g.shape == (5, 1) and list(g[[0, 1, 3], 0]) == [1, 2, 3] and np.isnan(g[[2, 4]]).all(), "gói mất = NaN"
    assert gop_tho([(None, 0, "khong-thay"), (None, 0, "yeu")])[2] == "yeu"
    assert gop_tho([(None, 0, "yeu"), (None, 0, "cu-dong")])[2] == "cu-dong"
    assert gop_tho([(None, 0, "khong-thay"), (15.0, 9, "")])[0] == 15.0


if __name__ == "__main__":
    for test in (test_nga_roi_nam, test_so_window_nga, test_nga_roi_dung_day, test_nga_roi_giay, test_bat_dong_lau,
                 test_nga_luc_kenh_ban, test_nga_roi_di_khoi,
                 test_nhieu_nguoi, test_nhip_tho, test_kenh_ban, test_luoi_gop_tho):
        test()
        print("ĐẠT", test.__name__)
