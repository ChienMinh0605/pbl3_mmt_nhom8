#include "kiem_tra.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "dac_trung.h"
#include "mo_hinh.h"

static const char *TEN[DT_SO_COT] = {"mot_bad", "mot_b0", "mot_b1", "mot_b2", "mot_b3", "mot_b4", "mot_peak",
                                     "mot_ratio", "mon_pc1", "mon_cvmed", "mon_cvmax", "mon_b0", "mon_b1", "mon_b2",
                                     "mon_b3", "mon_b4", "mon_slope", "mon_pos", "mon_after", "mon_before",
                                     "mon_busy", "mon_tail", "mon_head", "mon_lvl", "mon_width"};

int kiem_tra(const uint8_t *mh, uint32_t len_mh, const uint8_t *dl, uint32_t len_dl, float rate) {
    mo_hinh_t m;
    if (mo_hinh_doc(&m, mh, len_mh) || m.n_cot != DT_SO_COT) {
        printf("mo_hinh.bin sai định dạng\n");
        return -1;
    }
    uint16_t hd[4];                                        // số window, số sóng mang con, số cột, số lớp
    if (len_dl < 12 || memcmp(dl, "DL01", 4)) return -1;
    memcpy(hd, dl + 4, 8);
    if (hd[2] != DT_SO_COT || hd[3] != m.n_lop) return -1;
    printf("Mô hình: %u cây, %u nút, %u lớp | %u window đối chiếu\n", (unsigned)m.n_cay, (unsigned)m.n_nut,
           m.n_lop, hd[0]);
    uint32_t o = 12;
    float lech_cot[DT_SO_COT] = {0}, lech_p = 0;
    int sai_lop = 0;
    int64_t t_dt = 0, t_mh = 0, max_dt = 0;
    for (int w = 0; w < hd[0]; w++) {
        uint16_t n;
        memcpy(&n, dl + o, 2);
        float x_py[DT_SO_COT], p_py[16], p[16], x[DT_SO_COT];
        memcpy(x_py, dl + o + 4, 4 * DT_SO_COT);
        memcpy(p_py, dl + o + 4 + 4 * DT_SO_COT, 4 * m.n_lop);
        const int8_t *csi = (const int8_t *)(dl + o + 4 + 4 * DT_SO_COT + 4 * m.n_lop);
        o += 4 + 4 * DT_SO_COT + 4 * m.n_lop + n * 2 * hd[1];
        if (o > len_dl) return -1;

        real xr[DT_SO_COT];
        int64_t t0 = dong_ho_us();
        if (dac_trung(csi, n, hd[1], rate, xr)) {
            printf("Thiếu bộ nhớ ở window %d\n", w);
            return -1;
        }
        int64_t t1 = dong_ho_us();
        for (int c = 0; c < DT_SO_COT; c++) x[c] = (float)xr[c];
        int lop = mo_hinh_du_doan(&m, x, p);
        int64_t t2 = dong_ho_us();
        t_dt += t1 - t0, t_mh += t2 - t1;
        max_dt = t1 - t0 > max_dt ? t1 - t0 : max_dt;

        int lop_py = 0;
        for (int c = 0; c < m.n_lop; c++) {
            if (p_py[c] > p_py[lop_py]) lop_py = c;
            lech_p = fabsf(p[c] - p_py[c]) > lech_p ? fabsf(p[c] - p_py[c]) : lech_p;
        }
        sai_lop += lop != lop_py;
        for (int c = 0; c < DT_SO_COT; c++) {              // lệch tương đối (so với độ lớn của chính giá trị)
            float e = fabsf(x[c] - x_py[c]) / fmaxf(fabsf(x_py[c]), 1e-3f);
            lech_cot[c] = e > lech_cot[c] ? e : lech_cot[c];
        }
    }
    printf("Lệch tương đối lớn nhất của từng cột so với Python:\n");
    for (int c = 0; c < DT_SO_COT; c++) printf("  %-11s %.2e%s", TEN[c], lech_cot[c], c % 3 == 2 ? "\n" : "");
    printf("\nXác suất lệch lớn nhất: %.2e | khác lớp: %d/%u window\n", lech_p, sai_lop, hd[0]);
    printf("Thời gian TB mỗi window: đặc trưng %.2f ms (lớn nhất %.2f ms), mô hình %.3f ms\n",
           t_dt / 1000.0 / hd[0], max_dt / 1000.0, t_mh / 1000.0 / hd[0]);
    return sai_lop;
}
