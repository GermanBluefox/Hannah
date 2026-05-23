/**
 * hannah_ota — periodischer Firmware-Update-Check
 *
 * Ablauf:
 *   1. 60 Sekunden warten (WiFi + MQTT-Verbindung abwarten)
 *   2. GET {ota_url}/latest mit Bearer-Token
 *   3. Aktuelle Version mit Firmware-Version vergleichen
 *   4. Bei Unterschied: hannah/<device>/ota/pending publizieren
 *   5. Auf hannah/<device>/ota/ok warten → esp_https_ota + Neustart
 *   6. Alle HANNAH_OTA_POLL_INTERVAL_S Sekunden wiederholen
 */

#include "hannah_ota.h"
#include "hannah_net.h"
#include "hannah_config.h"

#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "esp_app_desc.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "cJSON.h"

static const char *TAG = "ota";

#define OTA_HTTP_BUF_SIZE   512
#define OTA_STARTUP_DELAY_S 60

/* Thawte TLS RSA CA G1 — Intermediate-CA für hannah-update.sgessinger.de */
static const char s_ca_cert_pem[] =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIEizCCA3OgAwIBAgIQCQ7oxd5b+mLSri/3CXxIVzANBgkqhkiG9w0BAQsFADBh\n"
    "MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3\n"
    "d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH\n"
    "MjAeFw0xNzExMDIxMjI0MjVaFw0yNzExMDIxMjI0MjVaMF4xCzAJBgNVBAYTAlVT\n"
    "MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j\n"
    "b20xHTAbBgNVBAMTFFRoYXd0ZSBUTFMgUlNBIENBIEcxMIIBIjANBgkqhkiG9w0B\n"
    "AQEFAAOCAQ8AMIIBCgKCAQEAxjngmPhVetC0b/ozbYJdzOBUA1sMog47030cAP+P\n"
    "23ANUN8grXECL8NhDEF4F1R9tL0wY0mczHaR0a7lYanlxtwWo1s2uGnnyDs6mOCs\n"
    "66ew2w3YETr6Tb14xgjpu1gGFtAeewaikO9Fud8hxGJTSwn8xeNkfKVWpD2L4vFN\n"
    "36FNgxeilK6aE4ykgGAzNlokTp6hNOLAYpDySdLAPKzuJSQ7JCEZ6O+SDKywIdXL\n"
    "oMTnpxuBKGSG88NWTo3CHCOGmQECia2yqdPDjgLqnEiYNjwQL8uMqj8rOvlMgviB\n"
    "cHA7xty+7/uYLN6ZS7Vq1/F/lVhVOf5ej6jZdmB85szFbQIDAQABo4IBQDCCATww\n"
    "HQYDVR0OBBYEFKWM/jLM6w8s1BnGCLgAJIhdw8W3MB8GA1UdIwQYMBaAFE4iVCAY\n"
    "lebjbuYP+vq5Eu0GF485MA4GA1UdDwEB/wQEAwIBhjAdBgNVHSUEFjAUBggrBgEF\n"
    "BQcDAQYIKwYBBQUHAwIwEgYDVR0TAQH/BAgwBgEB/wIBADA0BggrBgEFBQcBAQQo\n"
    "MCYwJAYIKwYBBQUHMAGGGGh0dHA6Ly9vY3NwLmRpZ2ljZXJ0LmNvbTBCBgNVHR8E\n"
    "OzA5MDegNaAzhjFodHRwOi8vY3JsMy5kaWdpY2VydC5jb20vRGlnaUNlcnRHbG9i\n"
    "YWxSb290RzIuY3JsMD0GA1UdIAQ2MDQwMgYEVR0gADAqMCgGCCsGAQUFBwIBFhxo\n"
    "dHRwczovL3d3dy5kaWdpY2VydC5jb20vQ1BTMA0GCSqGSIb3DQEBCwUAA4IBAQC6\n"
    "km0KA4sTb2VYpEBm/uL2HL/pZX9B7L/hbJ4NcoBe7V56oCnt7aeIo8sMjCRWTCWZ\n"
    "D1dY0+2KZOC1dKj8d1VXXAtnjytDDuPPf6/iow0mYQTO/GAg/MLyL6CDm3FzDB8V\n"
    "tsH/aeMgP6pgD1XQqz+haDnfnJTKBuxhcpnx3Adbleue/QnPf1hHYa8L+Rv8Pi5U\n"
    "h4V9FwHOfphdMXOxi14OqmsiTbc5cOs9/uukH+YVsuFdWTna6IVw1qh+tEtyH16R\n"
    "vmi7pkqyZYULOPMIE7avrljVVBZuikwARtY8tCVV6Pp9l3VeagBqb2ffgqNJt3C0\n"
    "TYNYQI+BXG1R1cABlold\n"
    "-----END CERTIFICATE-----\n";

static char s_response_buf[OTA_HTTP_BUF_SIZE];
static int  s_response_len = 0;
static char s_pending_url[192];
static SemaphoreHandle_t s_ota_sem;

/* ── HTTP-Event-Handler ───────────────────────────────────────────────────── */

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    if (evt->event_id == HTTP_EVENT_ON_DATA) {
        int copy = evt->data_len;
        int remaining = (int)sizeof(s_response_buf) - 1 - s_response_len;
        if (copy > remaining) copy = remaining;
        if (copy > 0) {
            memcpy(s_response_buf + s_response_len, evt->data, copy);
            s_response_len += copy;
        }
    }
    return ESP_OK;
}

/* ── Update-Check ─────────────────────────────────────────────────────────── */

static void check_for_update(void)
{
    const hannah_config_t *cfg = hannah_config_get();

    if (cfg->ota_url[0] == '\0') {
        ESP_LOGD(TAG, "Kein OTA-URL konfiguriert — überspringe Check.");
        return;
    }

    char url[192];
    snprintf(url, sizeof(url), "%s/latest", cfg->ota_url);

    char auth_header[192];
    snprintf(auth_header, sizeof(auth_header), "Bearer %s", cfg->ota_token);

    s_response_len = 0;
    memset(s_response_buf, 0, sizeof(s_response_buf));

    esp_http_client_config_t http_cfg = {
        .url           = url,
        .event_handler = http_event_handler,
        .cert_pem      = s_ca_cert_pem,
        .timeout_ms    = 10000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&http_cfg);
    if (!client) {
        ESP_LOGE(TAG, "http_client_init fehlgeschlagen.");
        return;
    }

    esp_http_client_set_header(client, "Authorization", auth_header);

    esp_err_t err = esp_http_client_perform(client);
    int status    = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    if (err != ESP_OK) {
        ESP_LOGW(TAG, "OTA-HTTP-Fehler: %s", esp_err_to_name(err));
        return;
    }
    if (status != 200) {
        ESP_LOGW(TAG, "OTA-Server antwortete mit HTTP %d.", status);
        return;
    }

    s_response_buf[s_response_len] = '\0';
    ESP_LOGD(TAG, "OTA-Antwort: %s", s_response_buf);

    cJSON *root = cJSON_Parse(s_response_buf);
    if (!root) {
        ESP_LOGW(TAG, "OTA: JSON-Parse fehlgeschlagen.");
        return;
    }

    const cJSON *jver = cJSON_GetObjectItemCaseSensitive(root, "version");
    const cJSON *jurl = cJSON_GetObjectItemCaseSensitive(root, "url");
    if (!cJSON_IsString(jver) || !cJSON_IsString(jurl)) {
        ESP_LOGW(TAG, "OTA: Kein 'version'/'url'-Feld in Antwort.");
        cJSON_Delete(root);
        return;
    }

    const char *latest  = jver->valuestring;
    const char *current = esp_app_get_description()->version;

    ESP_LOGI(TAG, "Firmware: aktuell=%s  verfügbar=%s", current, latest);

    if (strcmp(latest, current) != 0) {
        strncpy(s_pending_url, jurl->valuestring, sizeof(s_pending_url) - 1);
        s_pending_url[sizeof(s_pending_url) - 1] = '\0';

        char payload[128];
        snprintf(payload, sizeof(payload),
                 "{\"version\":\"%s\",\"pending\":true}", latest);
        char topic[96];
        snprintf(topic, sizeof(topic), "hannah/%s/ota/pending", cfg->device_id);
        hannah_net_mqtt_publish(topic, payload, 1, 0);
        ESP_LOGI(TAG, "OTA-pending publiziert → %s: %s", topic, payload);
    } else {
        ESP_LOGI(TAG, "Firmware ist aktuell.");
    }

    cJSON_Delete(root);
}

/* ── OTA-Flash ────────────────────────────────────────────────────────────── */

static esp_err_t ota_http_init_cb(esp_http_client_handle_t client)
{
    const hannah_config_t *cfg = hannah_config_get();
    char auth[192];
    snprintf(auth, sizeof(auth), "Bearer %s", cfg->ota_token);
    return esp_http_client_set_header(client, "Authorization", auth);
}

static void ota_update_task(void *arg)
{
    while (1) {
        xSemaphoreTake(s_ota_sem, portMAX_DELAY);

        if (s_pending_url[0] == '\0') {
            ESP_LOGW(TAG, "OTA-OK empfangen, aber keine URL bekannt.");
            continue;
        }

        ESP_LOGI(TAG, "Starte OTA von %s", s_pending_url);

        esp_http_client_config_t http_cfg = {
            .url            = s_pending_url,
            .cert_pem       = s_ca_cert_pem,
            .timeout_ms     = 60000,
            .keep_alive_enable = true,
        };
        esp_https_ota_config_t ota_cfg = {
            .http_config          = &http_cfg,
            .http_client_init_cb  = ota_http_init_cb,
        };

        esp_err_t err = esp_https_ota(&ota_cfg);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "OTA erfolgreich — Neustart.");
            esp_restart();
        } else {
            ESP_LOGE(TAG, "OTA fehlgeschlagen: %s", esp_err_to_name(err));
        }
    }
}

/* ── Callbacks ────────────────────────────────────────────────────────────── */

static void on_ota_ok(void)
{
    ESP_LOGI(TAG, "OTA-Freigabe (ota/ok) empfangen — starte Update.");
    xSemaphoreGive(s_ota_sem);
}

/* ── Task ─────────────────────────────────────────────────────────────────── */

static void ota_poll_task(void *arg)
{
    ESP_LOGI(TAG, "Warte %ds auf WiFi/MQTT...", OTA_STARTUP_DELAY_S);
    vTaskDelay(pdMS_TO_TICKS(OTA_STARTUP_DELAY_S * 1000));

    while (1) {
        check_for_update();
        vTaskDelay(pdMS_TO_TICKS((uint32_t)CONFIG_HANNAH_OTA_POLL_INTERVAL_S * 1000));
    }
}

/* ── Öffentliche API ─────────────────────────────────────────────────────── */

void hannah_ota_init(void)
{
    s_ota_sem = xSemaphoreCreateBinary();
    hannah_net_set_ota_ok_callback(on_ota_ok);
    xTaskCreate(ota_poll_task,   "ota_poll",   12288, NULL, 3, NULL);
    xTaskCreate(ota_update_task, "ota_update", 8192,  NULL, 5, NULL);
    ESP_LOGI(TAG, "OTA-Check aktiv (Erstprüfung in %ds, Intervall %ds).",
             OTA_STARTUP_DELAY_S, CONFIG_HANNAH_OTA_POLL_INTERVAL_S);
}
