// Chạy mọi window trong du_lieu_thu.bin: tính 25 cột, chạy mô hình, so với đáp án Python, đo thời gian.
// Dùng chung cho máy tính (host/may_tinh.c) và board (main.c); dong_ho_us() do mỗi bên tự cung cấp.
#pragma once
#include <stdint.h>

int64_t dong_ho_us(void);
// Trả về số window lệch lớp so với Python (âm nếu file sai định dạng). In bảng kết quả bằng printf.
int kiem_tra(const uint8_t *mo_hinh, uint32_t len_mh, const uint8_t *du_lieu, uint32_t len_dl, float rate);
