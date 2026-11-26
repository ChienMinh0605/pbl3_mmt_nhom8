#pragma once

#include <stdint.h>
#include "cJSON.h"

cJSON *sniffer_record(unsigned version, const char *type, int64_t ts_us);
cJSON *sniffer_config_reply(void);
void sniffer_emit(cJSON *record);
void sniffer_add_uart_status(cJSON *record);
