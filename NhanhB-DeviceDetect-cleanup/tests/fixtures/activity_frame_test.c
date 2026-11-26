#include "activity_frame.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t header[36];

static void test_data_and_management(void)
{
    static const unsigned source_offsets[] = {10, 10, 16, 24};
    static const unsigned destination_offsets[] = {4, 16, 4, 16};
    header[0] = 0x08;
    for (unsigned ds = 0; ds < 4; ++ds) {
        header[1] = ds;
        const size_t len = ds == 3 ? 30 : 24;
        activity_addresses_t addresses = activity_frame_addresses(ACTIVITY_DATA, header, len);
        assert(addresses.transmitter == header + 10 && addresses.receiver == header + 4);
        assert(addresses.source == header + source_offsets[ds]);
        assert(addresses.destination == header + destination_offsets[ds]);
        assert(!activity_frame_addresses(ACTIVITY_DATA, header, len - 1).transmitter);
    }

    header[0] = 0x88; // Four-address QoS Data with HT Control.
    header[1] = 0x83;
    assert(activity_frame_addresses(ACTIVITY_DATA, header, 36).transmitter == header + 10);
    assert(!activity_frame_addresses(ACTIVITY_DATA, header, 35).transmitter);

    header[0] = 0x40; // Probe Request.
    header[1] = 0;
    activity_addresses_t addresses = activity_frame_addresses(ACTIVITY_MANAGEMENT, header, 24);
    assert(addresses.source == header + 10 && addresses.destination == header + 4);
    assert(!activity_frame_addresses(ACTIVITY_DATA, header, 24).source); // Wrong SDK kind.
    header[1] = 1;
    assert(!activity_frame_addresses(ACTIVITY_MANAGEMENT, header, 24).source);
}

static void test_controls(void)
{
    header[1] = 0;
    for (unsigned subtype = 8; subtype <= 15; ++subtype) {
        header[0] = (uint8_t)((subtype << 4) | 4);
        bool receiver_only = subtype == 12 || subtype == 13;
        size_t length = receiver_only ? 10 : subtype <= 9 ? 18 : 16;
        activity_addresses_t addresses = activity_frame_addresses(ACTIVITY_CONTROL, header, length);
        assert(addresses.receiver == header + 4);
        assert(addresses.transmitter == (receiver_only ? NULL : header + 10));
        assert(!addresses.source && !addresses.destination);
        assert(addresses.block_ack == (subtype == 9));
        assert(!activity_frame_addresses(ACTIVITY_CONTROL, header, length - 1).receiver);
    }
    header[0] = 0x74; // Control Wrapper is outside the supported address layouts.
    assert(!activity_frame_addresses(ACTIVITY_CONTROL, header, 36).receiver);
    assert(!activity_frame_addresses(ACTIVITY_MISC, NULL, 1500).receiver);
    assert(!activity_frame_addresses(ACTIVITY_CONTROL, NULL, 0).receiver);
}

static void test_registry(void)
{
    activity_registry_t registry;
    assert(activity_registry_parse(&registry, "") && registry.count == 0);
    assert(activity_registry_parse(&registry, "02:11:22:33:44:55,8A:bb:cc:dd:ee:ff"));
    assert(registry.count == 2);
    memcpy(header + 4, registry.macs[0], ACTIVITY_MAC_LEN);
    memcpy(header + 10, registry.macs[1], ACTIVITY_MAC_LEN);
    memset(header + 16, 0xff, ACTIVITY_MAC_LEN);
    header[0] = 0x08;
    header[1] = 2;
    activity_addresses_t downlink = activity_frame_addresses(ACTIVITY_DATA, header, 24);
    assert(activity_registry_find(&registry, downlink.receiver) == 0);
    assert(activity_registry_find(&registry, downlink.transmitter) == 1);
    assert(activity_registry_find(&registry, downlink.source) == -1);
    assert(activity_registry_find(&registry, NULL) == -1);

    static const char *const invalid[] = {
        "", "02", "02:11:22:33:44:5", "02:11:22:33:44:55,", "00:00:00:00:00:00",
        "ff:ff:ff:ff:ff:ff", "03:11:22:33:44:55", "02:11:22:33:44:5g",
        "02:11:22:33:44:55,02:11:22:33:44:55",
    };
    for (size_t i = 1; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        assert(!activity_registry_parse(&registry, invalid[i]));
        assert(registry.count == 2);
    }
    char oversized[(ACTIVITY_MAX_DEVICES + 1) * 18];
    for (size_t i = 0; i <= ACTIVITY_MAX_DEVICES; ++i) {
        snprintf(oversized + i * 18, 18, "02:11:22:33:44:%02x", (unsigned)i);
        if (i < ACTIVITY_MAX_DEVICES) oversized[i * 18 + 17] = ',';
    }
    assert(!activity_registry_parse(&registry, oversized));
}

int main(void)
{
    test_data_and_management();
    test_controls();
    test_registry();
    return 0;
}
