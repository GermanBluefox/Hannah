# Changelog
<!--
    Placeholder for the next version (at the beginning of the line):
    ## **WORK IN PROGRESS**
-->
## **WORK IN PROGRESS**

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

### ESP Firmware
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

### ESP Firmware
* Fixed: mute command topic changed from `…/mute` to `…/mute/set`; state feedback published on `…/mute/state`
* Fixed: mute value parsing now accepts `true`/`false` in addition to `1`/`0`

## 0.12.4
### CI
* Fixed: Upload jobs fetched tags without pruning deleted ones (`--tags`) — replaced with `--tags --prune --prune-tags` so stale tags in the runner cache no longer cause `skip_if_unchanged` to compare against a non-existent previous tag

## 0.12.3
### AutoDeploy
* New: Generates a persistent device ID (UUID v4) on first start, stored in `/var/lib/hannah/autodeploy-device-id`; sent as `?device=<uuid>` with every `/latest` poll to enable accurate per-installation device counting on the Update Server

### ESP Firmware
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
### ESP Firmware
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
### ESP Firmware
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
### ESP Firmware
* New: `hannah_sensors` now publishes readings every 30s to `hannah/satellite/{device}/sensors` (retained, QoS 1); JSON payload includes `temperature`, `pressure`, `humidity`, and optionally `gas_resistance` (BME680 only)

### Hannah Core
* New: Subscribes to `hannah/satellite/+/sensors`; forwards readings to the ioBroker adapter via `AgentSensorUpdate` gRPC command

### Proto
* New: `AgentSensorUpdate` message — carries `device`, `temperature`, `pressure`, `humidity`, `gas_resistance`
* New: `sensor_update = 8` added to `AgentCommand.command` oneof

## 0.8.3
### ESP Firmware
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
