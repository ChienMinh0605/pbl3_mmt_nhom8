#include "activity_frame.h"

#include <string.h>

enum { ADDR1 = 4, ADDR2 = 10, ADDR3 = 16, ADDR4 = 24 };

static activity_addresses_t control_addresses(const uint8_t *header, size_t len, unsigned subtype)
{
    activity_addresses_t addresses = {0};
    switch (subtype) {
    case 12: // CTS
    case 13: // ACK
        if (len >= 10) addresses.receiver = header + ADDR1;
        break;
    case 8:  // Block Ack Request
    case 9:  // Block Ack
        if (len < 18) break; // Two addresses and at least the BAR/BA Control field.
        addresses.block_ack = subtype == 9;
        addresses.receiver = header + ADDR1;
        addresses.transmitter = header + ADDR2;
        break;
    case 10: // PS-Poll: BSSID (receiver), TA
    case 11: // RTS: RA, TA
    case 14: // CF-End: RA, BSSID (transmitting AP)
    case 15: // CF-End + CF-Ack: RA, BSSID (transmitting AP)
        if (len < 16) break;
        addresses.receiver = header + ADDR1;
        addresses.transmitter = header + ADDR2;
        break;
    }
    return addresses;
}

activity_addresses_t activity_frame_addresses(activity_frame_kind_t kind,
                                               const uint8_t *header, size_t header_len)
{
    activity_addresses_t addresses = {0};
    if (kind >= ACTIVITY_MISC || !header || header_len < 2) return addresses;
    if ((header[0] & 3) != 0 || ((header[0] >> 2) & 3) != (unsigned)kind) return addresses;

    unsigned subtype = header[0] >> 4;
    unsigned ds = header[1] & 3; // bit 0 To DS, bit 1 From DS
    if (kind == ACTIVITY_CONTROL) {
        return ds == 0 ? control_addresses(header, header_len, subtype) : addresses;
    }
    if (kind == ACTIVITY_MANAGEMENT && ds != 0) return addresses;

    size_t required = ds == 3 ? 30 : 24;
    if (kind == ACTIVITY_DATA && (subtype & 8)) {
        required += 2; // QoS Control
        if (header[1] & 0x80) required += 4; // HT Control
    }
    if (kind == ACTIVITY_MANAGEMENT && (header[1] & 0x80)) required += 4;
    if (header_len < required) return addresses;

    addresses.receiver = header + ADDR1;
    addresses.transmitter = header + ADDR2;
    addresses.source = header + (ds == 3 ? ADDR4 : ds == 2 ? ADDR3 : ADDR2);
    addresses.destination = header + ((ds & 1) ? ADDR3 : ADDR1);
    return addresses;
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int activity_registry_find(const activity_registry_t *registry, const uint8_t *mac)
{
    if (!mac || (mac[0] & 1)) return -1;
    for (size_t i = 0; i < registry->count; ++i) {
        if (memcmp(registry->macs[i], mac, ACTIVITY_MAC_LEN) == 0) return (int)i;
    }
    return -1;
}

bool activity_registry_parse(activity_registry_t *registry, const char *csv)
{
    activity_registry_t parsed = {0};
    while (*csv) {
        if (parsed.count == ACTIVITY_MAX_DEVICES) return false;
        uint8_t *mac = parsed.macs[parsed.count];
        unsigned nonzero = 0;
        for (size_t i = 0; i < ACTIVITY_MAC_LEN; ++i) {
            int high = hex_value(*csv++);
            if (high < 0) return false;
            int low = hex_value(*csv++);
            if (low < 0) return false;
            mac[i] = (uint8_t)((high << 4) | low);
            nonzero |= mac[i];
            if (i + 1 < ACTIVITY_MAC_LEN && *csv++ != ':') return false;
        }
        if (!nonzero || (mac[0] & 1) || activity_registry_find(&parsed, mac) >= 0) return false;
        ++parsed.count;
        if (!*csv) break;
        if (*csv++ != ',' || !*csv) return false;
    }
    *registry = parsed;
    return true;
}
