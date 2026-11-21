// ESP32-C3 #2 – RX / STA: kết nối vào #1, gửi UDP ~100 lần/giây, đo CSI từ gói trả lời.
// In ra Serial theo "Đặc tả định dạng dữ liệu" v0.1, mục 3:
//   BOOT,RX,<fw>,<mac_sta>,<mac_ap>,<channel>                         khi khởi động, khi kết nối, mỗi 30 s
//   CSI,<seq>,<t_us>,<src_mac>,<rssi>,<noise_floor>,<channel>,<sig_mode>,<cwb>,<first_word_invalid>,<len>,<csi_hex>
//   STAT,<t_us>,RX,<n_rx>,<n_filtered>,<n_queue_drop>,<channel>      mỗi giây
// Dòng bắt đầu bằng '#' là log gỡ lỗi, laptop bỏ qua.
//
// PRINT_CSI 1 : chạy thật (in mọi dòng CSI) – đóng Serial Monitor trước khi chạy logger.
// PRINT_CSI 0 : chỉ in BOOT + STAT – dùng Serial Monitor xem tốc độ CSI (n_rx) cho dễ đọc.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_wifi.h"

#define FW_VERSION "0.1"
#define PRINT_CSI  1

const char* WIFI_SSID = "csi_ap";
const char* WIFI_PASS = "csi12345";
const int   UDP_PORT = 5000;
const uint32_t SEND_INTERVAL_US = 10000;   // 10 ms → ~100 gói/giây
const int CSI_MAX_BYTES = 384;             // cấu hình chỉ LLTF → dự kiến len = 128
const int64_t STAT_PERIOD_US = 1000000;
const int64_t BOOT_PERIOD_US = 30000000;

typedef struct {
  int64_t  t_us;
  uint8_t  src[6];
  int8_t   rssi;
  int8_t   noise_floor;
  uint8_t  channel, sig_mode, cwb, fwi;
  uint16_t len;
  int8_t   buf[CSI_MAX_BYTES];
} csi_pkt_t;

QueueHandle_t q;
uint8_t apMac[6];
char macStaStr[18] = "-", macApStr[18] = "-";
volatile bool haveAp = false;
volatile bool forceBoot = true;
volatile uint8_t curChannel = 0;
volatile uint32_t nFiltered = 0, nDrop = 0;
WiFiUDP udp;
IPAddress apIp;

static void macToStr(const uint8_t* m, char* out) {
  snprintf(out, 18, "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
}

// Chạy trong Wi-Fi task: chỉ lọc + copy + đẩy vào queue, không Serial ở đây.
void csiCallback(void* ctx, wifi_csi_info_t* info) {
  if (info == NULL || info->buf == NULL || !haveAp) return;
  if (memcmp(info->mac, apMac, 6) != 0) { nFiltered++; return; }   // chỉ giữ khung từ #1
  csi_pkt_t p;
  p.t_us = esp_timer_get_time();
  memcpy(p.src, info->mac, 6);
  p.rssi        = info->rx_ctrl.rssi;
  p.noise_floor = info->rx_ctrl.noise_floor;
  p.channel     = info->rx_ctrl.channel;
  p.sig_mode    = info->rx_ctrl.sig_mode;
  p.cwb         = info->rx_ctrl.cwb;
  p.fwi         = info->first_word_invalid;
  p.len = info->len > CSI_MAX_BYTES ? CSI_MAX_BYTES : info->len;
  memcpy(p.buf, info->buf, p.len);
  if (xQueueSend(q, &p, 0) != pdTRUE) nDrop++;
}

// Task DUY NHẤT ghi ra Serial (CSI, STAT, BOOT) → các dòng không bao giờ bị lẫn vào nhau.
void printTask(void* arg) {
  static char line[64 + 2 * CSI_MAX_BYTES];
  static const char HEX_CH[] = "0123456789abcdef";
  csi_pkt_t p;
  uint32_t seq = 0, nSent = 0, lastFiltered = 0, lastDrop = 0;
  int64_t tStat = esp_timer_get_time(), tBoot = tStat;
  for (;;) {
    if (xQueueReceive(q, &p, pdMS_TO_TICKS(50)) == pdTRUE) {
#if PRINT_CSI
      int n = snprintf(line, sizeof line,
                       "CSI,%lu,%lld,%02x:%02x:%02x:%02x:%02x:%02x,%d,%d,%u,%u,%u,%u,%u,",
                       (unsigned long)seq, (long long)p.t_us,
                       p.src[0], p.src[1], p.src[2], p.src[3], p.src[4], p.src[5],
                       p.rssi, p.noise_floor, p.channel, p.sig_mode, p.cwb, p.fwi, p.len);
      for (int i = 0; i < p.len; i++) {
        uint8_t b = (uint8_t)p.buf[i];
        line[n++] = HEX_CH[b >> 4];
        line[n++] = HEX_CH[b & 0x0f];
      }
      line[n++] = '\n';
      Serial.write((uint8_t*)line, n);
#endif
      seq++;
      nSent++;
    }
    int64_t now = esp_timer_get_time();
    if (now - tStat >= STAT_PERIOD_US) {
      uint32_t f = nFiltered, d = nDrop;
      Serial.printf("STAT,%lld,RX,%lu,%lu,%lu,%u\n", (long long)now, (unsigned long)nSent,
                    (unsigned long)(f - lastFiltered), (unsigned long)(d - lastDrop), curChannel);
      nSent = 0; lastFiltered = f; lastDrop = d; tStat = now;
    }
    if (forceBoot || now - tBoot >= BOOT_PERIOD_US) {
      Serial.printf("BOOT,RX,%s,%s,%s,%u\n", FW_VERSION, macStaStr, macApStr, curChannel);
      forceBoot = false; tBoot = now;
    }
  }
}

void connectAp() {
  haveAp = false;
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(300);
  memcpy(apMac, WiFi.BSSID(), 6);          // BSSID đọc sau khi kết nối, không ghi cứng
  macToStr(apMac, macApStr);
  apIp = WiFi.gatewayIP();
  curChannel = WiFi.channel();
  haveAp = true;
  forceBoot = true;                         // in lại BOOT với mac_ap mới
}

void setup() {
  Serial.begin(921600);
  delay(1000);
  q = xQueueCreate(64, sizeof(csi_pkt_t));
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                     // tắt power save – bắt buộc
  uint8_t m[6];
  esp_wifi_get_mac(WIFI_IF_STA, m);
  macToStr(m, macStaStr);
  xTaskCreate(printTask, "csi_print", 4096, NULL, 5, NULL);

  connectAp();
  udp.begin(UDP_PORT + 1);

  wifi_csi_config_t cfg = {};
  cfg.lltf_en = true;                       // chỉ lấy LLTF: 64 sóng mang con
  cfg.htltf_en = false;
  cfg.stbc_htltf2_en = false;
  cfg.ltf_merge_en = false;
  cfg.channel_filter_en = false;
  cfg.manu_scale = false;
  cfg.shift = 0;
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csiCallback, NULL));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

void loop() {
  static uint32_t tSend = 0, cnt = 0;
  if (WiFi.status() != WL_CONNECTED) { connectAp(); return; }
  uint32_t now = micros();
  if (now - tSend >= SEND_INTERVAL_US) {
    tSend = now;
    udp.beginPacket(apIp, UDP_PORT);
    udp.write((uint8_t*)&cnt, sizeof(cnt));
    udp.endPacket();
    cnt++;
  }
  while (udp.parsePacket() > 0) udp.flush();   // bỏ gói trả lời, CSI đã đo ở callback
}
