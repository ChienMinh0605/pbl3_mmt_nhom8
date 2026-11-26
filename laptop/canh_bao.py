#!/usr/bin/env python3
"""Bộ ra quyết định cảnh báo (kế hoạch nhánh người mục 3): biến dự đoán theo thời gian của các tầng thành SỰ KIỆN cảnh
báo. Logic thuần, không phụ thuộc giao diện: dashboard gọi cap_nhat() mỗi khi có dự đoán mới; đánh giá thì chạy lại cả
buổi bằng chay_lai() (danh_gia_canh_bao.py). Kiểm tra: python test_canh_bao.py

    from canh_bao import CanhBao, ThamSo
    cb = CanhBao(ThamSo(bien_the="a"))
    for sk in cb.cap_nhat(t, muc=2, p_nhieu=0.1):           # t = host_time lúc có dự đoán (cuối window)
        print(sk)                                           # {"loai", "t", "muc", "ly_do", "t_phat_hien"}

Đầu vào của cap_nhat (chưa có thì bỏ trống):
    muc       mức hoạt động của window 6 s kết thúc ở t: 0 trống, 1 hoạt động, 2 yên (tầng 0)
    p_nhieu   P(≥ 2 người) của cùng window đó (tầng 1)
    dong_tac  động tác của window 3 s kết thúc ở t: NONE, FALL, STAND_UP, ... (tầng 2a)
    tho       kết quả nhip_tho.uoc_luong (nhịp/phút | None, độ nổi, lý do) trên 30 s kết thúc ở t (tầng 2b)
    ban       kênh bận trong giây kết thúc ở t (từ STAT, xem kenh_ban)

Quy tắc (ngưỡng trong ThamSo):
- Tầng 1: số người chỉ cập nhật khi Hoạt động, Yên thì giữ số cũ, Trống → 0. Phân vân thì chọn 1: chỉ nhận ≥ 2 người
  khi p_nhieu ≥ uu_tien_1_nguong. Chế độ nhiều người tắt phát hiện ngã, nhịp thở, bất động lâu.
- NGA: ≥ so_window_nga window FALL (trong win_3s giây) ở chế độ 1 người → chờ cho_nga_s; không bị huỷ thì cảnh báo.
  Huỷ: biến thể "a" chỉ khi thấy STAND_UP; "b" khi thấy STAND_UP, Hoạt động liên tục ≥ huy_hoat_dong_s hoặc Trống
  liên tục ≥ huy_trong_s (đã đi khỏi phòng) kể từ lúc phát hiện. Cử động tại chỗ (giãy, cố bò dậy) không huỷ ở "a".
  Ngã đã phát hiện thì vẫn xác nhận dù sau đó đếm ra nhiều người (giãy dễ bị đếm nhầm).
- BAT_DONG_LAU: Yên liên tục ≥ bat_dong_s (đoạn không Yên ngắn hơn bat_dong_ngat_s không tính là ngắt).
- THO_BAT_THUONG: nhịp > tho_cao hoặc < tho_thap ở so_cua_so_tho cửa sổ liên tiếp. NGUNG_THO: "khong-thay" ≥
  so_cua_so_ngung cửa sổ liên tiếp, và trong lần Yên này đã đo được nhịp (phòng trống bị nhầm là Yên thì không báo).
  Đang có cảnh báo ngã mà không thấy cả cử động lẫn nhịp thở → NGA_KHAN_CAP (không cần đã đo được nhịp: người ngã có
  thể ngưng thở ngay).
- Cờ kênh (co_kenh): dữ liệu chồng lên giây kênh bận không dùng để kết luận (huỷ ngã, Yên, nhịp thở, hạ số người /
  lên nhiều người; chỉ được nâng 0 → 1 người để kênh bận không tắt được phát hiện ngã). Window FALL lúc kênh bận vẫn
  tính. Chỉ khi giây bận có thể đang che bằng chứng huỷ (Hoạt động / Trống / STAND_UP) thì hạn xác nhận mới lùi tới
  cho_nga_s sau giây đó (tối đa cho_kenh_toi_da_s sau lúc phát hiện); người nằm Yên lúc kênh bận thì báo đúng hạn –
  thông tin kênh chỉ làm trễ, không bao giờ huỷ cảnh báo ngã.
"""
from dataclasses import dataclass

INF = float("inf")


@dataclass
class ThamSo:
    # Mặc định dưới (bien_the, so_window_nga, huy_hoat_dong_s, so_cua_so_ngung, uu_tien_1_nguong, so_window_nhieu):
    # chọn cho cách B trên 20 buổi lẻ data/sim2, kiểm lại trên 20 buổi chẵn (danh_gia_canh_bao.py, 24/11/2026)
    bien_the: str = "b"              # "a": chỉ STAND_UP huỷ ngã; "b": STAND_UP hoặc Hoạt động ≥ huy_hoat_dong_s
    #                                  (b ít báo giả hơn hẳn mà không bắt kém hơn: báo giả lúc đi lại bị huỷ trước khi
    #                                  kịp báo rồi khoá 30 s che mất cú ngã thật ngay sau)
    cho_nga_s: float = 10.0
    so_window_nga: int = 2           # cần ≥ ngần này window FALL trong win_3s giây mới coi là phát hiện ngã
    huy_hoat_dong_s: float = 10.0    # chỉ tính window bắt đầu sau lúc phát hiện: = cho_nga_s nghĩa là phải Hoạt động
    #                                  suốt cả lúc chờ mới huỷ (giãy vài giây rồi nằm yên vẫn báo)
    huy_trong_s: float = INF         # b: Trống liên tục ngần này giây thì huỷ. TẮT (24/11, chờ dữ liệu thật): người nằm
    #                                  bất động sau ngã dễ bị gọi nhầm là Trống → huỷ nhầm ngã thật. Trên sim2 đặt 4 s giảm
    #                                  báo ngã giả 5,8 → 4,9 lần/giờ, không mất cú ngã nào
    khoa_sau_nga_s: float = 30.0     # một cú ngã cho nhiều window FALL liên tiếp: sau cảnh báo bỏ qua FALL một lúc
    bat_dong_s: float = 300.0
    bat_dong_ngat_s: float = 10.0    # Hoạt động / Trống ngắn hơn ngần này không ngắt đoạn Yên (xê dịch vài cm trên ghế
    #                                  cũng làm vài window 6 s liền thành Hoạt động); chỉ dùng cho đoạn Yên
    tho_cao: float = 25.0
    tho_thap: float = 8.0
    so_cua_so_tho: int = 1           # số cửa sổ nhịp bất thường liên tiếp trước khi báo
    so_cua_so_ngung: int = 3         # 2 → 3: NGA_KHAN_CAP / NGUNG_THO giả giảm ~nửa, nín thở bắt được không đổi
    uu_tien_1_nguong: float = 0.7    # cách B: P(≥2) = min của hai board, nên đã dè dặt sẵn
    so_window_nhieu: int = 2         # cần ngần này window Hoạt động liên tiếp có P(≥2) ≥ ngưỡng mới sang nhiều người
    #                                  (cách B, 0,7 / 2: lỗi nguy hiểm ≤ 0,7 %, nhận ra ≥ 2 người ~10 % lúc chuyển động)
    co_kenh: bool = True
    cho_kenh_toi_da_s: float = 60.0  # kênh bận mãi cũng không được giữ cảnh báo ngã quá lâu (sim2 lẻ: 45–90 như nhau,
    #                                  30 thì thêm báo giả lúc nhiễu; chỉ lùi khi giây bận che bằng chứng huỷ)
    win_6s: float = 6.0
    win_3s: float = 3.0
    win_tho_s: float = 30.0


def kenh_ban(n_rx, n_filtered, rate=100.0, max_loc=30, ti_le_rx=0.85):
    """Dòng STAT của một RX → kênh bận? Nhiều khung của máy khác bị lọc, hoặc số gói CSI nhận tụt mạnh.
    Dùng được cho số lẫn mảng / cột pandas (toán tử |)."""
    return (n_filtered > max_loc) | (n_rx < ti_le_rx * rate)


class CanhBao:
    def __init__(self, p=None):
        self.p = p or ThamSo()
        self.so_nguoi = self.dem_nhieu = 0
        self.t_ban = self.t_dung = self.khoa_den = -INF
        self.yen_tu = self.hd_tu = None          # đầu đoạn Yên / Hoạt động liên tục (đầu window đầu tiên)
        self.ngat_tu = None                      # đầu đoạn không Yên đang chen giữa đoạn Yên
        self.trong_tu = None                     # cuối window Trống đầu tiên của đoạn Trống liên tục (kênh sạch)
        self.nga_gan = []                        # lúc các window FALL gần đây
        self.cho = None                          # ngã chờ xác nhận: {"t": lúc phát hiện, "han": hạn, "ban": bool}
        self.nga_luc = None                      # lúc cảnh báo ngã còn hiệu lực (chưa thấy đứng dậy)
        self._moi_lan_yen()

    def _moi_lan_yen(self):
        self.bat_dong_da_bao = self.tho_da_bao = self.ngung_da_bao = self.da_do_nhip = False
        self.dem_ngung = self.dem_bat = 0

    def _ban(self, t, win):
        return self.p.co_kenh and self.t_ban > t - win

    def _huy(self, t, t0):
        """Có dấu hiệu đã đứng dậy / đi lại kể từ t0 (theo biến thể)."""
        di_lai = self.hd_tu is not None and t - max(self.hd_tu, t0) >= self.p.huy_hoat_dong_s
        di_khoi = self.trong_tu is not None and t - max(self.trong_tu, t0) >= self.p.huy_trong_s
        return self.t_dung > t0 or (self.p.bien_the == "b" and (di_lai or di_khoi))

    def _lui(self, t):
        """Giây bận che mất bằng chứng huỷ: chờ thêm để thấy nó trên kênh sạch (không huỷ, chỉ trễ)."""
        if self.cho:
            self.cho["han"] = min(max(self.cho["han"], t + self.p.cho_nga_s), self.cho["t"] + self.p.cho_kenh_toi_da_s)
            self.cho["ban"] = True

    def cap_nhat(self, t, muc=None, p_nhieu=None, dong_tac=None, tho=None, ban=None):
        """Nhận các dự đoán có ở thời điểm t (gọi theo thứ tự thời gian). Trả về danh sách cảnh báo mới."""
        p, out = self.p, []
        bao = lambda loai, muc_do, ly_do, t0=t: out.append(
            {"loai": loai, "t": t, "muc": muc_do, "ly_do": ly_do, "t_phat_hien": t0})
        if ban:
            self.t_ban = t
        if muc is not None and not self._ban(t, p.win_6s):
            if muc == 2:
                self.yen_tu = t - p.win_6s if self.yen_tu is None else self.yen_tu
                self.ngat_tu = None
            else:
                self.ngat_tu = t if self.ngat_tu is None else self.ngat_tu
                if self.yen_tu is not None and t - self.ngat_tu >= p.bat_dong_ngat_s - 1e-9:
                    self.yen_tu = None
                    self._moi_lan_yen()
            self.hd_tu = (t - p.win_6s if self.hd_tu is None else self.hd_tu) if muc == 1 else None
            self.trong_tu = (t if self.trong_tu is None else self.trong_tu) if muc == 0 else None
            if muc == 0:
                self.so_nguoi = 0
            elif muc == 1 and p_nhieu is not None:
                # sang nhiều người phải thấy liên tục (lỗi này tắt phát hiện ngã và bị giữ suốt lúc Yên); về 1 thì ngay
                self.dem_nhieu = self.dem_nhieu + 1 if p_nhieu >= p.uu_tien_1_nguong else 0
                self.so_nguoi = 2 if self.dem_nhieu >= p.so_window_nhieu else 1
            else:
                self.so_nguoi = max(self.so_nguoi, 1)            # Yên: giữ số cũ, nhưng chắc chắn có người
        elif muc is not None:
            self.hd_tu = self.trong_tu = None    # kênh bận: đừng nối đoạn Hoạt động / Trống qua đó để huỷ ngã
            if muc != 2:
                self._lui(t)
            if muc >= 1:
                self.so_nguoi = max(self.so_nguoi, 1)    # người bước vào lúc nhiễu: số 0 cũ không được tắt phát hiện ngã
        if dong_tac == "STAND_UP":
            if self._ban(t, p.win_3s):
                self._lui(t)
            else:
                self.t_dung = t
        if dong_tac == "FALL":
            self.nga_gan = [x for x in self.nga_gan if x > t - p.win_3s] + [t]
        if (dong_tac == "FALL" and len(self.nga_gan) >= p.so_window_nga and self.so_nguoi == 1 and self.cho is None
                and t >= self.khoa_den):
            self.cho = {"t": t, "han": t + p.cho_nga_s, "ban": self._ban(t, p.win_3s)}
        if self.cho and self._huy(t, self.cho["t"]):
            self.cho = None
        if self.nga_luc is not None and self._huy(t, self.nga_luc):
            self.nga_luc = None
        if self.cho and t >= self.cho["han"]:
            c = self.cho
            tre = f", chờ kênh sạch thêm {c['han'] - c['t'] - p.cho_nga_s:.0f} s" if c["ban"] else ""
            bao("NGA", "cao", f"phát hiện ngã, {p.cho_nga_s:g} s không đứng dậy / đi lại{tre}", c["t"])
            self.cho, self.nga_luc, self.khoa_den = None, t, t + p.khoa_sau_nga_s
        mot_nguoi_yen = self.so_nguoi == 1 and self.yen_tu is not None
        if mot_nguoi_yen and t - self.yen_tu >= p.bat_dong_s and not self.bat_dong_da_bao:
            bao("BAT_DONG_LAU", "trung_binh", f"Yên liên tục {t - self.yen_tu:.0f} s")
            self.bat_dong_da_bao = True
        if tho is not None and mot_nguoi_yen and not self._ban(t, p.win_tho_s):
            bpm, _, ly_do = tho
            if bpm is not None:
                self.da_do_nhip, self.dem_ngung, self.ngung_da_bao = True, 0, False
                bat = bpm > p.tho_cao or bpm < p.tho_thap
                self.dem_bat = self.dem_bat + 1 if bat else 0
                if self.dem_bat >= p.so_cua_so_tho and not self.tho_da_bao:
                    bao("THO_BAT_THUONG", "cao", f"nhịp thở {bpm:.0f}/phút")
                    self.tho_da_bao = True
                self.tho_da_bao &= bat
            elif ly_do == "khong-thay":
                self.dem_ngung += 1
                if (self.dem_ngung >= p.so_cua_so_ngung and not self.ngung_da_bao
                        and (self.da_do_nhip or self.nga_luc is not None)):
                    if self.nga_luc is not None:
                        bao("NGA_KHAN_CAP", "khan_cap", "đã ngã, không thấy cử động lẫn nhịp thở")
                    else:
                        bao("NGUNG_THO", "cao", f"{self.dem_ngung} cửa sổ liên tiếp không thấy nhịp thở")
                    self.ngung_da_bao = True
            elif ly_do == "cu-dong":
                self.dem_ngung = self.dem_bat = 0
        return out


def chay_lai(quan_sat, p=None):
    """quan_sat: [(t, {đầu vào cap_nhat}), ...] → (cảnh báo, [(t, số người hệ thống đang tin)] sau mỗi window 6 s)."""
    cb, out, so = CanhBao(p), [], []
    for t, kw in sorted(quan_sat, key=lambda o: o[0]):
        out += cb.cap_nhat(t, **kw)
        if "muc" in kw:
            so.append((t, cb.so_nguoi))
    return out, so
