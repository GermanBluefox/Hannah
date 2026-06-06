#pragma once
#include <stdint.h>
#include <stdbool.h>

#define HANNAH_SD_MOUNT_POINT "/sdcard"

void     hannah_sd_init(void);
bool     hannah_sd_is_ready(void);
uint64_t hannah_sd_get_size_mb(void);
