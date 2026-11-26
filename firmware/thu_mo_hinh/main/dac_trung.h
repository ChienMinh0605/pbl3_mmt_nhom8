// 25 đặc trưng động tác của một board (bản C của laptop/features.py: robust_features), window 3 s.
#pragma once
#include <stdint.h>

#ifndef REAL
#define REAL float          // board: float (có FPU đơn); trên máy tính có thể dịch -DREAL=double để tách lỗi thuật toán
#endif
typedef REAL real;

#define DT_SO_COT 25        // thứ tự: mot_bad, mot_b0..b4, mot_peak, mot_ratio, mon_pc1, cvmed, cvmax, b0..b4, slope,
                            // pos, after, before, busy, tail, head, lvl, width (như COT trong xuat_board.py)

// csi: n_goi gói × (2 × n_song) byte int8 (byte chẵn phần ảo, lẻ phần thực, như dòng CSI). rate: gói / giây.
// Trả về 0 nếu được, -1 nếu thiếu bộ nhớ, -2 nếu quá ít gói (< 20).
int dac_trung(const int8_t *csi, int n_goi, int n_song, real rate, real out[DT_SO_COT]);
