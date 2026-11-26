#include "mo_hinh.h"

#include <math.h>
#include <string.h>

int mo_hinh_doc(mo_hinh_t *m, const uint8_t *b, uint32_t len) {
    if (len < 16 || memcmp(b, "MH02", 4) || ((uintptr_t)b & 3)) return -1;
    memcpy(&m->n_cot, b + 4, 2);
    memcpy(&m->n_lop, b + 6, 2);
    memcpy(&m->n_cay, b + 8, 4);
    memcpy(&m->n_nut, b + 12, 4);
    uint32_t o = 16;
    m->base = (const float *)(b + o), o += 4 * m->n_lop;
    m->goc = (const uint32_t *)(b + o), o += 4 * m->n_cay;
    m->nut = (const nut_t *)(b + o), o += sizeof(nut_t) * m->n_nut;
    return o == len ? 0 : -1;                              // sai độ dài: file hỏng hoặc khác phiên bản
}

int mo_hinh_du_doan(const mo_hinh_t *m, const float *x, float *p) {
    for (int c = 0; c < m->n_lop; c++) p[c] = m->base[c];
    for (uint32_t t = 0; t < m->n_cay; t++) {
        const nut_t *u = m->nut + m->goc[t];
        while (u->cot >= 0) {
            float v = x[u->cot];
            u = m->nut + (isnan(v) ? (u->thieu_trai ? u->trai : u->phai) : (v < u->val ? u->trai : u->phai));
        }
        p[t % m->n_lop] += u->val;                         // cây xếp vòng theo lớp
    }
    float mx = p[0], s = 0;                                // softmax
    for (int c = 1; c < m->n_lop; c++) mx = p[c] > mx ? p[c] : mx;
    for (int c = 0; c < m->n_lop; c++) s += (p[c] = expf(p[c] - mx));
    int best = 0;
    for (int c = 0; c < m->n_lop; c++) {
        p[c] /= s;
        if (p[c] > p[best]) best = c;
    }
    return best;
}
