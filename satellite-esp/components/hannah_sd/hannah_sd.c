#include "hannah_sd.h"
#include "esp_log.h"

static const char *TAG = "sd";

#if CONFIG_HANNAH_SD_ENABLED

#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"
#include "driver/sdspi_host.h"
#include "driver/spi_common.h"

static sdmmc_card_t *s_card  = NULL;
static bool          s_ready = false;

void hannah_sd_init(void)
{
    spi_bus_config_t bus_cfg = {
        .mosi_io_num     = CONFIG_HANNAH_SD_MOSI_GPIO,
        .miso_io_num     = CONFIG_HANNAH_SD_MISO_GPIO,
        .sclk_io_num     = CONFIG_HANNAH_SD_CLK_GPIO,
        .quadwp_io_num   = -1,
        .quadhd_io_num   = -1,
        .max_transfer_sz = 4000,
    };

    esp_err_t ret = spi_bus_initialize(SPI2_HOST, &bus_cfg, SDSPI_DEFAULT_DMA);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "SPI-Bus-Fehler: %s", esp_err_to_name(ret));
        return;
    }

    sdmmc_host_t host         = SDSPI_HOST_DEFAULT();
    host.slot                 = SPI2_HOST;

    sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot.gpio_cs               = CONFIG_HANNAH_SD_CS_GPIO;
    slot.host_id               = SPI2_HOST;

    esp_vfs_fat_sdmmc_mount_config_t mount_cfg = {
        .format_if_mount_failed = false,
        .max_files              = 5,
        .allocation_unit_size   = 16 * 1024,
    };

    ret = esp_vfs_fat_sdspi_mount(HANNAH_SD_MOUNT_POINT, &host, &slot, &mount_cfg, &s_card);
    if (ret != ESP_OK) {
        if (ret == ESP_FAIL)
            ESP_LOGE(TAG, "SD-Karte: FAT-Dateisystem nicht lesbar");
        else
            ESP_LOGE(TAG, "SD-Karte nicht gefunden: %s", esp_err_to_name(ret));
        spi_bus_free(SPI2_HOST);
        return;
    }

    s_ready = true;
    ESP_LOGI(TAG, "SD eingebunden unter %s (%" PRIu64 " MB)",
             HANNAH_SD_MOUNT_POINT, hannah_sd_get_size_mb());
}

bool hannah_sd_is_ready(void)
{
    return s_ready;
}

uint64_t hannah_sd_get_size_mb(void)
{
    if (!s_card) return 0;
    return (uint64_t)s_card->csd.capacity * s_card->csd.sector_size / (1024ULL * 1024ULL);
}

#else

void     hannah_sd_init(void)        {}
bool     hannah_sd_is_ready(void)    { return false; }
uint64_t hannah_sd_get_size_mb(void) { return 0; }

#endif /* CONFIG_HANNAH_SD_ENABLED */
