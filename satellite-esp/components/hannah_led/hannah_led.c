/**
 * hannah_led — WS2812B-Ring Steuerung mit Animationen
 *
 * Jeder LED-State hat eine eigene Animation:
 *   BOOT   — weißes Lauflicht (einmal rum, dann IDLE)
 *   IDLE   — aus
 *   WAKE   — pulsierendes Blau
 *   STREAM — rotierendes Blau (lauscht)
 *   SPEAK  — grüner Atemeffekt
 *   MUTE   — statisches Rot
 *   ERROR  — schnell blinkendes Rot
 *
 * Der Animations-Task läuft mit 50 Hz (20ms-Tick).
 * Frame-Counter wird bei jedem State-Wechsel zurückgesetzt.
 */

#include "hannah_led.h"
#include "led_strip.h"
#include "esp_log.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>
#include <string.h>

#define LED_GPIO   CONFIG_HANNAH_LED_GPIO
#define LED_COUNT  CONFIG_HANNAH_LED_COUNT

/* Animations-Tick: 20ms → 50 Hz */
#define TICK_MS    20

static const char *TAG = "hannah_led";
static led_strip_handle_t   s_strip         = NULL;
static volatile led_state_t s_current_state = LED_STATE_IDLE;

/* ── Hilfsfunktionen ─────────────────────────────────────────────────────── */

static inline void set_all(uint8_t r, uint8_t g, uint8_t b)
{
    for (int i = 0; i < LED_COUNT; i++)
        led_strip_set_pixel(s_strip, i, r, g, b);
}

/* Gibt einen Helligkeitswert 0..255 für einen pulsierenden Sinus zurück.
 * period_frames: Dauer einer vollständigen Periode in Frames (bei 50Hz). */
static inline float pulse(uint32_t frame, uint32_t period_frames)
{
    return 0.5f + 0.5f * sinf(2.0f * (float)M_PI * (float)frame / (float)period_frames);
}

/* ── Render-Funktionen (eine pro State) ─────────────────────────────────── */

static void render_boot(uint32_t frame)
{
    /* Weißes Lauflicht: 1 heller Kern + Abfall auf beide Seiten */
    set_all(0, 0, 0);
    /* 1 Umlauf in ~1.4s: Position wechselt alle 6 Frames (120ms/LED) */
    uint32_t pos = (frame / 6) % LED_COUNT;
    for (int d = -2; d <= 2; d++) {
        int idx = ((int)pos + d + LED_COUNT) % LED_COUNT;
        uint8_t bright;
        switch (d < 0 ? -d : d) {
            case 0: bright = 80;  break;
            case 1: bright = 35;  break;
            default: bright = 10; break;
        }
        led_strip_set_pixel(s_strip, idx, bright, bright, bright);
    }
}

static void render_idle(void)
{
    set_all(0, 0, 0);
}

static void render_wake(uint32_t frame)
{
    /* Pulsierendes Blau, Periode 2s = 100 Frames */
    uint8_t b = (uint8_t)(20.0f + 60.0f * pulse(frame, 100));
    set_all(0, 0, b);
}

static void render_stream(uint32_t frame)
{
    /* Rotierendes Blau: 3-LED-Bogen dreht einmal in ~1.6s = 80 Frames */
    set_all(0, 0, 0);
    /* Position in Subframe-Auflösung für flüssige Bewegung */
    float pos = fmodf((float)frame * (float)LED_COUNT / 80.0f, (float)LED_COUNT);
    int center = (int)pos % LED_COUNT;
    uint8_t bright[] = {60, 30, 10};
    for (int d = 0; d <= 2; d++) {
        int idx = (center + d) % LED_COUNT;
        led_strip_set_pixel(s_strip, idx, 0, 0, bright[d]);
        idx = ((center - d) + LED_COUNT) % LED_COUNT;
        led_strip_set_pixel(s_strip, idx, 0, 0, bright[d]);
    }
}

static void render_speak(uint32_t frame)
{
    /* Grüner Atemeffekt, Periode 2.4s = 120 Frames */
    uint8_t g = (uint8_t)(15.0f + 55.0f * pulse(frame, 120));
    set_all(0, g, 0);
}

static void render_mute(void)
{
    set_all(12, 0, 0);  /* Dunkles Rot — dauerhaft sichtbar aber nicht blendend */
}

static void render_error(uint32_t frame)
{
    /* Schnelles Blinken: 10 Frames an, 10 Frames aus = 0.4s Periode */
    if ((frame / 10) % 2 == 0)
        set_all(80, 0, 0);
    else
        set_all(0, 0, 0);
}

/* ── Animations-Task ─────────────────────────────────────────────────────── */

static void led_task(void *arg)
{
    uint32_t      frame      = 0;
    led_state_t   last_state = LED_STATE_BOOT;

    while (1) {
        led_state_t state = s_current_state;
        if (state != last_state) {
            frame      = 0;
            last_state = state;
        }

        switch (state) {
            case LED_STATE_BOOT:   render_boot(frame);   break;
            case LED_STATE_IDLE:   render_idle();        break;
            case LED_STATE_WAKE:   render_wake(frame);   break;
            case LED_STATE_STREAM: render_stream(frame); break;
            case LED_STATE_SPEAK:  render_speak(frame);  break;
            case LED_STATE_MUTE:   render_mute();        break;
            case LED_STATE_ERROR:  render_error(frame);  break;
        }

        led_strip_refresh(s_strip);
        frame++;
        vTaskDelay(pdMS_TO_TICKS(TICK_MS));
    }
}

/* ── Öffentliche API ─────────────────────────────────────────────────────── */

void hannah_led_init(void)
{
    led_strip_config_t strip_cfg = {
        .strip_gpio_num = LED_GPIO,
        .max_leds       = LED_COUNT,
    };
    led_strip_rmt_config_t rmt_cfg = {
        .resolution_hz = 10 * 1000 * 1000,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_strip));
    led_strip_clear(s_strip);

    xTaskCreate(led_task, "hannah_led", 2048, NULL, 3, NULL);
    ESP_LOGI(TAG, "LED ring initialized (%d LEDs, GPIO %d)", LED_COUNT, LED_GPIO);
}

void hannah_led_set_state(led_state_t state)
{
    s_current_state = state;
}
