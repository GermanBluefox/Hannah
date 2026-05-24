# Changelog
<!--
    Placeholder for the next version (at the beginning of the line):
    ## **WORK IN PROGRESS**
-->
## **WORK IN PROGRESS**

## 0.8.2
### ESP Firmware
* Fixed: `.history_trim` VS Code Local History directory was accidentally tracked as a git submodule — removed from index and added to `.gitignore`; fixes CI submodule init failure

## 0.8.1
### ESP Firmware
* Changed: OTA version check uses semver comparison instead of strict string equality — downgrades and git-describe suffixes (e.g. `0.8.0-1-gabcdef`) are no longer treated as available updates

## 0.8.0
### ESP Firmware
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
### ESP Firmware
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

### ESP Firmware
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
