#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ACTIVITY_MAC_LEN 6
#define ACTIVITY_MAX_DEVICES 16

typedef enum {
    ACTIVITY_MANAGEMENT,
    ACTIVITY_CONTROL,
    ACTIVITY_DATA,
    ACTIVITY_MISC,
    ACTIVITY_FRAME_KIND_COUNT
} activity_frame_kind_t;

typedef struct {
    const uint8_t *transmitter;
    const uint8_t *receiver;
    const uint8_t *source;
    const uint8_t *destination;
    bool block_ack;
} activity_addresses_t;

typedef struct {
    uint8_t macs[ACTIVITY_MAX_DEVICES][ACTIVITY_MAC_LEN];
    size_t count;
} activity_registry_t;

// header_len excludes the FCS. Returned pointers are only valid during the callback.
activity_addresses_t activity_frame_addresses(activity_frame_kind_t kind,
                                               const uint8_t *header, size_t header_len);
bool activity_registry_parse(activity_registry_t *registry, const char *csv);
int activity_registry_find(const activity_registry_t *registry, const uint8_t *mac);
