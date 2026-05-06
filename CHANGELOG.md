# Changelog
<!--
    Placeholder for the next version (at the beginning of the line):
    ## **WORK IN PROGRESS**
-->
## **WORK IN PROGRESS**

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