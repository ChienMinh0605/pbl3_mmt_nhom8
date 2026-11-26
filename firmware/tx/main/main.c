// TX (ESP32-C3): phát ESP-NOW broadcast CONFIG_CSI_TAN_SO gói/s trên kênh cố định, MAC phát đặt trong menuconfig.
// Sửa từ esp-csi examples/get-started/csi_send, bỏ nhánh C5/C6, băng thông HT20 (đặc tả v0.3: 20 MHz).
// Console mặc định của IDF (UART0, kèm USB-JTAG phụ) nên in được qua cổng CH340 lẫn cổng USB gốc.
// In ra: BOOT (đặc tả mục 3.1) lúc khởi động và mỗi 30 s; dòng "# tx ..." để gỡ lỗi (logger bỏ qua).
#include <stdio.h>
#include <string.h>
#include "esp_mac.h"
#include "esp_now.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#define FW "0.3"
static const uint8_t BROADCAST[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

static void doc_mac(const char *s, uint8_t mac[6])
{
    if (sscanf(s, "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx", &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]) != 6) {
        printf("# CSI_MAC_TX sai dinh dang: %s\n", s);
        abort();
    }
}

void app_main(void)
{
    esp_err_t r = nvs_flash_init();
    if (r == ESP_ERR_NVS_NO_FREE_PAGES || r == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        r = nvs_flash_init();
    }
    ESP_ERROR_CHECK(r);

    uint8_t mac[6];
    doc_mac(CONFIG_CSI_MAC_TX, mac);
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW20));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_CSI_KENH, WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, mac));

    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk((const uint8_t *)"pmk1234567890123"));
    esp_now_peer_info_t peer = {.channel = CONFIG_CSI_KENH, .ifidx = WIFI_IF_STA, .encrypt = false};
    memcpy(peer.peer_addr, BROADCAST, 6);
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    esp_now_rate_config_t rate = {.phymode = WIFI_PHY_MODE_HT20, .rate = WIFI_PHY_RATE_MCS0_LGI};
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(BROADCAST, &rate));

    const TickType_t chu_ky = pdMS_TO_TICKS(1000 / CONFIG_CSI_TAN_SO);
    TickType_t truoc = xTaskGetTickCount();
    uint32_t dem = 0, loi = 0, dem_cu = 0;
    int64_t t_boot = -30000000;
    for (;;) {
        int64_t t = esp_timer_get_time();
        if (t - t_boot >= 30000000) {
            printf("BOOT,TX," FW "," MACSTR ",-,%d\n", MAC2STR(mac), CONFIG_CSI_KENH);
            if (t_boot >= 0)
                printf("# tx %lu goi/30s, loi %lu\n", (unsigned long)(dem - dem_cu), (unsigned long)loi);
            t_boot = t, dem_cu = dem, loi = 0;
        }
        // Nội dung gói = bộ đếm 4 byte như csi_send; RX lấy rx_seq từ header 802.11, không đọc nội dung.
        if (esp_now_send(BROADCAST, (const uint8_t *)&dem, sizeof(dem)) == ESP_OK)
            dem++;
        else
            loi++;
        vTaskDelayUntil(&truoc, chu_ky);
    }
}
