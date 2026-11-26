// Chạy kiểm tra trên máy tính (trước khi nạp board) – cùng mã C với firmware:
//   gcc -O2 -I../main may_tinh.c ../main/kiem_tra.c ../main/dac_trung.c ../main/mo_hinh.c -lm -o may_tinh
//   ./may_tinh ../main/mo_hinh.bin ../main/du_lieu_thu.bin          (thêm -DREAL=double để so với bản double)
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#include "kiem_tra.h"

int64_t dong_ho_us(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000000 + t.tv_nsec / 1000;
}

static uint8_t *doc(const char *path, uint32_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    *len = (uint32_t)ftell(f);
    rewind(f);
    uint8_t *b = malloc(*len);
    if (b && fread(b, 1, *len, f) != *len) b = NULL;
    fclose(f);
    return b;
}

int main(int argc, char **argv) {
    uint32_t l1, l2;
    uint8_t *mh = argc > 2 ? doc(argv[1], &l1) : NULL, *dl = argc > 2 ? doc(argv[2], &l2) : NULL;
    if (!mh || !dl) {
        fprintf(stderr, "Cách dùng: %s mo_hinh.bin du_lieu_thu.bin\n", argv[0]);
        return 2;
    }
    int r = kiem_tra(mh, l1, dl, l2, 100.0f);
    return r != 0;
}
