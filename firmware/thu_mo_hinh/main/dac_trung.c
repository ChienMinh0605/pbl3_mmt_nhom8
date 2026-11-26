// Bản C của features.robust_features / motion_features / peak_ratio / good_packets (laptop/features.py). Giữ đúng từng
// bước của bản Python để kết quả khớp; đổi ở đây thì đổi cả bên Python (và ngược lại).
#include "dac_trung.h"

#include <tgmath.h>       // sqrt, log... tự chọn bản float / double theo kiểu real
#include <stdlib.h>
#include <string.h>

#ifdef ESP_PLATFORM                // bộ đệm lớn (~200 KB) để trong RAM trong chip: malloc mặc định đẩy khối > 16 KB ra PSRAM
#include "esp_heap_caps.h"
#define CAP_PHAT(n) heap_caps_malloc(n, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)
#else
#define CAP_PHAT(n) malloc(n)
#endif

#define BAD_LOG 0.5
static const double BANDS[5][2] = {{0.3, 1.0}, {1.0, 3.0}, {3.0, 8.0}, {8.0, 20.0}, {20.0, 40.0}};

static int cmp(const void *a, const void *b) {
    real x = *(const real *)a, y = *(const real *)b;
    return (x > y) - (x < y);
}

static real trung_vi(const real *x, int n, real *tmp) {   // như np.median: n chẵn lấy trung bình hai số giữa
    memcpy(tmp, x, n * sizeof(real));
    qsort(tmp, n, sizeof(real), cmp);
    return n % 2 ? tmp[n / 2] : (tmp[n / 2 - 1] + tmp[n / 2]) / 2;
}

static real tb(const real *x, int n) {
    real s = 0;
    for (int i = 0; i < n; i++) s += x[i];
    return s / n;
}

static real dlc(const real *x, int n) {                   // độ lệch chuẩn (ddof = 0, như numpy)
    real m = tb(x, n), s = 0;
    for (int i = 0; i < n; i++) s += (x[i] - m) * (x[i] - m);
    return sqrt(s / n);
}

// motion_features(x, rate, extra) trên ma trận x (n × k, hàng = gói). Ghi: pc1, cvmed, cvmax, b0..b4, slope, pos,
// after, before, busy và nếu extra: tail, head, lvl, width. Dùng buf (≥ n·k + k·k + 3n + 3k số real).
static void chuyen_dong(const real *x, int n, int k, real rate, int extra, real *o, real *buf) {
    real *rel = buf, *c = rel + n * k, *v = c + k * k, *v2 = v + k, *cv = v2 + k, *s = cv + k, *sm = s + n, *d = sm + n;
    for (int j = 0; j < k; j++) {                          // biên độ tương đối từng sóng mang con, rồi trừ trung bình
        real m = 0;
        for (int i = 0; i < n; i++) m += x[i * k + j];
        m /= n;
        m = m > 1e-6f ? m : 1e-6f;
        real mr = 0;
        for (int i = 0; i < n; i++) mr += (rel[i * k + j] = x[i * k + j] / m - 1);
        mr /= n;
        real ss = 0;
        for (int i = 0; i < n; i++) {
            rel[i * k + j] -= mr;
            ss += rel[i * k + j] * rel[i * k + j];
        }
        cv[j] = sqrt(ss / n);
    }
    memset(c, 0, sizeof(real) * k * k);                    // hiệp phương sai k × k: duyệt theo hàng (gói) cho liền bộ
    for (int i = 0; i < n; i++) {                          // nhớ, chỉ nửa trên rồi chép sang nửa dưới
        const real *r = rel + i * k;
        for (int a = 0; a < k; a++) {
            real ra = r[a], *ca = c + a * k;
            for (int b = a; b < k; b++) ca[b] += ra * r[b];
        }
    }
    for (int a = 0; a < k; a++)
        for (int b = a + 1; b < k; b++) c[b * k + a] = c[a * k + b];
    int j0 = 0;
    real tr = 0;
    for (int j = 0; j < k; j++) {
        tr += c[j * k + j];
        if (c[j * k + j] > c[j0 * k + j0]) j0 = j;
    }
    for (int j = 0; j < k; j++) v[j] = c[j * k + j0];
    for (int it = 0; it < 30; it++) {                      // PC1 bằng lặp lũy thừa (như bản Python)
        real nn = 0;
        for (int a = 0; a < k; a++) {
            real t = 0;
            for (int b = 0; b < k; b++) t += c[a * k + b] * v[b];
            v2[a] = t;
            nn += t * t;
        }
        nn = sqrt(nn);
        nn = nn > 1e-12f ? nn : 1e-12f;
        for (int a = 0; a < k; a++) v[a] = v2[a] / nn;
    }
    real vcv = 0;
    for (int a = 0; a < k; a++) {
        real t = 0;
        for (int b = 0; b < k; b++) t += c[a * k + b] * v[b];
        vcv += v[a] * t;
    }
    real sq = sqrt((real)k);
    for (int i = 0; i < n; i++) {
        real t = 0;
        for (int j = 0; j < k; j++) t += rel[i * k + j] * v[j];
        s[i] = t / sq;
    }
    o[0] = vcv / (tr > 1e-12f ? tr : 1e-12f);
    real cvmax = cv[0];
    for (int j = 1; j < k; j++) cvmax = cv[j] > cvmax ? cv[j] : cvmax;
    o[1] = trung_vi(cv, k, v2);
    o[2] = cvmax;

    // phổ công suất PC1 (cửa sổ Hann như np.hanning) – chỉ tính các tần số cần (< 40 Hz) bằng DFT trực tiếp
    real ms = tb(s, n), p[5] = {0, 0, 0, 0, 0};
    for (int i = 0; i < n; i++)
        sm[i] = (s[i] - ms) * (n > 1 ? (real)0.5 - (real)0.5 * cos((real)(2 * M_PI) * i / (n - 1)) : 1);
    // bảng cos/sin của 2π·m/n tính một lần (rel không còn dùng nên mượn chỗ): S3 chỉ có FPU float, gọi cos/sin trong
    // vòng lặp (72 nghìn lần mỗi window) làm phần này mất ~0,5 s trên board
    real *cs = rel, *sn = rel + n;
    for (int m = 0; m < n; m++) {
        cs[m] = cos((real)(2 * M_PI) * m / n);             // tính bằng kiểu real: double trên S3 là giả lập, rất chậm
        sn[m] = sin((real)(2 * M_PI) * m / n);
    }
    double df = 1.0 / (n * (1.0 / rate));                  // y hệt np.fft.rfftfreq: tần số ở đúng biên dải (8 Hz...)
    for (int q = 1; q <= n / 2; q++) {                     // ra 7,999… như numpy, nên rơi vào cùng dải
        double f = q * df;
        int b = -1;
        for (int z = 0; z < 5; z++)
            if (f >= BANDS[z][0] && f < BANDS[z][1]) b = z;
        if (b < 0) continue;
        real re = 0, im = 0;
        for (int i = 0, m = 0; i < n; i++, m = m + q < n ? m + q : m + q - n) {   // m = q·i mod n
            re += sm[i] * cs[m];
            im -= sm[i] * sn[m];
        }
        p[b] += (re * re + im * im) / n;
    }
    for (int z = 0; z < 5; z++) o[3 + z] = log10(p[z] + 1e-9f);

    // cú biến đổi lớn nhất: độ đổi trong 2w mẫu của PC1 đã làm trơn w mẫu (w = 0,1 s)
    int w = (int)lround(0.1f * rate);
    w = w > 1 ? w : 1;
    int L = n - w + 1, nd;
    for (int i = 0; i < L; i++) {
        real t = 0;
        for (int z = 0; z < w; z++) t += s[i + z];
        sm[i] = t / w;
    }
    if (L > 2 * w) {
        nd = L - 2 * w;
        for (int i = 0; i < nd; i++) d[i] = fabs(sm[i + 2 * w] - sm[i]);
    } else {
        nd = 1;
        d[0] = 0;
    }
    int kk = 0;
    for (int i = 1; i < nd; i++)
        if (d[i] > d[kk]) kk = i;
    real top = d[kk] > 1e-12f ? d[kk] : 1e-12f;
    int a0 = kk + 3 * w, b1 = kk - 3 * w > 0 ? kk - 3 * w : 0, busy = 0;
    for (int i = 0; i < nd; i++) busy += d[i] > 0.3f * top;
    o[8] = d[kk];
    o[9] = (kk + 1.5f * w) / n;
    o[10] = a0 < nd ? tb(d + a0, nd - a0) / top : 1;
    o[11] = b1 > 0 ? tb(d, b1) / top : 1;
    o[12] = (real)busy / nd;
    if (!extra) return;
    int q = (int)rate > 2 ? (int)rate : 2, h = (int)(0.5f * rate) > 2 ? (int)(0.5f * rate) : 2;
    q = q < n ? q : n;                                     // như s[-q:] của numpy khi n < q
    h = h < n ? h : n;
    real sd = dlc(s, n);
    sd = sd > 1e-9f ? sd : 1e-9f;
    int lo = kk, hi = kk;
    while (lo > 0 && d[lo - 1] > 0.5f * top) lo--;
    while (hi + 1 < nd && d[hi + 1] > 0.5f * top) hi++;
    o[13] = dlc(s + n - q, q) / sd;
    o[14] = dlc(s, q) / sd;
    o[15] = fabs(tb(s + n - h, h) - tb(s, h)) / sd;
    o[16] = (hi - lo + 1) / rate;
}

int dac_trung(const int8_t *csi, int n_goi, int n_song, real rate, real out[DT_SO_COT]) {
    int n = n_goi, k = n_song;
    if (n < 20 || k < 2) return -2;                        // như bản Python: window động tác cần ≥ 20 gói
    real *a = CAP_PHAT(sizeof(real) * (2 * n * k + 2 * n));
    real *buf = CAP_PHAT(sizeof(real) * (n * k + k * k + 3 * n + 3 * k));
    if (!a || !buf) {
        free(a);
        free(buf);
        return -1;
    }
    real *m = a + 2 * n * k, *tmp = m + n, *x = a + n * k;
    for (int i = 0; i < n; i++) {                          // biên độ; mức trung bình từng gói
        real t = 0;
        for (int j = 0; j < k; j++) {
            real im = csi[i * 2 * k + 2 * j], re = csi[i * 2 * k + 2 * j + 1];
            t += (a[i * k + j] = sqrt(re * re + im * im));
        }
        m[i] = t / k;
    }
    // good_packets: bỏ gói có mức lệch > e^0,5 so với trung vị (bỏ quá nửa thì coi như không lọc)
    real med = trung_vi(m, n, tmp);
    med = med > 1e-9f ? med : 1e-9f;
    int g = 0;
    for (int i = 0; i < n; i++) g += fabs(log((m[i] > 1e-9f ? m[i] : 1e-9f) / med)) < BAD_LOG;
    int loc = g >= 0.5f * n, ng = 0;
    for (int i = 0; i < n; i++)
        if (!loc || fabs(log((m[i] > 1e-9f ? m[i] : 1e-9f) / med)) < BAD_LOG) {
            memmove(a + ng * k, a + i * k, k * sizeof(real));
            m[ng++] = m[i];
        }
    out[0] = 1 - (real)(loc ? g : n) / n;

    real o[17];
    chuyen_dong(a, ng, k, rate, 0, o, buf);                // mot_b0..b4 trên biên độ thô
    for (int z = 0; z < 5; z++) out[1 + z] = o[3 + z];

    // peak_ratio trên biên độ trung bình các sóng mang con (m đã là mức từng gói sau lọc)
    real mm = tb(m, ng);
    mm = mm > 1e-9f ? mm : 1e-9f;
    for (int i = 0; i < ng; i++) tmp[i] = m[i] / mm;
    int ls = ng >= 20 ? ng - 9 : ng, hh = ng / 2;
    real *sm = buf;
    for (int i = 0; i < ls; i++) {
        if (ng < 20) { sm[i] = tmp[i]; continue; }
        real t = 0;
        for (int z = 0; z < 10; z++) t += tmp[i + z];
        sm[i] = t / 10;
    }
    real pk = 0;
    for (int i = 0; i + 10 < ls; i++) pk = fabs(sm[i + 10] - sm[i]) > pk ? fabs(sm[i + 10] - sm[i]) : pk;
    real s0 = hh > 1 ? dlc(tmp, hh) : 1;
    out[6] = ls > 10 ? pk : 0;
    out[7] = hh > 1 ? dlc(tmp + hh, ng - hh) / (s0 > 1e-9f ? s0 : 1e-9f) : 1;

    for (int i = 0; i < ng; i++) {                         // chia mỗi gói cho mức của nó → mon_* (bền với AGC)
        real mi = m[i] > 1e-9f ? m[i] : 1e-9f;
        for (int j = 0; j < k; j++) x[i * k + j] = a[i * k + j] / mi;
    }
    chuyen_dong(x, ng, k, rate, 1, out + 8, buf);
    free(a);
    free(buf);
    return 0;
}
