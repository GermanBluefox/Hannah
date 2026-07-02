#pragma once

#include <stdbool.h>

/**
 * hannah_asset — Asset-Cache (WAV-Sounds) via SPIFFS + Asset-Server
 *
 * Ablauf:
 *   hannah_asset_init() — SPIFFS mounten, Manifest prüfen, fehlende/veraltete
 *                          Assets im Hintergrund herunterladen.
 *   hannah_asset_play() — WAV aus SPIFFS lesen und über hannah_audio abspielen.
 *                          Gibt false zurück wenn das Asset nicht im Cache liegt
 *                          oder der WAV-Header ungültig ist (#116).
 *   hannah_asset_play_async() — wie play(), aber in eigenem Task (MQTT-safe).
 *                          Meldet das Ergebnis an den per
 *                          hannah_asset_set_play_result_callback() registrierten
 *                          Callback (falls gesetzt) — main.c nutzt das, um Core
 *                          per MQTT über fehlgeschlagene Play-Versuche zu informieren.
 *
 * Konfiguration (Kconfig / sdkconfig.defaults.ci):
 *   HANNAH_ASSET_SERVER_URL   — Asset-Server-URL (ohne abschließenden Slash)
 *   HANNAH_ASSET_SERVER_TOKEN — Bearer-Token
 */

typedef void (*hannah_asset_play_result_cb_t)(const char *asset_id, bool ok);

void hannah_asset_init(void);
bool hannah_asset_play(const char *asset_id);
void hannah_asset_play_async(const char *asset_id);
void hannah_asset_set_play_result_callback(hannah_asset_play_result_cb_t cb);
