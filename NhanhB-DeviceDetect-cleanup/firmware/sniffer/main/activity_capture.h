#pragma once

#include <stdint.h>
#include "esp_err.h"

esp_err_t activity_capture_start(uint8_t channel, uint8_t min_channel, uint8_t max_channel);
