// Chạy mô hình XGBoost dạng bảng nút (mo_hinh.bin do laptop/xuat_board.py xuất). Bảng đọc thẳng từ vùng nhớ của file
// (trên board: nhúng vào flash), không chép ra RAM.
#pragma once
#include <stdint.h>

typedef struct {                // một nút 16 byte: đọc một lần từ flash là đủ (4 mảng rời = 4 lần trượt cache)
    float val;                  // ngưỡng (nút chia) hoặc giá trị lá
    int16_t cot;                // -1 = lá
    uint8_t thieu_trai, dem;    // giá trị thiếu (NaN) đi nhánh trái?
    uint32_t trai, phai;
} nut_t;

typedef struct {
    uint16_t n_cot, n_lop;
    uint32_t n_cay, n_nut;
    const float *base;
    const uint32_t *goc;
    const nut_t *nut;
} mo_hinh_t;

// blob: nội dung mo_hinh.bin. Trả về 0 nếu đúng định dạng.
int mo_hinh_doc(mo_hinh_t *m, const uint8_t *blob, uint32_t len);
// x: n_cot giá trị (float, đúng thứ tự cột lúc xuất) → xác suất từng lớp (n_lop số). Trả về lớp lớn nhất.
int mo_hinh_du_doan(const mo_hinh_t *m, const float *x, float *xac_suat);
