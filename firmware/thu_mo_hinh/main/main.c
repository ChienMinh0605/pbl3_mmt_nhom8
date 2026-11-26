// Thử mô hình động tác trên ESP32-S3 (chưa bật Wi-Fi / CSI): tính 25 cột + chạy XGBoost trên các window CSI thô đã
// nhúng, so với đáp án Python, đo thời gian và bộ nhớ, in qua USB. Lặp lại mỗi 10 s để mở monitor muộn vẫn thấy.
#include <stdio.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "kiem_tra.h"

extern const uint8_t mh_start[] asm("_binary_mo_hinh_bin_start");
extern const uint8_t mh_end[] asm("_binary_mo_hinh_bin_end");
extern const uint8_t dl_start[] asm("_binary_du_lieu_thu_bin_start");
extern const uint8_t dl_end[] asm("_binary_du_lieu_thu_bin_end");

int64_t dong_ho_us(void) { return esp_timer_get_time(); }

void app_main(void) {
    // so hai chỗ để bảng nút: flash (đọc qua cache, chế độ DIO) và bản chép sang PSRAM (octal, nhanh hơn)
    size_t len = mh_end - mh_start;
    uint8_t *mh_psram = heap_caps_malloc(len, MALLOC_CAP_SPIRAM);
    if (mh_psram) memcpy(mh_psram, mh_start, len);
    while (1) {
        size_t ram0 = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
        printf("== Mô hình đọc từ FLASH\n");
        int r = kiem_tra(mh_start, len, dl_start, dl_end - dl_start, 100.0f);
        if (mh_psram) {
            printf("== Mô hình chép sang PSRAM\n");
            r |= kiem_tra(mh_psram, len, dl_start, dl_end - dl_start, 100.0f);
        }
        printf("KET QUA %s | RAM trong còn %u KB (thấp nhất %u KB), PSRAM còn %u KB\n\n", r == 0 ? "DAT" : "LECH",
               (unsigned)(ram0 / 1024), (unsigned)(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL) / 1024),
               (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}
