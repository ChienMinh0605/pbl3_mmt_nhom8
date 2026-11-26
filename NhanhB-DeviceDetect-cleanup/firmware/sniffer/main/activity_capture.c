#include "activity_capture.h"

#include "activity_frame.h"
#include "sniffer_wire.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/uart.h"
#include "nvs.h"
#include <stdio.h>
#include <string.h>

#define MODE "DEVICE_ACTIVITY_FIXED_CHANNEL"
#define UNATTRIBUTED ACTIVITY_MAX_DEVICES

typedef struct {
    uint32_t frames, bytes, tx_frames, rx_frames, block_acks;
    int8_t rssi_max;
} activity_counts_t;

typedef struct {
    uint32_t callbacks, invalid, unattributed, unregistered, off_channel;
    uint32_t frames_by_kind[ACTIVITY_FRAME_KIND_COUNT];
} activity_totals_t;

typedef struct {
    int64_t start_us;
    activity_counts_t counts[ACTIVITY_MAX_DEVICES + 1][ACTIVITY_FRAME_KIND_COUNT];
} activity_window_t;

static activity_registry_t registry;
static portMUX_TYPE window_lock = portMUX_INITIALIZER_UNLOCKED;
static activity_totals_t totals;
static activity_window_t windows[2];
static activity_window_t *active = &windows[0];
static uint8_t router_channel, channel_min, channel_max;
static uint32_t registry_revision;
static bool reconfiguring;
static QueueHandle_t commands;

typedef struct {
    uint32_t version, revision;
    uint8_t channel, count;
    uint8_t macs[ACTIVITY_MAX_DEVICES][ACTIVITY_MAC_LEN];
} saved_config_t;

static bool permitted_channel(int channel)
{
    return channel >= channel_min && channel <= channel_max;
}

static void normalize_registry(activity_registry_t *list)
{
    for (size_t i = 1; i < list->count; ++i) {
        for (size_t j = i; j > 0 && memcmp(list->macs[j - 1], list->macs[j], ACTIVITY_MAC_LEN) > 0; --j) {
            uint8_t tmp[ACTIVITY_MAC_LEN];
            memcpy(tmp, list->macs[j], sizeof(tmp));
            memcpy(list->macs[j], list->macs[j - 1], sizeof(tmp));
            memcpy(list->macs[j - 1], tmp, sizeof(tmp));
        }
    }
}

static esp_err_t persist_config(const activity_registry_t *list, uint8_t channel, uint32_t revision)
{
    saved_config_t saved = {.version = 1, .revision = revision, .channel = channel, .count = list->count};
    memcpy(saved.macs, list->macs, sizeof(saved.macs));
    nvs_handle_t nvs;
    esp_err_t result = nvs_open("device_activity", NVS_READWRITE, &nvs);
    if (result != ESP_OK) return result;
    result = nvs_set_blob(nvs, "config", &saved, sizeof(saved));
    if (result == ESP_OK) result = nvs_commit(nvs);
    nvs_close(nvs);
    return result;
}

static void restore_config(void)
{
    nvs_handle_t nvs;
    if (nvs_open("device_activity", NVS_READONLY, &nvs) != ESP_OK) return;
    saved_config_t saved;
    size_t size = sizeof(saved);
    esp_err_t result = nvs_get_blob(nvs, "config", &saved, &size);
    nvs_close(nvs);
    if (result != ESP_OK || size != sizeof(saved) || saved.version != 1 ||
        !permitted_channel(saved.channel) || saved.count > ACTIVITY_MAX_DEVICES) return;
    // Apply the same validation as the build-time fallback.
    char csv[ACTIVITY_MAX_DEVICES * 18 + 1] = {0};
    for (size_t i = 0; i < saved.count; ++i) {
        snprintf(csv + i * 18, sizeof(csv) - i * 18, MACSTR "%s",
                 MAC2STR(saved.macs[i]), i + 1 == saved.count ? "" : ",");
    }
    if (activity_registry_parse(&registry, csv)) {
        normalize_registry(&registry);
        router_channel = saved.channel;
        registry_revision = saved.revision;
    }
}

static void record_frame(activity_counts_t *counts, const wifi_pkt_rx_ctrl_t *rx,
                         bool tx, bool received, bool block_ack)
{
    if (!counts->frames || rx->rssi > counts->rssi_max) counts->rssi_max = rx->rssi;
    ++counts->frames;
    counts->bytes += rx->sig_len;
    counts->tx_frames += tx;
    counts->rx_frames += received;
    counts->block_acks += block_ack;
}

static bool unicast_mac(const uint8_t *mac)
{
    static const uint8_t zero[ACTIVITY_MAC_LEN] = {0};
    return mac && !(mac[0] & 1) && memcmp(mac, zero, sizeof(zero)) != 0;
}

static void receive_activity(void *buf, wifi_promiscuous_pkt_type_t type)
{
    if (!buf) return;
    const wifi_promiscuous_pkt_t *packet = buf;
    const wifi_pkt_rx_ctrl_t *rx = &packet->rx_ctrl;
    static const activity_frame_kind_t kinds[] = {
        [WIFI_PKT_MGMT] = ACTIVITY_MANAGEMENT, [WIFI_PKT_CTRL] = ACTIVITY_CONTROL,
        [WIFI_PKT_DATA] = ACTIVITY_DATA, [WIFI_PKT_MISC] = ACTIVITY_MISC,
    };
    if ((unsigned)type >= sizeof(kinds) / sizeof(kinds[0])) return;
    const activity_frame_kind_t kind = kinds[type];
    const bool valid = rx->rx_state == 0 && rx->sig_len >= 4;
    activity_addresses_t addresses = {0};
    if (valid && kind != ACTIVITY_MISC) {
        addresses = activity_frame_addresses(kind, packet->payload, rx->sig_len - 4);
    }
    bool unattributed = !unicast_mac(addresses.transmitter) && !unicast_mac(addresses.receiver);

    portENTER_CRITICAL(&window_lock);
    if (reconfiguring) {
        portEXIT_CRITICAL(&window_lock);
        return;
    }
    const int tx = activity_registry_find(&registry, addresses.transmitter);
    const int receiver = activity_registry_find(&registry, addresses.receiver);
    ++totals.callbacks;
    if (valid && rx->channel == router_channel) ++totals.frames_by_kind[kind];
    if (!valid) {
        ++totals.invalid;
    } else if (rx->channel != router_channel) {
        ++totals.off_channel;
    } else if (unattributed) {
        ++totals.unattributed;
        record_frame(&active->counts[UNATTRIBUTED][kind], rx, false, false, addresses.block_ack);
    } else if (tx < 0 && receiver < 0) {
        ++totals.unregistered;
    } else {
        if (tx >= 0) {
            record_frame(&active->counts[tx][kind], rx, true, receiver == tx, addresses.block_ack);
        }
        if (receiver >= 0 && receiver != tx) {
            record_frame(&active->counts[receiver][kind], rx, false, true, addresses.block_ack);
        }
    }
    portEXIT_CRITICAL(&window_lock);
}

static void emit_activity(const activity_window_t *window, int64_t end_us, size_t device,
                          activity_frame_kind_t kind)
{
    static const char *const names[] = {"management", "control", "data", "misc"};
    const activity_counts_t *counts = &window->counts[device][kind];
    if (!counts->frames) return;
    cJSON *record = sniffer_record(2, "activity_sample", window->start_us);
    if (record) {
        if (device == UNATTRIBUTED) {
            cJSON_AddNullToObject(record, "source_mac");
        } else {
            char mac[18];
            snprintf(mac, sizeof(mac), MACSTR, MAC2STR(registry.macs[device]));
            cJSON_AddStringToObject(record, "source_mac", mac);
        }
        cJSON_AddStringToObject(record, "attribution", device == UNATTRIBUTED ? "unattributed" : "registered");
        cJSON_AddStringToObject(record, "frame_kind", names[kind]);
        cJSON_AddNumberToObject(record, "duration_us", (double)(end_us - window->start_us));
        cJSON_AddNumberToObject(record, "channel", router_channel);
        cJSON_AddNumberToObject(record, "registry_revision", registry_revision);
        cJSON_AddNumberToObject(record, "n_frames", counts->frames);
        cJSON_AddNumberToObject(record, "n_bytes", counts->bytes);
        cJSON_AddNumberToObject(record, "tx_frames", counts->tx_frames);
        cJSON_AddNumberToObject(record, "rx_frames", counts->rx_frames);
        cJSON_AddNumberToObject(record, "block_ack_frames", counts->block_acks);
        cJSON_AddNumberToObject(record, "rssi_max_dbm", counts->rssi_max);
    }
    sniffer_emit(record);
}

static void emit_status(const activity_totals_t *snapshot, int64_t now)
{
    cJSON *record = sniffer_record(2, "status", now);
    if (record) {
        cJSON_AddStringToObject(record, "mode", MODE);
        cJSON_AddBoolToObject(record, "capture_active", !reconfiguring);
        cJSON_AddBoolToObject(record, "runtime_config", true);
        cJSON_AddNumberToObject(record, "channel_min", channel_min);
        cJSON_AddNumberToObject(record, "channel_max", channel_max);
        cJSON_AddNumberToObject(record, "channel", router_channel);
        cJSON_AddNumberToObject(record, "registry_revision", registry_revision);
        cJSON_AddStringToObject(record, "scan_mode", "fixed");
        cJSON_AddNumberToObject(record, "registered_devices", registry.count);
        cJSON_AddNumberToObject(record, "rx_callbacks", snapshot->callbacks);
        cJSON_AddNumberToObject(record, "invalid_frames", snapshot->invalid);
        cJSON_AddNumberToObject(record, "off_channel_frames", snapshot->off_channel);
        cJSON_AddNumberToObject(record, "unattributed_frames", snapshot->unattributed);
        cJSON_AddNumberToObject(record, "unregistered_frames", snapshot->unregistered);
        cJSON_AddNumberToObject(record, "management_frames", snapshot->frames_by_kind[ACTIVITY_MANAGEMENT]);
        cJSON_AddNumberToObject(record, "data_frames", snapshot->frames_by_kind[ACTIVITY_DATA]);
        cJSON_AddNumberToObject(record, "control_frames", snapshot->frames_by_kind[ACTIVITY_CONTROL]);
        sniffer_add_uart_status(record);
    }
    sniffer_emit(record);
}

static void emit_channel(int64_t tick)
{
    cJSON *record = sniffer_record(2, "channel", tick);
    if (record) {
        cJSON_AddStringToObject(record, "mode", MODE);
        cJSON_AddStringToObject(record, "scan_mode", "fixed");
        cJSON_AddNumberToObject(record, "channel", router_channel);
        cJSON_AddNumberToObject(record, "registry_revision", registry_revision);
    }
    sniffer_emit(record);
}

static bool parse_macs(const cJSON *array, activity_registry_t *list)
{
    if (!cJSON_IsArray(array) || cJSON_GetArraySize(array) > ACTIVITY_MAX_DEVICES) return false;
    char csv[ACTIVITY_MAX_DEVICES * 18 + 1] = {0};
    size_t offset = 0;
    const cJSON *item;
    cJSON_ArrayForEach(item, array) {
        if (!cJSON_IsString(item) || strlen(item->valuestring) != 17) return false;
        if (offset) csv[offset++] = ',';
        memcpy(csv + offset, item->valuestring, 17);
        offset += 17;
    }
    if (!activity_registry_parse(list, csv)) return false;
    normalize_registry(list);
    return true;
}

static void config_reply(const char *id, const char *error, bool include_registry)
{
    cJSON *record = sniffer_config_reply();
    if (record) {
        cJSON_AddStringToObject(record, "request_id", id);
        cJSON_AddBoolToObject(record, "ok", !error);
        if (error) cJSON_AddStringToObject(record, "error", error);
        cJSON_AddNumberToObject(record, "registry_revision", registry_revision);
        cJSON_AddNumberToObject(record, "channel", router_channel);
        cJSON_AddNumberToObject(record, "registered_devices", registry.count);
        cJSON_AddBoolToObject(record, "runtime_config", true);
        cJSON_AddNumberToObject(record, "channel_min", channel_min);
        cJSON_AddNumberToObject(record, "channel_max", channel_max);
        if (include_registry && !error) {
            cJSON *array = cJSON_AddArrayToObject(record, "macs");
            for (size_t i = 0; array && i < registry.count; ++i) {
                char mac[18];
                snprintf(mac, sizeof(mac), MACSTR, MAC2STR(registry.macs[i]));
                cJSON_AddItemToArray(array, cJSON_CreateString(mac));
            }
        }
    }
    sniffer_emit(record);
}

static const char *apply_config(const activity_registry_t *candidate, uint8_t channel)
{
    const bool move = channel != router_channel;
    if (move) {
        portENTER_CRITICAL(&window_lock);
        reconfiguring = true;
        portEXIT_CRITICAL(&window_lock);
    }
    esp_err_t result = move ? esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE) : ESP_OK;
    const char *error = result == ESP_OK ? NULL : "channel_apply_failed";
    if (!error && persist_config(candidate, channel, registry_revision + 1) != ESP_OK) {
        error = "nvs_write_failed";
    }
    if (error && move) {
        uint8_t actual;
        wifi_second_chan_t secondary;
        // Keep the previous revision. Reboot if the radio cannot restore its channel.
        if ((esp_wifi_get_channel(&actual, &secondary) != ESP_OK || actual != router_channel) &&
            esp_wifi_set_channel(router_channel, WIFI_SECOND_CHAN_NONE) != ESP_OK) esp_restart();
    }
    portENTER_CRITICAL(&window_lock);
    if (!error || move) {
        memset(active, 0, sizeof(*active));
        active->start_us = esp_timer_get_time();
    }
    if (!error) {
        registry = *candidate;
        router_channel = channel;
        ++registry_revision;
    }
    reconfiguring = false;
    portEXIT_CRITICAL(&window_lock);
    return error;
}

static bool handle_command(const cJSON *command)
{
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(command, "request_id");
    const cJSON *op = cJSON_GetObjectItemCaseSensitive(command, "command");
    const cJSON *version = cJSON_GetObjectItemCaseSensitive(command, "v");
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(command, "type");
    if (!cJSON_IsString(id) || !*id->valuestring || strlen(id->valuestring) > 64) return false;
    if (!cJSON_IsNumber(version) || version->valuedouble != 2 || !cJSON_IsString(type) ||
        strcmp(type->valuestring, "config_command") || !cJSON_IsString(op)) {
        config_reply(id->valuestring, "invalid_command", false);
        return false;
    }

    const char *name = op->valuestring;
    const char *error = NULL;
    bool boundary = false;
    bool get_registry = !strcmp(name, "get_registry");
    if (!strcmp(name, "get_status") || get_registry) {
        config_reply(id->valuestring, NULL, get_registry);
        return false;
    }

    activity_registry_t candidate = registry;
    uint8_t channel = router_channel;
    const cJSON *requested_channel = cJSON_GetObjectItemCaseSensitive(command, "channel");
    if (!strcmp(name, "set_channel") || (!strcmp(name, "set_registry") && requested_channel)) {
        if (!cJSON_IsNumber(requested_channel) || requested_channel->valuedouble != requested_channel->valueint ||
            !permitted_channel(requested_channel->valueint)) error = "invalid_channel";
        else channel = requested_channel->valueint;
    }
    if (!error) {
        if (!strcmp(name, "set_registry")) {
            if (!parse_macs(cJSON_GetObjectItemCaseSensitive(command, "macs"), &candidate)) error = "invalid_registry";
        } else if (!strcmp(name, "clear_registry")) {
            candidate = (activity_registry_t){0};
        } else if (strcmp(name, "set_channel")) {
            error = "unknown_command";
        }
    }
    if (!error && (channel != router_channel || candidate.count != registry.count ||
        memcmp(candidate.macs, registry.macs, registry.count * ACTIVITY_MAC_LEN))) {
        const bool moved = channel != router_channel;
        error = apply_config(&candidate, channel);
        boundary = !error || moved;
    }
    config_reply(id->valuestring, error, true);
    return boundary;
}

static void command_input(void *arg)
{
    (void)arg;
    char line[768];
    size_t length = 0;
    bool discard = false;
    uint8_t chunk[128];
    for (;;) {
        int count = uart_read_bytes(UART_NUM_0, chunk, sizeof(chunk), pdMS_TO_TICKS(100));
        for (int i = 0; i < count; ++i) {
            if (chunk[i] == '\n') {
                line[length] = 0;
                cJSON *command = discard ? NULL : cJSON_ParseWithOpts(line, NULL, true);
                if (command) xQueueSend(commands, &command, portMAX_DELAY);
                length = 0;
                discard = false;
            } else if (!discard) {
                if (length == sizeof(line) - 1 || chunk[i] == 0) discard = true;
                else line[length++] = chunk[i];
            }
        }
    }
}

static void activity_output(void *arg)
{
    (void)arg;
    emit_channel(active->start_us);
    activity_totals_t snapshot = {0};
    emit_status(&snapshot, active->start_us);

    activity_window_t *spare = &windows[1];
    int64_t next = active->start_us + 1000000;
    for (;;) {
        int64_t delay_us = next - esp_timer_get_time();
        TickType_t delay = delay_us > 0 ? pdMS_TO_TICKS((delay_us + 999) / 1000) : 0;
        cJSON *command;
        if (xQueueReceive(commands, &command, delay) == pdTRUE) {
            bool boundary = handle_command(command);
            cJSON_Delete(command);
            if (boundary) {
                portENTER_CRITICAL(&window_lock);
                snapshot = totals;
                int64_t now = active->start_us;
                portEXIT_CRITICAL(&window_lock);
                emit_channel(now);
                emit_status(&snapshot, now);
                next = now + 1000000;
            }
        }
        if (esp_timer_get_time() < next) continue;

        memset(spare, 0, sizeof(*spare));
        portENTER_CRITICAL(&window_lock);
        int64_t now = esp_timer_get_time();
        spare->start_us = now;
        activity_window_t *completed = active;
        active = spare;
        snapshot = totals;
        portEXIT_CRITICAL(&window_lock);

        for (int kind = 0; kind < ACTIVITY_FRAME_KIND_COUNT; ++kind) {
            for (size_t device = 0; device < registry.count; ++device) {
                emit_activity(completed, now, device, kind);
            }
            emit_activity(completed, now, UNATTRIBUTED, kind);
        }
        emit_status(&snapshot, now);
        spare = completed;
        next = now + 1000000;
    }
}

esp_err_t activity_capture_start(uint8_t channel, uint8_t min_channel, uint8_t max_channel)
{
    if (!activity_registry_parse(&registry, CONFIG_DEVICE_ACTIVITY_REGISTERED_MACS)) {
        fprintf(stderr, "Invalid DEVICE_ACTIVITY_REGISTERED_MACS\n");
        return ESP_ERR_INVALID_ARG;
    }
    router_channel = channel;
    channel_min = min_channel;
    channel_max = max_channel < 13 ? max_channel : 13;
    restore_config();
    if (!permitted_channel(router_channel)) return ESP_ERR_INVALID_ARG;
    ESP_ERROR_CHECK(esp_wifi_set_channel(router_channel, WIFI_SECOND_CHAN_NONE));
    commands = xQueueCreate(4, sizeof(cJSON *));
    if (!commands) return ESP_ERR_NO_MEM;
    const wifi_promiscuous_filter_t filters = {
        .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA |
                       WIFI_PROMIS_FILTER_MASK_CTRL | WIFI_PROMIS_FILTER_MASK_MISC,
    };
    const wifi_promiscuous_filter_t control = {.filter_mask = WIFI_PROMIS_CTRL_FILTER_MASK_ALL};
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filters));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_ctrl_filter(&control));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(receive_activity));
    active->start_us = esp_timer_get_time();
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    if (xTaskCreate(command_input, "activity_commands", 4096, NULL, 4, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    return xTaskCreate(activity_output, "activity_output", 6144, NULL, 4, NULL) == pdPASS
        ? ESP_OK : ESP_ERR_NO_MEM;
}
