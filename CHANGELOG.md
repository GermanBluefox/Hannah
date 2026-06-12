# Changelog
<!--
    Placeholder for the next version (at the beginning of the line):
    ## **WORK IN PROGRESS**
-->
## **WORK IN PROGRESS**

## 0.24.10
### Satellite Firmware
* Fixed: mbedTLS context allocations redirected to PSRAM via `mbedtls_platform_set_calloc_free()` — internal RAM fragmentation (caused by BLE/NimBLE init) prevented `mbedtls_ssl_setup` from allocating the SSL context, causing all TLS connections to fail after boot

## 0.24.9
### Satellite Firmware
* Fixed: `hannah_asset` retries manifest fetch indefinitely (every 30 min) instead of giving up after 3 attempts — previously the update task deleted itself on failure, so assets were never fetched if TLS wasn't ready at boot
* Fixed: `CONFIG_MBEDTLS_KEY_EXCHANGE_RSA=n` added — disables RSA key exchange cipher suites (no forward secrecy); forces ECDHE negotiation with the Netscaler reverse proxy which otherwise prefers `AES256-SHA` (RSA key exchange) causing TLS handshake failure on ESP32-S3 via PSA crypto

## 0.24.8
### Satellite Firmware
* Fixed: `CONFIG_LWIP_SNTP_MAX_SERVERS=2` added — without it, pool.ntp.org (at slot 1) was silently dropped because lwIP only allocated one server slot; now DHCP NTP (slot 0) and pool.ntp.org (slot 1) are both active
* Improved: `hannah_net_wait_sntp()` now uses an EventGroup bit instead of `esp_netif_sntp_sync_wait` — fixes immediate return on second call; bit stays set after sync so all subsequent callers return instantly
* Improved: after WiFi gets IP, a 30s repeating FreeRTOS timer calls `esp_sntp_restart()` until SNTP is synced

## 0.24.7
### Satellite Firmware
* Fixed: SNTP init moved from `IP_EVENT_STA_GOT_IP` handler to `hannah_net_init()` — previously SNTP registered its `renew_servers_after_new_IP` event handler *after* the IP event already fired, so the DHCP-provided NTP server (Option 42) was never picked up; now the handler is registered before WiFi connects
* Fixed: `hannah_ota` now waits up to 10s for SNTP sync before the first `check_for_update()` call — prevents TLS handshake failure (`-0x008D`) caused by invalid system clock at t=60s boot

## 0.24.6
### Satellite Firmware
* Fixed: `CONFIG_LWIP_DHCP_GET_NTP_SRV=y` added to `sdkconfig.defaults` — required for `server_from_dhcp = true` in SNTP config; without it ESP-IDF rejected the SNTP init with `sntp_init_api: Tried to configure SNTP server from DHCP, while disabled`

## 0.24.5
### Satellite Firmware
* Fixed: SNTP time synchronization added — `hannah_net` starts NTP (`pool.ntp.org`) after WiFi connect; `hannah_asset` waits up to 10s for sync before first manifest fetch — fixes TLS handshake failure (`-0x3B00`) caused by invalid system clock
* Improved: SNTP now prefers NTP server from DHCP (Option 42); falls back to `pool.ntp.org` if DHCP provides none; DHCP-provided server is refreshed automatically on IP renewal
* Fixed: BME680 humidity compensation formula corrected to match Bosch reference (`bme68x.c`) — wrong divisors for `par_h3` (200→100), `par_h4` (100→16384), `par_h5` (10⁹→1048576) and wrong structure of correction term (used `v1` instead of `h`); fixes `H=0.0%` readings

## 0.24.4
### Satellite Firmware
* Changed: `wakeword_enabled` removed from NVS and web interface — wake-word on/off is now a compile-time decision via `CONFIG_HANNAH_WAKEWORD_ENABLED`; threshold (`ww_threshold`) remains configurable at runtime
* Fixed: `hannah_asset` manifest fetch retries up to 3 times with 30s delay on failure instead of silently skipping the update
* Fixed: BME680 calibration block 1 address corrected from `0x89` to `0x8A`, length from 25 to 23 bytes — fixes incorrect temperature/humidity readings

## 0.24.3
### Satellite Firmware
* Fixed: `hannah_asset` startup delay increased from 10s to 50s to ensure PSA crypto is ready before first TLS connection (asset check at t=50s, OTA check at t=60s)

## 0.24.2
### Satellite Firmware
* Fixed: `PSA_ERROR_INSUFFICIENT_MEMORY` (-141) during TLS handshake — `hannah_asset` delays 10s at boot before manifest fetch and uses `esp_crt_bundle_attach`; OTA unmounts SPIFFS before download to free heap for PSA signature verification

## 0.24.1
### Satellite Firmware
* Fixed: OTA TLS handshake failed with `MBEDTLS_ERR_X509_CERT_VERIFY_FAILED` — replaced hardcoded intermediate CA PEM with `esp_crt_bundle_attach` in both version check and OTA download

## 0.24.0
### Satellite Firmware
* Changed: asset server URL and token moved from compile-time Kconfig constants to NVS (with sdkconfig fallback) — adapter can now provision them during initial flash
* Changed: `hannah_asset` uses `hannah_config_get()` instead of `CONFIG_HANNAH_ASSET_SERVER_URL` / `CONFIG_HANNAH_ASSET_SERVER_TOKEN`; asset URL is now logged on each manifest fetch

## 0.23.16
### Satellite Firmware
* Fixed: PDM microphone channel selection was wrong — code read right channel (SEL=VDD, index 1) but Rev 4 PCB has SEL=GND (left channel, index 0); switched to `s16[i * 2]`
* Fixed: PDM gain factor x256 caused hard clipping; tuned to x64 which gives usable speech levels without distortion

## 0.23.15
### Satellite Firmware
* Fixed: `mic_task` could starve `IDLE0` on CPU0 and trigger the task watchdog — every loop iteration now yields via `vTaskDelay(1)` instead of relying solely on `i2s_channel_read()` blocking (or `taskYIELD()`)

### Hannah Core
* Fixed: audio received via UDP from a satellite in capture/sampling mode was processed through the normal STT/LLM/TTS pipeline instead of being routed to the capture stream — `process_audio_udp` now checks `is_captured()` like the gRPC path
* Fixed: a satellite could get stuck in capture/sampling mode after a Hannah Core restart because the retained MQTT sampling-mode flag survived independently of Hannah's in-memory capture state — Hannah now republishes `sampling: false` (retained) for any newly (re)connected satellite it doesn't consider captured

## 0.23.14
### Satellite Firmware
* Added: configurable status LED — `HANNAH_STATUS_LED_ENABLED` / `HANNAH_STATUS_LED_GPIO` (Kconfig, default GPIO 18 for Rev 4); turned on as early as possible in `app_main`

## 0.23.13
### Hannah Core
* Fixed: `_on_satellite_change` callback crashed with `TypeError` when a proxy satellite registered — `grpc_server.py` was passing `{device: {"room": ..., "addr": ...}}` but the callback expected `{device: room_string}`; snapshots now consistently use `{device: room_string}` matching the UDP server format

## 0.23.12
### Hannah Core
* Fixed: proxy satellites always had empty `address` state in ioBroker — `SatelliteRegistration` proto now carries the satellite IP; `grpc_server.py` stores it in `_proxy_satellites`; `get_satellites` lambda uses new `proxy_satellites_full()` to include the address

### Proxy
* Changed: `SatelliteChangeCallback` now includes `address` (satellite IP); passed through `NotifySatelliteRegistered` to Hannah Core
* Added: `udp.Server.RegisteredDevicesFull()` — returns `{device: SatelliteInfo{Room, Address}}` for re-notify on reconnect

## 0.23.11
### CI
* Fixed: upload jobs failed with SSL certificate error — `alpine` container has no internal CA; added `echo insecure >> ~/.curlrc` in `.upload.before_script` so all curl calls skip TLS verification for the self-signed Update-Server

## 0.23.10
### Hannah Core
* Fixed: `GetSatellites` response always returned empty `address` field — `get_satellites` lambda now uses new `udp_server.registered_devices_full()` which includes the actual `ip:port` address
* Added: `UdpServer.registered_devices_full()` — returns `{device: {room, addr}}` with address as `ip:port` string

### Satellite Firmware
* Added: `HANNAH_MIC_TYPE_NONE` Kconfig option — disables microphone input (mic_init, mic_task, sampling/PTT callbacks skipped); LED set to IDLE directly at init
* Added: `HANNAH_SPEAKER_ENABLED` Kconfig bool (default y) — disables I2S speaker output and TTS callbacks when set to n; allows building pure sensor-node firmware

## 0.23.9
### Satellite Firmware
* Fixed: BLE watchlist retained MQTT message was dropped on boot because `hannah_ble_init()` registers the callback after MQTT has already connected and received the retained payload; `hannah_net` now caches the payload and delivers it immediately when the callback is registered

## 0.23.8
### Hannah Core
* Changed: `udp_server` — added 300 ms delay before sending `tts_end` to satellite; prevents hard audio cutoff caused by `tts_end` arriving before the last PCM UDP packets are received and queued on the satellite

### Proxy
* Changed: `udp.SendTTS` — added 300 ms delay before sending `tts_end`; same reason as above (proxy is the primary TTS path for ESP32 satellites)

### Satellite Firmware
* Fixed: `hannah_audio` warmup loop — `taskYIELD()` (0.23.7) does not yield to `IDLE0` (priority 0) when higher-priority tasks are runnable during boot; replaced with `vTaskDelay(1 ms)` so the loop actually blocks and lets `IDLE0` reset the task watchdog

## 0.23.7
### Satellite Firmware
* Fixed: `hannah_audio` warmup loop — `continue` bypassed the `taskYIELD()` at the end of `mic_task`'s main loop, starving `IDLE0` for the full 5-second warmup period and causing a task watchdog warning at boot; added `taskYIELD()` inside the warmup block before `continue`

## 0.23.6
### Satellite Firmware
* Fixed: `hannah_ota` / `hannah_audio` — TFLite wakeword inference in `mic_task` (CPU 0) prevented `IDLE0` from running during OTA download, triggering repeated task watchdog warnings and potentially stalling HTTPS reads; `ota_update_task` now calls `hannah_audio_pause_wakeword()` before starting the download, causing `mic_task` to sleep 50 ms per iteration instead of running inference

## 0.23.5
### Satellite Firmware
* Fixed: `hannah_audio` — `mic_task` and `speaker_task` both ran unpinned on CPU 0; TFLite inference starved the speaker task causing `i2s_channel_write` silence drain to time out, resulting in TTS audio cutoff at end; `mic_task` now pinned to CPU 0, `speaker_task` to CPU 1; silence drain timeout changed to `portMAX_DELAY`

## 0.23.4
### Satellite Firmware
* Fixed: `mic_task` — added `taskYIELD()` at end of each loop iteration; TFLite wakeword inference was monopolizing CPU 0 and starving IDLE0, causing repeated task watchdog triggers (especially during concurrent OTA download)

## 0.23.3
### Hannah Core
* Fixed: BLE tag locations were not delivered to ioBroker adapter after reconnect — `_on_agent_connect` now pushes all current locations via `ble_engine.get_current_locations()` as a resync on every adapter connect
* Added: `BleLocationEngine.get_current_locations()` — returns last known location for all configured tags

### Satellite Firmware
* Fixed: `hannah_audio` speaker task — TTS playback was cut off at the end; on `audio_end` only 320 bytes of silence were written which was insufficient to drain the I2S DMA pipeline (8 × 640 frames × 2 bytes = 10240 bytes); now writes full DMA-sized silence buffer to ensure all buffered audio is clocked out

## 0.23.2
### Hannah Core
* Fixed: `tool_agent` — LLM had no access to current date/time; now injected into system prompt on every run (weekday, date, time); prevents wrong guesses for questions like "Welcher Tag ist heute?"

## 0.23.1
### Hannah Core
* Fixed: startup crash — `main.py` log statement referenced removed `topic_prefix_write` attribute on `ResidentsClient`; replaced with `topic_prefix_read`

## 0.23.0
### Satellite Firmware
* Added: `hannah_sd` component — SPI Micro-SD card support via `esp_vfs_fat`; mounts at `/sdcard`; enabled per Kconfig (`CONFIG_HANNAH_SD_ENABLED`); no-op stubs when disabled
* Added: `sdkconfig.defaults.rev4` enables SD card (GPIO 4/5/6/7) and BME680

### CI
* Added: `build:esp32:rev4` — builds firmware with `sdkconfig.defaults.rev4`
* Added: `upload:esp32:rev4` — uploads Rev4 firmware to channel `satellite-esp-stable`

## 0.22.2
### Hannah Core
* Fixed: `tool_agent` — `speak()` is now a terminal tool; the loop returns immediately after dispatching `speak` without waiting for a further LLM round-trip; previously the loop could exhaust `_MAX_ITERATIONS` before `speak` was ever called, causing the fallback "Das habe ich leider nicht verstanden." instead of the generated answer
* Changed: `_MAX_ITERATIONS` raised from 3 to 5 — allows more complex tool-use flows (e.g. multi-device commands, intermediate queries) without hitting the limit prematurely
* Added: TTS result logging in `_handle_satellite_audio` — logs byte count and sample rate on success, or a warning when `synthesize()` returns nothing

## 0.22.1
### Hannah Core
* Fixed: `process_notification` (notify/alert severity) was sending raw Azure TTS (24kHz) to satellites without resampling — audio played at 67% speed with noticeably lower pitch; now resampled to 16kHz via `_resample_to_16k` before `_send_audio`
* Fixed: `_on_agent_satellite_control` (ioBroker announcements) had the same missing resample, and called `udp_server.send_tts` directly instead of `_send_audio` — breaking proxy-connected satellites

## 0.22.0
### Hannah Core
* Added: LLM rephrase for announcements — `_rephrase_text()` helper shared by trigger engine and satellite control handler; falls back to original text when LLM is unavailable or fails
* Added: `rephrase: true` field in `triggers.yaml` — TriggerEngine passes `say` text through LLM before TTS when set
* Added: `AgentSatelliteControl.announcement_rephrase` gRPC field — adapter can request LLM reformulation per announcement

### Proto
* Added: `announcement_rephrase` (field 8) to `AgentSatelliteControl.oneof control` — speak announcement with LLM rephrase applied before TTS

## 0.21.3
### Telegram
* Added: Automated test suite for the Telegram bot (`telegram/tests/test_app.py`, 28 tests) — covers private-chat guard, trust-level checks, link/unlink flow, `/start` welcome message, free-text command dispatch, and car-state formatting; integrated as `test:telegram` CI job

### VoiceID
* Refactored: `voiceid/app.py` — moved all module-level side effects (model loading, argparse, `os.makedirs`) out of import scope into a `create_app()` factory and FastAPI lifespan handler; routes extracted to `APIRouter`; `get_embedding()` now accepts classifier as parameter instead of using a global
* Added: Automated test suite for the VoiceID service (`voiceid/tests/test_app.py`, 16 tests) — covers embedding extraction, profile enrollment (new + blending), identification with threshold logic, startup profile sync from disk to RAM, and config-file threshold overrides; integrated as `test:voiceid` CI job (Python 3.11, torch CPU-only, no speechbrain install required)

## 0.21.2
### Hannah Core
* Changed: Asset manifest is now fetched without namespace filter (`GET /manifest`) so asset metadata can be queried generically across all namespaces

## 0.21.1
### Satellite Firmware
* Fixed: `hannah_asset` — asset server HTTPS requests failed due to missing CA certificate; added Thawte TLS RSA CA G1 cert to `fetch_manifest()` and `download_asset()` (same CA as OTA)

## 0.21.0
### Hannah Core
* Added: Asset manifest fetch at startup — reads `duration_s`, `sample_rate`, `channels`, `bits_per_sample` from asset server manifest (`asset_server.url` + `asset_server.token` in `config.yaml`)
* Changed: Timer alert now plays `timer_jingle` asset on all target satellites before TTS; TTS is pre-synthesized so jingle and announcement are sequenced precisely (`play_asset` → sleep `duration_s + 0.1 s` → TTS PCM)
* Added: `mqtt_handler.publish_play_asset(device, asset_id)` — publishes `{"asset_id": …}` to `hannah/satellite/{device}/play_asset`

### Satellite Firmware
* Added: `hannah_asset` component — fetches asset manifest at boot, downloads/caches WAV files in SPIFFS (sha256-based cache validation via NVS), plays WAV assets on demand with proper WAV chunk scanning
* Added: MQTT topic `hannah/satellite/{device}/play_asset` — payload `{"asset_id": …}` triggers async WAV playback via `hannah_audio_play()`
* Added: `HANNAH_ASSET_SERVER_URL` + `HANNAH_ASSET_SERVER_TOKEN` Kconfig options (set via CI as `sdkconfig.defaults.ci`)
* Changed: SPIFFS partition expanded from 1.9 MB to 9 MB

## 0.20.0
### Hannah Core
* Fixed: Notifications played back at wrong pitch — Azure TTS output (24 kHz) was not resampled before sending to satellite, causing 2/3-speed playback and a noticeably deeper voice; use `_resample_to_16k()` helper
* Added: `TriggerPlink` gRPC RPC — Hannah plays an 880 Hz plink tone on the satellite and holds virtual PTT for `record_duration` seconds so the collector can trigger guided Hey-Hannah recordings remotely
* Added: `plink.py` — generates 880 Hz sine plink PCM (200 ms, 16 kHz, 16-bit mono) or loads from a WAV file
* Added: `_on_trigger_plink` in `main.py` — plays plink audio on satellite, then holds virtual PTT for the requested duration
* Added: `SatelliteCaptureRequest.sample_type` field (`"noise"` or `"hey_hannah"`) — collector signals which training mode to use
* Changed: `mqtt_handler.publish_sampling_mode` now sends JSON payload `{"enabled": …, "type": …}` instead of plain boolean; added `publish_virtual_ptt` to toggle `hannah/satellite/{device}/ptt`
* Changed: `grpc_server.RequestSatelliteCapture` forwards `sample_type` to the capture callback

### Hardware (PCB Rev. 4)
* Added: SD card slot (SPI)
* Changed: LED data pin moved from GPIO 5 to GPIO 3; `sdkconfig.defaults.rev4` updated accordingly

### Satellite Firmware
* Added: `sdkconfig.defaults.rev4` — build target for PCB Rev. 4 with updated GPIO assignments
* Added: Virtual PTT via MQTT `hannah/satellite/{device}/ptt` — `"true"`/`"1"` activates PTT, `"false"`/`"0"` releases; allows Hannah Core to trigger recordings without a physical button press
* Added: `hey_hannah` capture sub-mode — in this mode the mic streams only while PTT is active (physical or virtual) and sends `audio_end` on PTT release; pre-flush clears any buffered noise before each recording; speaker output is allowed so the plink tone is audible
* Changed: `noise` capture sub-mode behaviour unchanged — continuous auto-flush every 5 s, pre-flush on PTT press; speaker is muted in this mode
* Changed: `hannah/satellite/{device}/sampling` payload is now JSON with `enabled`/`type` fields
* Changed: capture LED animation is now more distinctly purple (higher blue component relative to red)
* Added: LED state transition logging — each state change is logged (`LED X → Y`)

## 0.19.0
### Hannah Core
* Added: Wakeword Collector integration — satellites can be put in capture mode via gRPC; Hannah relays raw PCM to the collector instead of STT pipeline; DND is set automatically; MQTT `hannah/satellite/{device}/sampling` notifies satellite firmware (firmware-side pending)
* Added: `RequestSatelliteCapture`, `ReleaseSatelliteCapture`, `StreamSatelliteAudio` gRPC RPCs for wakeword training data capture
* Added: `SatelliteCaptureRequest`, `SatelliteCaptureResponse`, `SatelliteAudioChunk` gRPC messages

### Satellite Firmware
* Added: Sampling mode via MQTT `hannah/satellite/{device}/sampling` — when `{"enabled":true}` is received, speaker output is blocked, any running TTS queue is cleared, and LED shows `LED_STATE_CAPTURE` (purple pulsing); restored to normal on `{"enabled":false}` or auto-release

## 0.18.6
### Hannah Core
* Fixed: NLU timer trigger now recognizes Whisper-truncated "erinner" (prefix match instead of exact set match)
* Fixed: Announcements (proactive / timer / trigger) played back at wrong pitch — Azure TTS output (24 kHz) was not resampled before sending to satellite, causing 2/3-speed playback and a noticeably deeper voice; extracted `_resample_to_16k()` helper used by both announcement and satellite audio paths

## 0.18.5
### Hannah Core
* Fixed: `SetTimer` intent not handled in gRPC/satellite audio path (`_handle_text`) — fell through to `iobroker.execute()` causing "Kein Raum erkannt" warning and no timer being set; timer is now created correctly from all input paths

### Proto
* Added: `TimerNotReady` message — Hannah can signal a temporary degraded state (e.g. ioBroker disconnected) over the `TimerConnect` stream; Timer Service should hold `TimerFired` events until a subsequent `TimerReady` is received; Hannah Core does not yet send this message

## 0.18.4
### Hannah Core
* Fixed: NLU responses no longer contain raw internal category names (e.g. "light") — mapped to German labels: Lichter, Steckdosen, Klimageräte, Rollläden, Sensoren

## 0.18.3
### Satellite Firmware
* Fixed: false wakeword trigger immediately after boot — wakeword frontend is now fed audio during the 5-second warmup period so model state is fully initialized before detection begins; previously the uninitialized frontend caused a consistent false trigger ~200 ms after warmup ended
* Fixed: TTS audio chunks silently dropped during playback — speaker queue depth increased from 8 to 256 entries; send is now blocking with a 2-second timeout to apply backpressure instead of discarding chunks
* Fixed: OTA reliability — mbedTLS TLS IN buffer reduced from 16 KB to 8 KB via `MBEDTLS_ASYMMETRIC_CONTENT_LEN`; frees internal RAM headroom consumed by DSR_16S PDM downsampling

## 0.18.2
### Satellite Firmware
* Fixed: PDM microphone channel selection corrected — SPH0641LU4H-1 with SEL=VDD outputs on the right channel (index 1), not left; previously all captured audio was zero
* Fixed: PDM digital gain increased from default (1×) to 8× — default gain produced inaudibly quiet signal for the SPH0641LU4H-1

## 0.18.1
### Hardware (PCB Rev. 4)
* Changed: SW1 (EN) tap rerouted closer to ESP pin for more clearance to C3/C4/R3
* Changed: SW2 (IO0) rerouted for more clearance between R6 and button body; AMP_LRC/AMP_BCLK traces rerouted away from button area
* Changed: UART connector (J4) TX/RX swapped to match adapter pinout without crossing cables

### Satellite Firmware
* Changed: wakeword enable/disable is now a runtime decision — `CONFIG_HANNAH_WAKEWORD_ENABLED=y` compiles in the wakeword code, NVS `wakeword_enabled` decides at boot whether wakeword or PTT mode is active
* Added: VAD silence timeout (`vad_silence_ms`) is now stored in NVS and configurable via web UI (200–10000 ms); default remains 1500 ms
* Fixed: after wakeword detection, VAD cannot end the stream for the first 2 seconds — prevents cutoff during the natural pause between wakeword and spoken command

## 0.18.0
### AutoDeploy
* Changed: revision field from update server is now compared alongside version — same version but higher revision triggers redeployment; revision is persisted in state file
* Changed: download URL is now taken from the server response `url` field; `device=<id>` query parameter added to download requests

### Satellite Firmware
* Changed: OTA now compares server `revision` field in addition to version — same version but higher revision triggers an update; revision is persisted in NVS after successful OTA
* Changed: OTA download URL now includes `device=<id>` query parameter (matching the `/latest` check request)

## 0.17.0
### Hardware (PCB Rev. 4)
* Changed: PCB revision bumped from 3 to 4
* Fixed: ALPS SKRPABE010 button LCSC part numbers corrected for all 6 buttons (Mute, Vol-, Vol+, PTT, EN, IO0)
* Changed: ESP32-S3-WROOM-1U LCSC part number updated to N16R8 variant (was accidentally N16R2 in Rev. 3)

### Satellite Firmware
* Added: LED animations per state — BOOT rotating white, WAKE pulsing blue, STREAM rotating blue arc, SPEAK green breathing, MUTE dim static red, ERROR fast red blink; driven by a 50 Hz FreeRTOS task

## 0.16.3
### Satellite Firmware
* Fixed: LED stays in SPEAK (green) state until the speaker task has finished playing all TTS audio — previously `status=idle` from the server would immediately reset the LED while chunks were still queued for playback

## 0.16.2
### Hardware (PCB Rev. 3)
* Fixed: ALPS SKRPABE010 footprint corrected — contacts were bridged on the wrong axis causing EN and IO0 to be permanently pulled to GND; all 6 button footprints (EN, IO0, Mute, Vol-, Vol+, PTT) replaced
### Satellite Firmware
* Added: `sdkconfig.defaults.rev2` — build target for PCB Rev. 2 (PDM mics, BMP280, external LED ring, corrected GPIO assignments)

## 0.16.1
### Hannah Core
* Added: INFO log in `Notify` gRPC handler — logs severity and text on every received notification to diagnose duplicate delivery

## 0.16.0
### Hannah Core
* Changed: `SetTimer` voice intent now routes through the external Timer Service — generates a UUID timer_id, persists metadata in `HannahTimerStore`, and calls `grpc_servicer.timer_create()`; in-process `TimerManager` removed for timer commands
* Added: NLU label extraction for timer commands — "erinnere mich in X Minuten an Y" triggers `SetTimer` and extracts Y as label; response includes label if detected ("Timer für 40 Minuten gesetzt: Spazierengehen.")

## 0.15.0
### Hannah Core
* Added: `say` action type in routines — routines can now speak text via TTS as part of their action sequence; optional `room` parameter (default: `all`)
* Added: Hannah Timer Service gRPC interface — `TimerConnect` bidirectional stream, `TimerReady` signal sent after ioBroker device snapshot; `HannahTimerStore` (SQLite) persists timer metadata (label, room, roomie_id, fire_at) locally; on `TimerFired`, Hannah looks up metadata and plays TTS announcement

## 0.14.7
### Hannah Core
* Changed: notification reformulation prompt now uses Hannah's persona ("24-jährige Mitbewohnerin") and per-severity tone tuning for more natural, less formal spoken notifications

## 0.14.6
### Hannah Core
* Fixed: `get_active_devices` now correctly uses the `on` state as the sole indicator of activity when present — previously a non-zero `level` alone would mark a device as active even if `on=false` (e.g. lights with a saved level but physically off)
* Changed: `get_active_devices` output now includes total device count (e.g. "5 von 47") to give the LLM context for relative statements

## 0.14.5
### Hannah Core
* Added: INFO-level payload size logging in tool agent — logs message count and character count per iteration, and tool result size after each dispatch
* Fixed: tool agent now blocks duplicate tool calls (same name + same arguments) server-side and returns an error forcing the LLM to call `speak` instead of looping
* Changed: tool agent query tools now return human-readable text instead of raw JSON — `get_all_devices`, `get_active_devices`, `get_devices_in_room`, `get_devices_by_category`, `get_device_state` all return formatted strings that LLMs can directly use for spoken answers

## 0.14.4
### Hannah Core
* Added: `get_active_devices` tool — returns only active devices (on=true or level>0) with current state; ideal for "was läuft gerade?"
* Added: `get_devices_in_room(room)` tool — returns devices in a specific room with state keys; for targeted queries and control
* Added: `get_devices_by_category(category)` tool — returns devices of a category with state keys; for bulk actions like "alle Lichter aus"
* Changed: `get_all_devices` now returns only id/name/room/category (no state_keys, no current) — pure discovery tool to reduce token usage

## 0.14.3
### Hannah Core
* Fixed: `get_all_devices` tool no longer returns `current` state values — payload was too large for LLM token budget; use `get_device_state` for current values

## 0.14.2
### CI
* Fixed: `upload:core` CI job did not include `main.py` in the release archive — services deployed via autodeploy were missing the entry point

## 0.14.1
### Hannah Core
* Fixed: LLM tool calls in `chat_with_tools` could hang indefinitely on large Ollama responses — added explicit `stream: false` to payload and explicit `(connect, read)` timeout tuple
* Added: INFO-level iteration logging in `tool_agent.run()` for observability in journalctl

## 0.14.0
### Hannah Core
* Added: LLM Tool Agent (`hannah/tool_agent.py`) — handles complex requests via OpenAI-compatible function-calling; tools: `get_all_devices`, `get_device_state`, `set_device_state`, `speak`
* Changed: `Unknown` and `Smalltalk` intents now both route to the Tool Agent instead of bare `llm.chat()`
* Changed: `LLMClient` — added `chat_with_tools(messages, tools)` method; `OpenAICompatibleLLM` implements native tool calling, other backends fall back to regular `chat()`
* Changed: `get_all_devices` tool now returns `state_keys` (list of available state names) and `current` (actual values) separately to prevent LLM misreading key names as values
* Added: tool usage rules appended to system prompt in every Tool Agent call (always use `speak`, no repeated tool calls)

### Scripts
* Added: `scripts/hannah_shell.py` — interactive text shell for testing NLU/Tool Agent via gRPC `SubmitText` without Telegram

## 0.13.1
* Fixed: MQTT-triggered mute/unmute now correctly updates the LED state (was only updated on button press)

## 0.13.0
### Proto
* Changed: `AgentSatelliteUpdate` — added optional `volume` (int32) and `mute` (bool) fields
* Changed: `AgentSatelliteControl` — added optional `device_id` (string) for per-satellite targeting

### Hannah Core
* Changed: satellite volume/mute now reported via `volume/state` / `mute/state` topics (satellite-initiated); Hannah subscribes to these instead of command topics
* Changed: `_on_agent_satellite_control` for volume/mute now publishes `volume/set` / `mute/set` commands to satellites (previously published state topics)
* Added: mute room-replication — when one satellite reports a mute state change, Hannah replicates `mute/set` to all satellites in the same room
* Added: global volume command (`hannah/volume`) now sends `volume/set` to all satellites
* Removed: PCM volume scaling in Hannah Core (`_scale_pcm`, `_get_volume`); volume is applied satellite-side

### Satellite Firmware
* Added: Vol+/Vol- buttons now publish new level to `hannah/satellite/<device>/volume/state`
* Added: subscribe to `hannah/satellite/<device>/volume/set`; received value is applied to local playback volume
* Added: change detection in `hannah_net_set_mute()` — state is only published if it actually changed

## 0.12.5
### CI
* Fixed: `skip_if_unchanged` calls were removed from all upload jobs for the v0.12.4 release to force a full upload — this commit restores them

### Hannah Core
* Removed: all ioBroker-facing MQTT publishes (transcript, speaking, satellite_status, rooms, online, global dnd/mute, text commands); ioBroker communication is now exclusively via gRPC
* Removed: REST API client code from `iobroker.py` (`requests`, `_get_enum`, `_get_objects`); device data is now fully gRPC-driven
* Removed: `publish_fn` parameter from `ResidentsClient` (unused)
* Removed: PCM volume scaling in Hannah Core (`_scale_pcm`); volume will be applied satellite-side
* Kept: per-satellite MQTT for volume/mute/dnd control, announcements/notifications, OTA/BLE/sensors

### Satellite Firmware
* Fixed: mute command topic changed from `…/mute` to `…/mute/set`; state feedback published on `…/mute/state`
* Fixed: mute value parsing now accepts `true`/`false` in addition to `1`/`0`

## 0.12.4
### CI
* Fixed: Upload jobs fetched tags without pruning deleted ones (`--tags`) — replaced with `--tags --prune --prune-tags` so stale tags in the runner cache no longer cause `skip_if_unchanged` to compare against a non-existent previous tag

## 0.12.3
### AutoDeploy
* New: Generates a persistent device ID (UUID v4) on first start, stored in `/var/lib/hannah/autodeploy-device-id`; sent as `?device=<uuid>` with every `/latest` poll to enable accurate per-installation device counting on the Update Server

### Satellite Firmware
* New: Sends `?device=<device_id>` (NVS-backed device ID) with every OTA `/latest` request to enable accurate per-device counting on the Update Server

## 0.12.2
### CI
* Fixed: `skip_if_unchanged` caused SIGPIPE (exit 141) — replaced `grep | head -1` with `awk`

## 0.12.1
### AutoDeploy
* Fixed: `UnboundLocalError` for `current` variable in `deploy_component()` — `state.get(name)` was called after `get_latest()` which already needed it

### CI
* Changed: Renamed job groups for clarity — `test:python` → `test:core`, `test:go` → `test:proxy`, `test:satellite` → `test:satellite:pi`, `build:amd64/arm64` → `build:proxy:amd64/arm64`, `publish:amd64/arm64` → `publish:proxy:amd64/arm64`
* Changed: `PACKAGE_NAME` variable renamed to `PROXY_PACKAGE_NAME`
* New: Upload jobs skip the Update-Server upload if the component directory has no changes since the previous release tag (`skip_if_unchanged` function in `.upload`)

## 0.12.0
### Satellite Firmware
* Changed: OTA update-check requests now include `?current=<version>` so the Update-Server can track installed version distribution

### AutoDeploy
* Changed: `get_latest()` now passes the currently installed version as `current` query parameter to the Update-Server

## 0.11.0
### Hannah Core
* New: Connect sound — Hannah plays `core/sounds/satellite_connected.wav` (if present) on the satellite when it registers via the proxy
* New: Timer — "Hannah, stelle einen Timer auf 20 Minuten" fires TTS on the source satellite when the countdown ends
* New: Alarm — "Hannah, stelle einen Wecker auf 7 Uhr 30" sets a persistent alarm that fires on the configured `alarm.satellite` (falls back to source satellite); survives Hannah restarts via `alarms.json`

## 0.10.0
### Hannah Core
* New: `climate` device type — NLU recognizes `SetMode` (`SetMode`: cool/heat/dry/fan_only/auto) and `SetFanSpeed` (low/medium/high/auto) intents; German compound words ("Klimaanlage", "Klimaanlagen") map to `climate` category
* New: Climate device query answers report on/off state, operating mode, current temperature, target temperature, and fan speed

## 0.9.1
### Satellite Firmware
* Fixed: `ota_channel` buffer increased from 16 to 32 bytes — channel names longer than 15 characters (e.g. `satellite-esp-dev`) were silently truncated

### CI
* Changed: GitLab Generic Registry publish jobs and Hannah Update-Server upload jobs split into separate stages (`publish` and `upload`) with clearer naming
* Changed: Upload jobs use `{latestTag}-dev` (e.g. `v0.9.0-dev`) as version fallback when `FORCE_PUBLISH` runs without a tag

### AutoDeploy
* New: `autodeploy.py` — polls Update-Server channels and deploys updates; supports self-update
* New: `install.sh` — downloads and installs the AutoDeploy agent from the Update-Server, sets up Python venv and systemd service
* Fixed: State was not saved before service restart, causing an infinite redeploy loop on self-update
* Fixed: Replacing a running executable raised `ETXTBSY` — file is now unlinked before copy
* Changed: `hannah-autodeploy.service` sets `REQUESTS_CA_BUNDLE` to system trust store

## 0.9.0
### Satellite Firmware
* New: `hannah_sensors` now publishes readings every 30s to `hannah/satellite/{device}/sensors` (retained, QoS 1); JSON payload includes `temperature`, `pressure`, `humidity`, and optionally `gas_resistance` (BME680 only)

### Hannah Core
* New: Subscribes to `hannah/satellite/+/sensors`; forwards readings to the ioBroker adapter via `AgentSensorUpdate` gRPC command

### Proto
* New: `AgentSensorUpdate` message — carries `device`, `temperature`, `pressure`, `humidity`, `gas_resistance`
* New: `sensor_update = 8` added to `AgentCommand.command` oneof

## 0.8.3
### Satellite Firmware
* New: OTA rollback — `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` enabled; firmware marks itself valid after first successful MQTT connection, otherwise the bootloader automatically reverts to the previous partition on the next reboot
* New: OTA rollback loop prevention — after a rollback, the previously invalid partition version is compared against the server's latest; if they match, `ota/failed` (with `reason: rollback`) is published instead of `ota/pending` to prevent an update loop
* New: OTA channel config (`HANNAH_OTA_CHANNEL`) — Kconfig string, NVS-backed, configurable via WebUI; appended as `?channel=<value>` to the update server request; devkit default: `dev`
* New: Dev-channel semver comparison — when channel is not `stable`, the git-describe commit offset is compared when the semver base is equal (e.g. `0.8.2-12` > `0.8.2-11`)
* Fixed: git-describe offset parsing in semver comparison was broken for versions without a patch-level dot suffix — replaced manual loop with `strchr` (regression introduced in 0.8.1)

### Scripts
* New: `scripts/upload-dev-firmware.ps1` — builds (devkit config) and uploads firmware to the OTA server; supports `-NoBuild`, `-Channel`, `-List`, `-Delete`, `-Version`; reads credentials from `.env`

### CI
* Changed: firmware is now uploaded to the `stable` channel (`?channel=stable`) instead of the implicit default

## 0.8.2
### Satellite Firmware
* Fixed: `.history_trim` VS Code Local History directory was accidentally tracked as a git submodule — removed from index and added to `.gitignore`; fixes CI submodule init failure

## 0.8.1
### Satellite Firmware
* Changed: OTA version check uses semver comparison instead of strict string equality — downgrades and git-describe suffixes (e.g. `0.8.0-1-gabcdef`) are no longer treated as available updates

## 0.8.0
### Satellite Firmware
* New: `hannah_ble` component — passive BLE scanner for indoor localisation; MAC-based watchlist from `hannah/satellite/{device}/ble/watchlist`; RSSI reports to `hannah/satellite/{device}/ble/report`; rate-limited per MAC (Kconfig: `HANNAH_BLE_REPORT_INTERVAL_MS`); NimBLE host in dedicated FreeRTOS task; BLE/WiFi coexistence via `CONFIG_ESP_COEX_SW_COEXIST_ENABLE`

### Hannah Core
* New: `ble_location.py` — `BleLocationEngine` aggregates per-satellite RSSI reports per BLE tag; "strongest RSSI wins" room determination; configurable stale timeout; fires `on_location_change` callback on every room transition
* New: Subscribes to `hannah/satellite/+/ble/report`; routes reports to `BleLocationEngine`
* New: Publishes BLE watchlist (retained) to each satellite on connect via `publish_ble_watchlist()`
* New: On location change, publishes `hannah/ble/{label}/location` (retained JSON) and pushes `AgentBleUpdate` to ioBroker adapter

### Proto
* New: `AgentBleUpdate` message — carries `label`, `mac`, `room`, `satellite`, `rssi` for the `AgentConnect` stream
* New: `ble_update = 7` added to `AgentCommand.command` oneof

### ioBroker Adapter
* New: `BleWatcher` class — handles `ble_update` commands; creates/updates `hannah.0.ble.{label}.{room,satellite,rssi}` states on first update

## 0.7.0
### Satellite Firmware
* New: `hannah_ota` publishes firmware version to `hannah/satellite/{device}/firmware` (retained, QoS 1) after boot — enables firmware visibility in ioBroker
* Changed: OTA MQTT topics renamed from `hannah/{device}/ota/*` to `hannah/satellite/{device}/ota/*` for consistency with the satellite topic namespace
* Fixed: OTA-pending MQTT handler never fired due to wrong topic-part count (was checking `len==3`, correct is `len==5`)

### Hannah Core
* New: Subscribes to `hannah/satellite/+/firmware`; stores firmware version per satellite and fires `satellite.firmware` gRPC event (`SubscribeEvents` stream)
* New: Pushes firmware version and `update_available` flag to the ioBroker adapter via `AgentFirmwareEvent` over the `AgentConnect` stream
* New: `TriggerFirmwareUpdate` gRPC RPC — triggers immediate OTA for a satellite (bypasses residents check), called by the ioBroker adapter `update_now` button
* New: On `ota/pending` event, `update_available=true` is pushed to the adapter immediately so the ioBroker state updates without waiting for a full reconnect
* Changed: OTA publish/subscribe topics updated to `hannah/satellite/{device}/ota/*`
* Fixed: MQTT topic typo `hannah/satelite/` → `hannah/satellite/` throughout `mqtt_handler.py` and `config.example.yaml` — mute/volume/dnd/announcement/status/online topics now match the firmware's subscription patterns

### Proto
* New: `FirmwareEventProto` message — carries `device` and `version` for the `SubscribeEvents` stream
* New: `AgentFirmwareEvent` message — carries `device`, `version`, and `update_available` bool for the `AgentConnect` stream
* New: `TriggerFirmwareUpdateRequest` message and `TriggerFirmwareUpdate` RPC

## 0.6.0
### Hardware
* New: Hardware Rev 3 PCB — iterates on Rev 2; ESP32-S3-WROOM-1U (external U.FL antenna, no keep-out conflict with LED ring); hierarchical schematic (Audio, Supplementals, Power_Control sub-sheets); AHT20 humidity sensor integrated directly on board sharing BMP280 I2C bus; LD2410 24GHz radar presence sensor header (5-pin: 5V, GND, TX, RX, OUT); 24× SK6812MINI-E LED ring directly on PCB at 3.3V (replaces JST connector + SN74AHCT125D level shifter); BMP280 I2C bus unified with shared SDA/SCL (was on separate GPIOs); I2C pull-up resistors moved to root sheet; fixed mic power circuit bug (R10 was on MOSFET drain instead of gate)

### Satellite Firmware
* New: `hannah_config` component — NVS-backed configuration (WiFi credentials, device ID, OTA token/URL); persists across reboots, readable at runtime via `hannah_config_get()`
* New: `hannah_webserver` component — HTTP setup UI served in AP mode; WiFi network picker (APSTA scan), device settings (device ID, OTA token/URL), live log viewer (ring buffer, 1s polling)
* New: WiFi provisioning — AP fallback when no credentials are stored; APSTA mode for simultaneous scan and serve; credentials written to NVS on submit
* New: Factory reset — hold Mute button at boot to erase WiFi credentials and force AP provisioning mode
* New: `hannah_ota` component — periodic update check against the Hannah update server (`GET /latest` with Bearer token); compares server version against running firmware; publishes `hannah/{device}/ota/pending` when an update is available; flashes new firmware via `esp_https_ota` on `ota/ok` and restarts
* New: Wake-Word detection (microWakeWord, TFLite Micro) — hey_hannah inception model embedded as C array; MicroResourceVariables support for streaming state; TFLite arena allocated from PSRAM
* New: PTT button (GPIO12), Vol+/Vol- buttons (GPIO13/14) with software volume control
* New: Custom partition table — 2MB app partition to fit firmware with embedded TFLite model
* New: BMP280 sensor support — reads temperature and pressure every 30s via I2C (IO8/IO9); logged locally, Hannah channel TBD
* New: Wake-Word VAD: adaptive noise-floor threshold (measured in IDLE, set to 2× noise EMA on trigger); 10s hard streaming timeout as safety net
* Fixed: Wake-Word VAD onset bypassed after wakeword detection — VAD now starts in speaking=1 state so silence detection begins immediately
* Fixed: ESP32 satellite re-registered every ~12s — `udp_connect()` was called on every MQTT reconnect via the retained `hannah/server` message; now skipped if the proxy address is unchanged and the socket is already connected.
* Fixed: ESP32 satellite microphone (INMP441) now uses 32-bit I2S slot width — the previous 16-bit slot width provided only 16 BCLK cycles per channel, too few for the INMP441 to output valid audio (resulting in noise). Stereo→mono downmix updated accordingly.
* Fixed: ESP32 heartbeat interval reduced from 30s to 10s, eliminating a race condition with the proxy's 30s heartbeat timeout that caused continuous re-registration on every heartbeat cycle.
* Fixed: ESP32 MQTT reconnect loop after WiFi drop — random suffix appended to client ID prevents duplicate-ID conflicts while the broker still holds the old TCP session
* Fixed: Mute LED stays red after unmute — LED now immediately returns to idle state when mute is toggled off

### Hannah Core
* New: Hannah Core subscribes to `hannah/+/ota/pending`; sends `ota/ok` immediately if no resident is home, otherwise queues the device and releases all pending updates when the last resident leaves

## 0.5.3
* New: NLU compound word splitting — "Schlafzimmerlicht" is split into "Schlafzimmer Licht" before parsing using known room name words as prefixes and category keywords as suffixes
* Fixed: Telegram `/systemmessages` command threw `AttributeError: system_messages` — generated `hannah_pb2.py` in the telegram service was out of sync with the proto definition and missing field 7 (`system_messages`)

## 0.5.2
* Fixed: Proxy UDP server now clears any open audio session on satellite re-registration — previously a session accumulated indefinitely across ESP reboots (no `audio_end` sent), causing gRPC `ResourceExhausted` on the first successful `audio_end`
* Fixed: Proxy gRPC client max receive message size raised to 32 MB (was 4 MB default)

## 0.5.1
* Fixed: NLU rooms dict was stale after adapter snapshot — NLU was initialized before the device snapshot arrived and never received the updated rooms/devices; room detection failed for all queries
* Fixed: Telegram device menu threw `Can't parse entities` for devices with `_` in category name (e.g. `temperature_sensor`) — category label is now sanitized before use in Markdown
* Fixed: Telegram device menu now shows `Soll` temperature for thermostat devices (`expected` state)

## 0.5.0
* New: `AgentDevice` proto carries a `device_type` field (field 5) — resolved by the adapter from `common.hannah.type`, `common.role`, or function enum IDs; Hannah uses this instead of deriving the category from the state ID path
* New: NLU recognizes `SetTemperature` intent — detects temperature values ("22 Grad", "21,5°C") and maps them to the `expected` state on thermostat devices
* New: Extended device category support — `temperature_sensor`, `thermostat`, `window`, `door`, `blind` (in addition to `light` and `socket`)
* Fixed: Pi satellite `max_heartbeat_wait` reduced from 15s to 5s — prevents heartbeat cycle from exceeding the proxy's 30s timeout window

## 0.4.5
* Fixed: LLM classifier now correctly routes device state queries (e.g. "Welche Lichter sind an?") as COMMAND instead of SMALLTALK, preventing them from bypassing NLU when smalltalk mode is active

## 0.4.4
* New: STT supports Azure Cognitive Services as primary backend — fallback chain: Azure → Remote (faster-whisper-server) → Local

## 0.4.3
* Fixed: Auto-deploy now also pulls `/opt/hannah-telegram` before restarting the Telegram service, so the service actually runs the updated code.

## 0.4.2
* Fixed: Proxy and UDP server now send `reregister` to satellites that send heartbeats or audio without being registered — prevents satellites from silently losing their registration without reconnecting.

## 0.4.1
* Changed: Auto-deploy script now only triggers on new release tags instead of every commit to master.
* Fixed: Auto-deploy `git fetch --tags` now uses `--force` to prevent failure when local tags diverge from remote.

## 0.4.0
* New: `AgentDevice` carries a `floor` field — provided by the ioBroker adapter, resolved from `common.floor` or from the state ID path (known abbreviations: EG, OG, UG, DG, KG, ZG).

## 0.3.1
* Fixed: Release-Cycle

## 0.3.0
* New: Device discovery via gRPC adapter snapshot — Hannah Core no longer queries the ioBroker REST API; device structure (room, name, functions, current value) is pushed by the adapter on connect
* New: Resident snapshot on connect — all known residents are forwarded by the adapter via gRPC, replacing the previous API-based lookup
* New: `_state_cache` for roomless states (weather, car tracker, etc.) — extra-prefix states are cached separately from the device structure and kept up to date via state updates
* New: Satellite offline detection — heartbeat watchdog marks satellites as offline after 30s (3 missed heartbeats), both in Go Proxy and Python UDP server
* Removed: ioBroker REST API dependency — `requests`-based state reads replaced by local cache lookup
* Removed: MQTT transport layer — all ioBroker communication now runs exclusively over gRPC

## 0.2.1
* Fixed: Hannah must detect if a satellite silently went offline

## 0.2.0
* New: AgentNotification — ioBroker adapter sends notifications via gRPC
* New: Notify unary RPC replaces AgentMessage notification stream
* New: compatibility with iobroker.hannah v0.2.0

## 0.1.2
* New: AgentSetResident + AgentSatelliteUpdate, satellite state sync
* New: move residents.set_presence to gRPC
* New: ESP32 satellite end-to-end audio working
* New: AgentTextAnswer — Hannah pushes text command answer to adapter
* New: satellite_control + onConnected fix + _on_satellite_change gRPC push
* New: compatibility with iobroker.hannah v0.1.0
* Fixed: fix timing issue

## 0.1.1
* Fixed: optimistic cache update in control_direct

## 0.1.0
* initial Release
