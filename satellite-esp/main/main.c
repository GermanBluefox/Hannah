/**
 * Hannah Satellite — ESP32-S3
 *
 * Pin-Übersicht: main/pinmap.h
 */

#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"
#include "driver/gpio.h"

#include "hannah_config.h"
#include "hannah_net.h"
#include "hannah_audio.h"
#include "hannah_led.h"
#include "hannah_sensors.h"
#include "hannah_webserver.h"
#include "hannah_ota.h"
#include "hannah_ble.h"

static const char *TAG = "main";

/* Mute beim Start gedrückt halten → WiFi-Einstellungen löschen → AP-Modus */
static void check_factory_reset(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << CONFIG_HANNAH_MUTE_GPIO),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    vTaskDelay(pdMS_TO_TICKS(50));

    if (gpio_get_level(CONFIG_HANNAH_MUTE_GPIO) == 0) {
        ESP_LOGW(TAG, "*** Factory Reset: Mute beim Start gedrückt ***");
        ESP_LOGW(TAG, "*** WiFi-Einstellungen werden gelöscht — startet im AP-Modus ***");
        nvs_handle_t h;
        if (nvs_open("hannah", NVS_READWRITE, &h) == ESP_OK) {
            nvs_set_str(h, "wifi_ssid", "");
            nvs_set_str(h, "wifi_pass", "");
            nvs_commit(h);
            nvs_close(h);
        }
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Hannah Satellite starting...");

    /* NVS initialisieren (wird von hannah_config und WiFi-Stack genutzt) */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /* Mute beim Start gedrückt? → WiFi löschen → AP-Modus */
    check_factory_reset();

    /* Konfiguration aus NVS laden (sdkconfig-Defaults beim Erststart) */
    hannah_config_init();

    /* LED-Ring — sofort visuelles Feedback */
    hannah_led_init();
    hannah_led_set_state(LED_STATE_BOOT);

    /* Netzwerk: STA wenn Config vorhanden, sonst AP-Setup-Modus */
    hannah_net_init();

    /* Webserver — immer aktiv (STA: erreichbar über LAN-IP, AP: 192.168.4.1) */
    hannah_webserver_start();

    /* Audio-Pipeline */
    hannah_audio_init();

    /* Sensoren */
    hannah_sensors_init();

    /* OTA-Update-Check (Poll im Hintergrund, kein Flash-Vorgang) */
    hannah_ota_init();

    /* BLE-Scanner für Indoor-Lokalisierung */
    hannah_ble_init();

    /* LED bleibt in BOOT — hannah_audio mic_task setzt LED_STATE_IDLE nach Warmup */
    ESP_LOGI(TAG, "All components initialized.");
}
