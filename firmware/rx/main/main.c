// RX (ESP32-S3): thu CSI của gói ESP-NOW từ TX (lọc theo MAC trong menuconfig), in BOOT, CSI, STAT đúng đặc tả
// v0.3 mục 3. Sửa từ esp-csi examples/get-started/csi_recv; khác ví dụ: chỉ lấy LLTF, tắt channel filter (đặc tả
// mục 3.2), giữ MAC riêng của RX, không dùng esp_csi_gain_ctrl.
// Callback CSI chạy trong task Wi-Fi nên chỉ chép dữ liệu vào queue; task in định dạng dòng và ghi ra USB.
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "esp_mac.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"

#define FW "0.3"
#define CSI_TOI_DA 128      // LLTF 64 sóng mang con × 2 byte; dài hơn = không phải cấu hình của mình, bỏ
#define DO_DAI_QUEUE 128    // ~1,3 s ở 100 gói/s

typedef struct {
    int64_t t_us;
    uint16_t rx_seq, len;
    uint8_t mac[6];
    int8_t rssi, noise_floor;
    uint8_t channel, sig_mode, cwb, fwi;
    int8_t buf[CSI_TOI_DA];
} ban_ghi_t;

static uint8_t s_mac_tx[6], s_mac_rx[6];
static QueueHandle_t s_queue;
static atomic_uint s_n_filtered, s_n_queue_drop;

static void doc_mac(const char *s, uint8_t mac[6])
{
    if (sscanf(s, "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx", &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]) != 6) {
        printf("# CSI_MAC_TX sai dinh dang: %s\n", s);
        abort();
    }
}

static void csi_cb(void *ctx, wifi_csi_info_t *info)
{
    if (!info || !info->buf)
        return;
    if (memcmp(info->mac, s_mac_tx, 6) != 0 || info->len > CSI_TOI_DA) {
        atomic_fetch_add(&s_n_filtered, 1);   // khung của máy khác trên kênh: dùng đo độ bận kênh (kenh_ban)
        return;
    }
    const wifi_pkt_rx_ctrl_t *rc = &info->rx_ctrl;
    ban_ghi_t b = {
        .t_us = esp_timer_get_time(), .rx_seq = info->rx_seq, .len = info->len,
        .rssi = rc->rssi, .noise_floor = rc->noise_floor, .channel = rc->channel,
        .sig_mode = rc->sig_mode, .cwb = rc->cwb, .fwi = info->first_word_invalid,
    };
    memcpy(b.mac, info->mac, 6);
    memcpy(b.buf, info->buf, info->len);
    if (xQueueSend(s_queue, &b, 0) != pdTRUE)
        atomic_fetch_add(&s_n_queue_drop, 1);
}

static void in_boot(void)
{
    printf("BOOT,%s," FW "," MACSTR "," MACSTR ",%d\n", CONFIG_CSI_TEN_BOARD, MAC2STR(s_mac_rx), MAC2STR(s_mac_tx),
           CONFIG_CSI_KENH);
}

static void task_in(void *arg)
{
    static const char HEX[] = "0123456789abcdef";
    static char dong[96 + 2 * CSI_TOI_DA];
    ban_ghi_t b;
    uint32_t seq = 0, n_rx = 0;
    int64_t t_stat = esp_timer_get_time(), t_boot = t_stat;
    for (;;) {
        if (xQueueReceive(s_queue, &b, pdMS_TO_TICKS(100)) == pdTRUE) {
            int n = snprintf(dong, sizeof dong, "CSI,%lu,%lld,%u," MACSTR ",%d,%d,%u,%u,%u,%u,%u,",
                             (unsigned long)seq, (long long)b.t_us, b.rx_seq, MAC2STR(b.mac), b.rssi, b.noise_floor,
                             b.channel, b.sig_mode, b.cwb, b.fwi, b.len);
            for (int i = 0; i < b.len; i++) {
                uint8_t v = (uint8_t)b.buf[i];
                dong[n++] = HEX[v >> 4];
                dong[n++] = HEX[v & 15];
            }
            dong[n++] = '\n';
            fwrite(dong, 1, n, stdout);
            seq++, n_rx++;
        }
        int64_t t = esp_timer_get_time();
        if (t - t_stat >= 1000000) {
            uint8_t kenh;
            wifi_second_chan_t phu;
            esp_wifi_get_channel(&kenh, &phu);
            printf("STAT,%lld,%s,%lu,%u,%u,%u\n", (long long)t, CONFIG_CSI_TEN_BOARD, (unsigned long)n_rx,
                   atomic_exchange(&s_n_filtered, 0), atomic_exchange(&s_n_queue_drop, 0), kenh);
            n_rx = 0;
            t_stat += 1000000;
            if (t - t_stat >= 1000000)
                t_stat = t;                     // bị chặn lâu (laptop không đọc): không in dồn STAT
        }
        if (t - t_boot >= 30000000) {
            in_boot();
            t_boot = t;
        }
        if (uxQueueMessagesWaiting(s_queue) == 0)
            fflush(stdout);                     // hết việc thì đẩy phần còn trong bộ đệm ra USB
    }
}

void app_main(void)
{
    // Driver có bộ đệm: printf không chặn mãi khi laptop chưa mở cổng (FIFO đầy thì bỏ).
    usb_serial_jtag_driver_config_t ucfg = {.tx_buffer_size = 16384, .rx_buffer_size = 256};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&ucfg));
    usb_serial_jtag_vfs_use_driver();
    setvbuf(stdout, NULL, _IOFBF, 1024);   // gom vài dòng mỗi lần ghi thay vì ghi từng dòng

    esp_err_t r = nvs_flash_init();
    if (r == ESP_ERR_NVS_NO_FREE_PAGES || r == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        r = nvs_flash_init();
    }
    ESP_ERROR_CHECK(r);
    doc_mac(CONFIG_CSI_MAC_TX, s_mac_tx);

    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW20));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_CSI_KENH, WIFI_SECOND_CHAN_NONE));
    ESP_ERROR_CHECK(esp_wifi_get_mac(WIFI_IF_STA, s_mac_rx));

    s_queue = xQueueCreate(DO_DAI_QUEUE, sizeof(ban_ghi_t));
    assert(s_queue);
    xTaskCreatePinnedToCore(task_in, "in", 4096, NULL, 5, NULL, 1);   // nhân 1; Wi-Fi chạy nhân 0

    // Đặc tả mục 3.2: chỉ LLTF, tắt channel filter để các sóng mang con độc lập, co giãn tự động.
    wifi_csi_config_t csi = {
        .lltf_en = true, .htltf_en = false, .stbc_htltf2_en = false, .ltf_merge_en = false,
        .channel_filter_en = false, .manu_scale = false, .shift = 0,
    };
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));   // nhận cả khung không gửi cho mình → n_filtered đo kênh bận
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    in_boot();
}
