#pragma once

/**
 * hannah_asset — Asset-Cache (WAV-Sounds) via SPIFFS + Asset-Server
 *
 * Ablauf:
 *   hannah_asset_init() — SPIFFS mounten, Manifest prüfen, fehlende/veraltete
 *                          Assets im Hintergrund herunterladen.
 *   hannah_asset_play() — WAV aus SPIFFS lesen und über hannah_audio abspielen.
 *   hannah_asset_play_async() — wie play(), aber in eigenem Task (MQTT-safe).
 *
 * Konfiguration (Kconfig / sdkconfig.defaults.ci):
 *   HANNAH_ASSET_SERVER_URL   — Asset-Server-URL (ohne abschließenden Slash)
 *   HANNAH_ASSET_SERVER_TOKEN — Bearer-Token
 */

void hannah_asset_init(void);
void hannah_asset_play(const char *asset_id);
void hannah_asset_play_async(const char *asset_id);
