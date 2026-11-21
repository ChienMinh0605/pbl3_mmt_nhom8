// ESP32-C3 #1 – TX / SoftAP trên một kênh cố định.
// Theo "Đặc tả định dạng dữ liệu" v0.1:
//   - KHÔNG gửi dữ liệu đo lên laptop,
//   - chỉ in dòng BOOT khi khởi động và lặp lại mỗi 30 giây (mục 3.1).
// Ngoài ra: gửi lại (echo) mọi gói UDP mà #2 gửi tới, để #2 đo CSI từ gói trả lời
// (~100 gói/giây; thay cho ping – xem README).
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_wifi.h"
#include "esp_system.h"
#if __has_include("esp_mac.h")
#include "esp_mac.h"
#endif

#define FW_VERSION "0.1"

const char* AP_SSID    = "csi_ap";
const char* AP_PASS    = "csi12345";
const int   AP_CHANNEL = 6;          // đổi thành kênh ít AP nhất
const int   UDP_PORT   = 5000;
const uint32_t BOOT_PERIOD_MS = 30000;

WiFiUDP udp;
uint8_t buf[64];
char macSta[18], macAp[18];

static void macToStr(const uint8_t* m, char* out) {
  snprintf(out, 18, "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
}

static void printBoot() {
  // BOOT,<board>,<fw>,<mac_sta>,<mac_ap>,<channel>
  Serial.printf("BOOT,TX,%s,%s,%s,%d\n", FW_VERSION, macSta, macAp, AP_CHANNEL);
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS, AP_CHANNEL, 0, 2);
  esp_wifi_set_bandwidth(WIFI_IF_AP, WIFI_BW_HT20);   // 20 MHz → 64 sóng mang con
  WiFi.setSleep(false);
  udp.begin(UDP_PORT);

  uint8_t m[6];
  esp_read_mac(m, ESP_MAC_WIFI_STA);  macToStr(m, macSta);
  esp_wifi_get_mac(WIFI_IF_AP, m);    macToStr(m, macAp);   // = BSSID mà #2 dùng để lọc CSI
  printBoot();
}

void loop() {
  static uint32_t tBoot = millis();
  int len = udp.parsePacket();
  if (len > 0) {
    int n = udp.read(buf, sizeof(buf));
    udp.beginPacket(udp.remoteIP(), udp.remotePort());
    udp.write(buf, n);
    udp.endPacket();
  }
  if (millis() - tBoot >= BOOT_PERIOD_MS) {
    tBoot = millis();
    printBoot();
  }
}
