# Changelog
<!--
    Placeholder for the next version (at the beginning of the line):
    ## **WORK IN PROGRESS**
-->


## 0.45.1
### Hannah Core
* Fixed: `hannah.service` failed to start with `RuntimeError: ... depends on grpcio>=1.81.1` — `grpc_tools.protoc` bakes the locally-installed grpcio-tools version into the generated `_grpc.py` as a minimum runtime requirement, but `requirements.txt`'s old `grpcio>=1.60.0` floor didn't force an upgrade of an already-installed older grpcio on deploy. Raised the floor to `>=1.81.1` to match, and added a warning comment in `gen_proto.sh` so future stub regenerations keep grpcio-tools in step with this pin (Refs #93)

### Telegram
* Fixed: same `grpcio`/`grpcio-tools` version floor raised to `>=1.81.1`, for the same reason as Hannah Core (Refs #93)

## 0.45.0
### Hannah Core
* Added: new unary gRPC RPCs `GetRooms`/`GetGroups`/`CreateGroup`/`UpdateGroup`/`DeleteGroup`/`SetGroupRooms` on `HannahServicer` — first phase of #27's planned WebUI gRPC surface. Pure wiring onto `RoomManager`'s existing methods (#77), no new business logic; no consumer yet, this just adds the server-side API surface ahead of the future standalone `webui/` service (Refs #88, #27)
* Added: `UserManager.login_user(username, password)` — verifies via `check_password_hash` against the stored hash, constant-time even for unknown usernames (checks against a dummy hash instead of short-circuiting). Prep work for #27 Phase 3's planned `Login` RPC, not wired into gRPC yet (Refs #27)
* Changed: `GetSatellites` RPC now returns every satellite known to `RoomManager`'s DB (not just currently-connected ones), with new `room_id`/`room_display_name`/`last_seen`/`connected`/`room_mismatch` fields — the "full status" merge logic (DB + live state + room-mismatch detection) that used to live only in-process in `webui.py`'s `/satellites` route moved into the RPC itself, since the future standalone `webui/` service won't have direct `RoomManager` access. Breaking change for existing consumers, intentionally — `iobroker.hannah` updated in the same step (Refs #89, #27)
* Added: `SetSatelliteRoom`/`SetSatelliteDisplayName` RPCs on `HannahServicer` — second phase of #27's WebUI gRPC surface, pure wiring onto `RoomManager`'s existing methods, same pattern as Phase 1's Rooms/Groups RPCs (Refs #89, #27)
* Added: `Login` RPC on `HannahServicer` — third phase of #27's WebUI gRPC surface, wires the already-prepared `UserManager.login_user()` to the existing `UserResponse` shape (same as `GetUser`); failed logins return `found=false` with gRPC `UNAUTHENTICATED` (Refs #90, #27)
* Added: `GetRoutines`/`CreateRoutine`/`UpdateRoutine`/`DeleteRoutine`/`GetTriggers`/`CreateTrigger`/`UpdateTrigger`/`DeleteTrigger` RPCs on `HannahServicer` — fourth phase of #27's WebUI gRPC surface. `RoutineManager`/`TriggerEngine` gain new CRUD methods (thin wrappers around `BaseModel.create/update/delete`, no new business logic) since they previously only supported read-only matching/runtime checks. `when`/`cancel_when`/`on_response`/`actions` stay JSON-encoded string fields in the proto rather than structured messages — both are deliberately open-ended/union-shaped, modeling them rigidly would force a proto change on every new trigger condition kind (Refs #91, #27)
* Fixed: a state-based trigger created via the new `CreateTrigger`/`UpdateTrigger` RPCs would never fire until the next ioBroker-adapter reconnect, because the adapter only re-subscribes to trigger-referenced states (`WatchMore`) on connect. `TriggerEngine` now takes an `on_change` callback that re-pushes the current `WatchMore` set right after a create/update (Refs #91, #27)
* Added: new `SettingsManager` (`settings_category`/`settings` tables, hierarchical via self-referencing `parent`) plus `GetSettings`/`UpdateConfig`/`CreateSetting`/`DeleteSetting` RPCs on `HannahServicer` — final phase of #27's WebUI gRPC surface. Moves `ble.tags`, `cars`, `nlu.*`, `llm.system_prompt` and `iobroker.state_names` out of static `config.yaml` into editable DB storage; `core/deploy/migrate_config_settings.py` does the one-time cutover. Unlike earlier phases, this one is wired into runtime immediately: `main.py` now builds the same `cfg`-shaped dicts `NLU`/`CarTracker`/`BleLocationEngine`/`IoBrokerClient` already expected, just sourced from `SettingsManager` instead of `cfg.get(...)` for these 5 areas — no changes needed in those 4 modules themselves, with a fallback to the old `cfg`/code defaults wherever a category hasn't been migrated yet (Refs #92, #27)

### Hannah Proxy
* Changed: updated proto files to reflect the newest Core changes (#27 Phases 1–5: Rooms/Groups, Satellites, Login, Routines/Triggers, Settings) (Refs #27)

### Telegram
* Changed: updated proto files to reflect the newest Core changes (#27 Phases 1–5: Rooms/Groups, Satellites, Login, Routines/Triggers, Settings) (Refs #27)

## 0.44.0
### Hannah Core
* Changed: `routines.yaml`/`triggers.yaml` replaced by SQLite (`routines`/`triggers` tables, `hannah.db`) — new `Routine`/`Trigger` models (`hannah.models.routine`/`hannah.models.trigger`), nested condition/action structures (`when`, `cancel_when`, `on_response`, `triggers`, `actions`) stored as JSON columns, same pattern as `LinkedAccount.provider_payload`. `RoutineManager`/`TriggerEngine` now take a `db` callable instead of a file path; eliminates the mtime-based hot-reload entirely (SQL query is always current). Part of #27's planned WebUI scope — Routinen/Trigger get full CRUD via the WebUI once it lands (Refs #27)
* Added: `core/deploy/migrate_triggers_routines.py` — one-time, idempotent migration of existing `routines.yaml`/`triggers.yaml` content into `hannah.db`, analogous to `migrate_rooms_db.py` for #77 (Refs #27)

## 0.43.1
### Hannah Core
* Fixed: the room fallback for voice commands without an explicit room (`main.py`) only checked `udp_server.get_registered_room()` — proxy-connected satellites are tracked separately (`grpc_servicer._proxy_satellites`) and were never consulted, even though RoomManager already had a room assigned for them at registration time. Now resolves directly via `room_manager.get_satellite_room()`, independent of the live connection type (Refs #87)
* Removed: `device_rooms` config (static MQTT-satellite room fallback) — dead since #35 removed room reporting from satellite NVS entirely, making RoomManager the sole authority; no legacy satellites needing this fallback remain in active use (Refs #87)
* Removed: `residents.user_roomie`/`user_roomies` config (static list of "real" roomie IDs used to tell residents apart from guests in unscoped presence queries) — `ResidentsClient.is_home()` now derives this from the User Registry (new `UserManager.get_roomie_ids()`, based on `User.type == "roomie"` via the linked `residents` account) instead of duplicating it in config, consistent with #72 (Refs #87)

## 0.43.0
### Satellite Firmware
* Added: `POST /nvs` HTTP endpoint — lets the ioBroker adapter remotely update whitelisted NVS keys (`wifi_ssid`, `wifi_pass`, `mqtt_broker`, `mqtt_port`, `ota_channel`, `seed`, `ww_threshold`) over WiFi without physical/WebSerial access, then restarts. Secured by a new, dedicated `nvs_token` — kept separate from `ota_token` since that one isn't guaranteed identical across the fleet (overridable per-device via `/settings`) and can't double as a shared secret. Empty `nvs_token` = endpoint fully disabled (fail closed) (Refs #36)

## 0.42.1
### Hannah Core
* Fixed: `UserManager.get_user_by_id()` crashed with `ValueError` on a non-numeric `user_id` instead of returning `None` — Voice-ID returns the literal string `"unknown"` as `speaker_user_id` when recognition confidence is too low, which flows straight into this lookup via `main.py`'s `_speaker_context()`/`_resolve_roomie_id()`. Those two call sites also bypassed `UserManager`'s cache entirely by calling `User.get()` directly; now go through `get_user_by_id()` like everything else (Refs #84)

## 0.42.0
### Hannah Core
* Changed: BLE-Indoor-Lokalisierung (`ble_location.py`) ist jetzt von ioBroker Residents entkoppelt und setzt direkt `User.presence`, statt über `ResidentsClient`/`Resident` zu laufen. Grund: `ResidentsClient._residents` wird nur asynchron über die gRPC-Verbindung zum Adapter befüllt (Einzel-Updates oder das `send_residents`-Snapshot, #73) — BLE-Reports kommen aber unabhängig per MQTT und können direkt nach einem Core-Neustart schon eintreffen, bevor der Adapter verbunden ist, was zu `log.warning(...Tippfehler in config.yaml?)` führte, obwohl kein Tippfehler vorlag. `UserManager` lädt dagegen synchron aus der lokalen SQLite-DB, keine Race möglich
* Changed: `config.yaml`s BLE-Tag-Einträge nutzen jetzt `username` statt `roomie`/`type` — Auflösung zu `user_id` passiert einmalig beim Config-Laden (nicht mehr pro Sichtung), ein unbekannter Username wird sofort beim Start gewarnt statt erst bei der ersten Sichtung
* Added: `UserManager.dump_present_users()`, aufgerufen bei jedem `AgentConnect` — pusht "anwesend" für jeden User, den Hannah aktuell als zuhause kennt, Richtung ioBroker. Schließt eine Lücke aus #82: BLE-Sichtungen können eintreffen, bevor der Adapter überhaupt verbunden ist, das zugehörige arrival-Event verhallt dann ungehört. Sendet bewusst nur "anwesend", nie "weg" — ioBroker kann eine eigene, unabhängige Presence-Quelle haben (z.B. WLAN-Controller-Tracking), die nicht überschrieben werden soll (Refs #83)

## 0.41.2
### Hannah Core
* Fixed: the `/satellites` WebUI page's "Meldet sich als" warning compared a live-resolved room *ID* (e.g. `leonie_schlafzimmer`) against the assigned room's *display name* (e.g. `Leonie Schlafzimmer`) — a false positive for every room whose ID isn't spelled identically to its display name, even though the satellite was correctly assigned. The satellite/proxy never sends a room at all (`SatelliteRegistration.room` was deliberately removed — RoomManager is the sole authority); the mismatch check now compares room ID against room ID, resolving the live ID to a display name only for the message text (Refs #81)

## 0.41.1
### Hannah Core
* Fixed: a satellite's "last seen" timestamp froze forever after its initial registration — `udp_server.py` only refreshed it on the `"register"` control packet, never on the periodic `"heartbeat"` ones; `grpc_server.py`'s `NotifySatelliteRegistered` (proxy-routed satellites) never refreshed it at all, not even once. Since the Go proxy also never forwards individual satellite heartbeats to Core (only one heartbeat per proxy connection, covering every satellite behind it), `RegisterProxy`'s heartbeat drain loop now refreshes `last_seen` for every currently-known proxy satellite on each proxy heartbeat as a pragmatic stand-in — a real per-satellite heartbeat would need a proxy protocol change, deliberately out of scope here (Refs #80)

## 0.41.0
### Hannah Core
* Fixed: `BaseModel.create()`/`update()`/`delete()` never rolled back on a failed write (e.g. `IntegrityError` from a UNIQUE violation) — the implicitly-started transaction stayed open on that connection, which then blocked every other write to the same DB file with `database is locked` until the connection happened to get garbage-collected. Found while writing an end-to-end test for #77; also affects `User`/`LinkedAccount` already in production (e.g. a duplicate username/email via `/users/create`) (Refs #79)
* Added: `Room`/`Group`/`Satellite` models, `rooms`/`groups`/`group_rooms`/`satellites` tables added to `hannah.db`'s schema (Refs #77)
* Changed: `RoomManager` now uses the `hannah.models` layer instead of hand-rolled `sqlite3` — same public API/return shapes, so `main.py`/`webui.py`/`grpc_server.py` needed no changes beyond the constructor call. `group_rooms` (pure n:n pivot) stays model-less, queried via joins; `Satellite`'s pairing rename (device_id is the PK) stays raw SQL since `BaseModel.update()` never touches PK columns (Refs #77)
* Added: `core/deploy/migrate_rooms_db.py` — one-time, idempotent migration of the real production data in the old standalone `rooms.db` into `hannah.db`'s new tables; ships with the next core release since `deploy/` is part of the release tarball (Refs #77)

## 0.40.6
### Hannah Core
* Fixed: `hannah.db` (User-Registry, Issue #72) was deleted on every AutoDeploy update — `DB_PATH` defaulted to a path relative to `__file__` (`.../core/hannah/hannah.db`), landing it *inside* the `hannah/` package directory that `autodeploy.py`'s `_extract_and_copy()` wipes and replaces wholesale on each deploy. Now defaults to the relative path `"hannah.db"`, resolved against the service's working directory like `room_manager.py`'s `rooms.db` and `memory.py`'s `memory.db` already do (Refs #76)

## 0.40.5
### Hannah Core
* Added: "Löschen"-Button auf der `/users`-WebUI-Seite — `username` ist im Edit-Formular absichtlich readonly (Identifier für Telegram `/verknuepfen` u.a.), ein Vertipper beim Anlegen (z.B. Groß-/Kleinschreibung) ließ sich bisher nur direkt in der DB korrigieren. Neue `UserManager.delete_user()` räumt zusätzlich den In-Memory-Cache/Wiring-State auf, `linked_accounts` läuft per `ON DELETE CASCADE` mit (Refs #75)

## 0.40.4
### Hannah Core
* Fixed: the adapter's initial `send_residents` snapshot (sent once per `AgentConnect`, all currently known residents in one message) was never wired up on the Core side — `on_agent_send_residents` was passed as `None` with a `#TODO`, so `HannahServicer` always fell through to `log.warning("[grpc] Unrecognized AgentMessage payload: send_residents")` and Core had to wait for the next individual `resident_update` per resident instead (Refs #73)

## 0.40.3
### Hannah Core
* Changed: `User.id` and every `*Request.user_id`/`GetUserRequest.id` field (LinkAccount, UnlinkAccount, SetTrustLevel, SetSystemMessages, GetUser) are now `int32` instead of `string` on the wire, matching the actual `users.id` SQLite column — found while debugging `/verknuepfen` always failing with `Exception calling application: '3'`. `EnrollVoiceprintRequest.user_id`/`SubmitSatelliteAudioRequest.speaker_user_id` stay `string` on purpose — those cross into the Voice-ID HTTP service, which treats the identifier as an opaque key
* Fixed: `UserManager.get_user_by_id()` looked a (possibly string) `user_id` up against its int-keyed cache after caching under the int — `self._users[user_id]` then missed with `KeyError` for any non-int input; now normalizes to `int(user_id)` up front regardless of what the proto wire type guarantees
* Fixed: `_user_to_pb` read `acc.service` to build the `linked_accounts` map, but the `LinkedAccount` model attribute is `.provider` — crashed with `AttributeError` on `GetUsers`/`GetUser` for any user with at least one linked account
* Fixed: `BaseModel.__init__` called `json.loads(value)` on every JSON-typed column unconditionally, including an empty string — `provider_payload` defaults to `""` when a caller (e.g. Telegram's `/verknuepfen`) never sets it, so the very next read of that row raised `JSONDecodeError`. Empty string now deserializes to `None`
* Added: regression tests in `core/tests/test_grpc_server.py` exercising `LinkAccount` and `_user_to_pb` against a real (non-mocked) `UserManager`/SQLite DB — all four bugs above were invisible to the existing mock-based tests

### Hannah Proxy
* Changed: proto copy synced with the `User`/`*Request.user_id` `string` → `int32` change above — mirror-only, the proxy itself never touches these fields

### Telegram
* Changed: proto copy synced with the `User`/`*Request.user_id` `string` → `int32` change above — `user.id` was already typed `int` in `grpc_client.py`'s signatures, so no source changes needed, just regenerated stubs

## 0.40.2
### VoiceID
* Added: `voiceid/deploy/install-macos.sh` now passes `--config /opt/hannah/etc/voiceid.yaml` to the service — config support already existed in `app.py` but nothing on macOS ever wired it up, so `unknown_threshold`/`uncertain_threshold`/host/port were silently stuck on defaults

## 0.40.1
### AutoDeploy
* Fixed: the self-update restart path (when autodeploy deploys a newer version of itself) still hardcoded `systemctl restart` — `_restart_service()` got the macOS/launchd platform switch earlier, but this is a separate call site that was missed, crashing with `FileNotFoundError` on the Mac Mini as soon as a newer autodeploy release was available

## 0.40.0
### Hannah Core
* Added: new SQLite-backed user/linked-account model (`users`, `linked_accounts`), replacing ioBroker Residents as the source of authority for Hannah's users — accounts, trust levels, and provider links now live natively in Hannah Core (Refs #72)
* Added: `linked_accounts.external_id` column — separates the per-provider lookup key from `provider_payload` (now JSON metadata only), since the payload's shape differs per provider (residents: `roomie_id` nested in JSON; telegram: raw ID; OAuth: tokens) and can't be queried generically. `LinkedAccountLookup` proto message gets an `external_id` field to carry the search value (Refs #72)
* Fixed: `GetUser`'s `linked_account` lookup branch joined `linked_accounts` without an `ON` clause and filtered via a non-existent `linked_accounts__provider` kwarg (`Query.where()` has no Django-style relation traversal); now joins and filters explicitly on `provider` + `external_id` (Refs #72)
* Fixed: `GetUser`'s `user_name` lookup queried a non-existent `users.user_name` column — the actual DB/model column is `username` (Refs #72)
* Fixed: `_user_to_pb` called dict-style `.get()` on `User` model instances, which silently resolved to `BaseModel.get()` (a classmethod) instead of raising — crashed with `AttributeError` on every `GetUsers`/`GetUser` call; now reads model attributes directly (Refs #72)
* Fixed: `GetUser` mapped every lookup failure through `_ambiguous_message` (built for the old `AmbiguousResidentError`) — with the new model "not found" is the only failure mode (`one_or_404()` raises plain `LookupError`), so it now returns `NOT_FOUND` instead of crashing on the missing `.roomie_id`/`.types` attributes (Refs #72)
* Removed: `user_registry.py` — the old ioBroker-Residents-driven SQLite registry (UUID/`roomie_id`/trust level) is fully superseded by the new `hannah.models` layer (Refs #72)
* Changed: `EnrollVoiceprintRequest.roomie_id` → `.user_id`, `SubmitSatelliteAudioRequest.speaker_roomie_id` → `.speaker_user_id` — Voice-ID now identifies speakers by Hannah's own stable `users.id` instead of an ioBroker roomie_id, consistent with decoupling account identity from ioBroker entirely (Refs #72)
* Fixed: `_speaker_context()` queried `User.get(db, user_name=...)` against a column that doesn't exist (the actual column is `username`) and then read the result with dict-style `user["display_name"]`/`user.get("trust_level", 5)` — both crash (or silently return a bound method) on a `User` model instance; now resolves by `id` and reads plain attributes (Refs #72)
* Added: `_resolve_roomie_id()` in `main.py` — bridges a Hannah `user_id` back to its linked ioBroker `roomie_id` (via `linked_accounts[provider="residents"].provider_payload`) for the two places that still need a name-shaped identifier: `car_tracker`'s `owner_roomies` matching and `residents.set_user_home`/`set_user_away` (Refs #72)
* Added: WebUI page `/users` — lists Hannah Users and lets an admin link/unlink them to a known ioBroker Resident (Roomie/Guest/Pet), using the same `link_account`/`unlink_account` calls Telegram's `/verknuepfen` already goes through. Backed by a new `ResidentsClient.all_residents()`. Manual stand-in until residents get auto-linked on arrival (Refs #72)
* Fixed: `UserManager.create_user()` never passed `display_name`/`type` to `User.create()` — both are `NOT NULL` without a default, so every call crashed with `IntegrityError`; now defaults `display_name` to the username and `type` to `"roomie"`, both overridable (Refs #72)
* Added: WebUI `/users/create` and `/users/<id>/edit` — an admin can now create and edit Hannah Users directly in the WebUI instead of via raw SQL, which was only ever meant for the initial bootstrap (Refs #72)
* Added: bidirectional mood sync between a Hannah User and its linked Resident. Pull (ioBroker → Hannah) via a new `ResidentsClient.on_mood_changed()`, mirroring the existing arrival/departure dispatch. Push (Hannah → ioBroker) via a new `AgentSetResidentMood` command — kept separate from `AgentSetResident` rather than adding an optional field to it, to avoid any ambiguity between "mood intentionally 0" and "mood not set" on the wire. `UserManager` now tracks presence- and mood-wiring per user in separate sets, so `set_residents_pusher()` and `set_mood_pusher()` can be bound in either order without one blocking the other's retroactive wiring (Refs #72)

### Hannah Proxy
* Changed: Voice-ID client (`internal/voiceid/client.go`) and `SubmitSatelliteAudio` follow the same `roomie_id` → `user_id` rename — `IdentifyResponse.RoomieID` → `.UserID`, `X-Roomie-ID` HTTP header → `X-User-ID`, `SubmitSatelliteAudioRequest.SpeakerRoomieId` → `.SpeakerUserId` (Refs #72)

### VoiceID
* Changed: `/enroll` and `/identify` speak `user_id` instead of `roomie_id` — `X-Roomie-ID` request header → `X-User-ID`, `{"roomie_id": ...}` response field → `{"user_id": ...}`; the service itself stores/matches by opaque key either way, only the wire naming changes (Refs #72)
* Changed: `voiceid/deploy/install-macos.sh` rewritten to install from the Update Server (matching every other `install.sh` in the repo) instead of a direct git clone. Also fixes two bugs in the old script found while planning a reinstall: `--uninstall` deleted `voice_profiles` despite claiming to keep them (nested inside the install dir it then `rm -rf`'d), and it crashed outright on an unset `$MEM_SYMLINK`. Code/venv now live in `/opt/hannah/voiceid`, voice profiles/cache in a separate `/opt/hannah/voiceid-data/` that no install/update/uninstall step ever touches

### Telegram
* Changed: `/verknuepfen` and `/trustlevel` resolve users by `username` instead of `roomie_id` — `get_user_by_roomie()` and its `resident_type` disambiguation argument (made obsolete now that usernames live in Hannah's own `users` table instead of colliding across ioBroker resident types) are replaced by `get_user_by_username()`; linking now threads the resolved `user.id` through to `LinkAccountRequest` instead of a bare username string (Refs #72)
* Changed: client-side proto usage follows the `User`/`LinkedAccountLookup`/`*Request` field renames that came with Hannah's own user model — `uuid` → `id`, `roomie_id` → `user_name`, `LinkedAccountLookup.service`/`.account_id` → `.provider`/`.external_id`, `SetSystemMessagesRequest.uuid` / `SetTrustLevelRequest.roomie_id` / `LinkAccountRequest.roomie_id` → `.user_id` (Refs #72)
* Fixed: the rename above initially landed only half-applied and would have taken the bot down hard — `LinkedAccountLookup` was still built with the old `service`/`account_id` field names, which fails outright on every `GetUser` linked-account lookup, i.e. every authenticated message (`_is_known_user`/`_get_user`/`_has_trust` all go through it); leftover `user.roomie_id`/`.uuid`/`.username` accesses on the renamed `User` message, plus a stray `get_user_by_roomie()` call in `send_car_parked_to_all()` that was never updated when the method itself got renamed, would additionally have broken system notifications, `/systemmessages`, the trust-level confirmation reply, and car-parked-owner pings respectively (Refs #72)
* Changed: linking/help copy (`/verknuepfen` docstring, `_WELCOME`, `_UNKNOWN_USER`, command usage strings) now asks for a username instead of a Roomie-ID; `/verknuepfen` and `/trustlevel` drop the now-meaningless `[roomie|guest|pet]` disambiguation argument (Refs #72)

### AutoDeploy
* Added: macOS support — `_restart_service()` uses `launchctl kickstart -k system/<label>` instead of `systemctl restart` when running on Darwin; new `deploy/install-macos.sh` bootstraps the agent itself as a LaunchDaemon via the Update Server, mirroring the existing Linux installer. The voiceid Mac install still bypasses the Update Server entirely (separate concern, not changed here)

## 0.39.1
### Hannah Core
* Fixed: `UserRegistry._init_db()`'s `type`-column migration (#64/0.39.0) did `ALTER TABLE users RENAME TO users_old`, which made SQLite automatically rewrite `linked_accounts.user_uuid`'s FOREIGN KEY to point at `users_old` — the migration then dropped that table, leaving `linked_accounts` referencing a table that no longer existed. Every `link_account()` call failed with `FOREIGN KEY constraint failed` (surfaced in Telegram as `/verknuepfen` always failing). `_init_db()` now rebuilds `linked_accounts` too, repointed at the new `users` table *before* `users_old` is dropped (dropping it first fails too — for the same reason) (Refs #69)
* Fixed: `get_by_roomie`/`link_account`/`set_trust_level` resolved a resident by `roomie_id` alone — if a Guest and a Roomie (or a Pet) share a name, `fetchone()`/`UPDATE ... WHERE roomie_id = ?` would silently act on whichever row SQLite happened to return, with no guarantee it's the right one (e.g. linking your Telegram account to a same-named pet instead of yourself). All three now accept an optional `resident_type` and raise a new `AmbiguousResidentError` (naming the colliding types) when it's omitted and more than one active match exists, instead of guessing (Refs #69)
* Changed: `GetUserRequest`/`LinkAccountRequest`/`SetTrustLevelRequest` get an optional `ResidentType type` field to pass the disambiguation through gRPC; the corresponding `HannahServicer` handlers catch `AmbiguousResidentError` and fail the RPC with `FAILED_PRECONDITION`, naming the colliding types in the details (Refs #69)
* Changed: `set_system_messages` now identifies the target by `uuid` instead of `roomie_id` — its only caller (Telegram `/systemmessages`) always acts on the requesting user, who is already uniquely resolved via their linked Telegram account beforehand, so threading `roomie_id` (+ the collision risk that comes with it) through was pointless. `SetSystemMessagesRequest.roomie_id`/`.type` replaced by `.uuid` (never released, safe to change outright) (Refs #69)

### Hannah Proxy
* Changed: proto updated — `GetUserRequest`/`LinkAccountRequest`/`SetTrustLevelRequest` get an optional `type` field, `SetSystemMessagesRequest.roomie_id`/`.type` replaced by `.uuid` (Refs #69)

### Telegram
* Changed: `/verknuepfen <roomie-id> [roomie|guest|pet]` — the type is now an optional second argument, needed only when `roomie-id` is ambiguous; the bot surfaces Hannah Core's `FAILED_PRECONDITION` details instead of swallowing them as a generic "not found" (`get_user_by_roomie`/`link_account` now thread `resident_type` through and return the real error message) (Refs #69)
* Changed: `/trustlevel <roomie-id> <0-10> [roomie|guest|pet]` — same optional type argument as `/verknuepfen`, for the same reason (admin-only command, but still needs to disambiguate a colliding `roomie-id`) (Refs #69)

## 0.39.0
### Hannah Core
* Changed: `is_guest: bool` replaced by a `ResidentType` enum (`ROOMIE`/`GUEST`/`PET`) throughout the residents proto surface (`AgentResident`, `AgentSetResident`); `AgentResidentUpdate` removed and merged into `AgentResident` (now also carries `name`, `optional mood_level`, `presence_state`), used directly as the `resident_update` payload — groundwork for Pet support (Refs #64)
* Added: `core/hannah/residents/` package — `Resident` base class (`Roomie`/`Guest`/`Pet` subclasses) replaces the flat boolean/cache-dict model; a minimal event system (`on()`/`_emit()`) plus `update()` detect arrival/departure (and `mood_changed`) transitions on the object itself instead of an external string-keyed cache, so Pets get the same presence semantics as Roomies/Guests for free (Refs #64)
* Changed: `ResidentsClient` (`core/hannah/residents.py` → `core/hannah/residents_manager.py`) drops the MQTT-topic-string parsing path entirely — residents have been driven exclusively via gRPC for months, the string cache was dead weight; adds `get_or_create(roomie_id, cls)` as a persistent per-resident registry. The four separate `on_arrival`/`on_departure`/`on_guest_arrival`/`on_guest_departure` callbacks collapse into one `on_arrival`/`on_departure` pair that receives the `Resident` object itself; consumers branch on type via `isinstance` where behavior actually differs (Refs #64)
* Fixed: `set_guest_home`/`set_guest_away` passed a bare `1` where the old `is_guest` bool argument used to go — after the `ResidentType` enum landed this silently collided with `ROOMIE = 1`, so outbound guest-presence writes tagged guests as roomies; now passes `pb.ResidentType.GUEST` explicitly
* Fixed: `_on_agent_set_resident` discarded the incoming `resident_type` and always called `residents.set_presence()` without it — adapter-initiated `SetResident` commands for guests were written through as roomie presence updates
* Fixed: `resident_update` handling in `grpc_server.py` never read the proto's `name` field, so Hannah never learned a resident's display name from gRPC presence updates; also `r.has_field(...)` → `r.HasField(...)` (would have raised `AttributeError` on the first update carrying a `mood_level`)
* Added: `User` class in `user_registry.py` — a thin decorator around `Resident` (Roomie/Guest/Pet) adding the registry-only fields (UUID, trust level, system messages) that don't belong in the presence domain. Pets get a `User` entry and a `trust_level` just like Roomies/Guests instead of being excluded — a SmartHome's permission model applies to every resident it lets live there, not just the humans (e.g. an electronic cat flap gated by `trust_level`). `UserRegistry.sync()` now resolves each incoming resident's live `Resident` instance via `ResidentsClient.get_or_create()` (shared object, not a duplicate) and wraps it; query methods (`get_all`/`get_by_roomie`/etc.) still return plain dicts for now (Refs #64, follow-up to replace the whole query API tracked in #68)
* Fixed: `ResidentsClient._residents` and the `users` table were keyed by `roomie_id` alone — a Guest and a Roomie with the same name (separate prefixes in the residents adapter, perfectly legal) would have collided: `get_or_create()` would silently return the wrong type's instance once a key existed, and the `users` table's `UNIQUE(roomie_id)` constraint would reject the second insert outright. Both are now keyed by `(roomie_id, type)` — `ResidentsClient` via a `(resident_cls, roomie_id)` tuple key plus a new `get_or_null(roomie_id, cls)` (returns `None` instead of creating, for callers like the BLE tracker that should only ever reference an already-known resident); `users` via a `UNIQUE(roomie_id, type)` constraint, migrated from the old single-column `UNIQUE(roomie_id)` with a table rebuild (existing rows get `type=NULL` since the real type was never recorded before — `sync()` backfills it from the next live snapshot instead of inserting a duplicate)
* Fixed: `UserRegistry.sync()` deactivation/reactivation matched rows by `roomie_id` instead of `uuid` — would have deactivated/reactivated the wrong row once two residents share a `roomie_id` across types
* Fixed: `UserRegistry.sync()` recomputed `resident_ids` and reassigned `residents = list(residents)` inside the per-resident loop (only correct once a `next()` had already run), and incremented `added` for every already-known resident on every sync call, not just newly inserted/reactivated ones
* Added: BLE tags can now reference Pets, not just Roomies — `ble.tags[]` in `config.yaml` gets an optional `type` field (`roomie`/`guest`/`pet`, default `roomie`) alongside `roomie`, since a `roomie_id` alone isn't unique across types. On a location change, `_on_ble_location_change` resolves the tag's `(roomie, type)` via `ResidentsClient.get_or_null()` — only acting on an already-known resident, never creating a phantom one from a config typo — and sets `presence_state` to home. This is one-directional on purpose: a BLE sighting is a strong "home" signal, but a stale/lost tag is not a reliable "away" signal (weak reception ≠ left the house), so a disappearing tag never resets presence (Refs #64)

### Hannah Proxy
* Changed: proto updated — `ResidentType` enum replaces `is_guest` bool, `AgentResidentUpdate` merged into `AgentResident` (Refs #64)

### Telegram
* Changed: proto updated — `ResidentType` enum replaces `is_guest` bool, `AgentResidentUpdate` merged into `AgentResident` (Refs #64)

## 0.38.3
### Hannah Core
* Added: `IoBrokerClient.handle_state_update()` now logs a `WARNING` (once per suffix, no log spam on repeated updates) when a live state update arrives for a suffix missing from `config.yaml`'s `iobroker.state_names`, instead of silently dropping it — found via a stale production `config.yaml` that never got the `iaq`/`co2_equiv`/`voc_equiv` entries added for #21, causing those values to freeze at the last gRPC snapshot indefinitely without any visible symptom (Refs #21)

## 0.38.2
### Satellite Firmware
* Added: WiFi AP-Setup-Modus verlässt sich nicht mehr endgültig — ein periodischer Timer (alle 10 Minuten, gleiches Muster wie der bestehende SNTP-Retry) versucht im Hintergrund das ursprüngliche Netz wiederzufinden, parallel zum laufenden AP (kein Scan-/Konfigurations-Unterbruch). Bei Erfolg wird der AP nur sofort abgeworfen, wenn kein Client mehr am Captive Portal hängt — sonst wartet der Cutover bis zur letzten Trennung, damit eine laufende Konfiguration (z.B. neuer PSK bei Netz-Umzug) nicht durch einen verschwindenden AP unterbrochen wird. Kein Retry bei unkonfigurierten Geräten ohne hinterlegtes WiFi (Refs #52)

## 0.38.1
### Hannah Core
* Added: `RoomManager.sync_rooms()` now detects rooms that disappeared from the ioBroker enum catalog and removes them; satellites that were assigned to a vanished room have their `room_id` nulled (kept in the DB, not deleted) and are reported back to the caller, which pushes `agent_satellite_deleted()` to the adapter so the now-roomless satellite's object tree is cleaned up there too (Refs #51)
* Fixed: `NotifySatelliteRegistered`/`NotifySatelliteGone` pushed `agent_satellite_update()` to the adapter twice per connect/disconnect — once directly, once via the `_on_satellite_change` online/offline diff in `main.py`; the direct calls are removed, `_on_satellite_change` now resolves `display_name` itself via `RoomManager.resolve_satellite_name()` (Refs #53)
* Fixed: the UDP-direct satellite path (fallback when no proxy is connected) took its room straight from the satellite's own registration payload, completely bypassing `RoomManager` — a satellite has had no way to know its own room since the room/group management rework (#25); it now resolves the room via `RoomManager` like the proxy path already does, and isn't tracked/forwarded to the adapter at all without one (Refs #53)

## 0.38.0
### Hannah Core
* Added: `humidity_sensor` sensor category — `_CATEGORY_STATES["humidity_sensor"]` with `current` (%); reuses the existing generic category-query mechanism, same pattern as `temperature_sensor` (Refs #47)
* Added: `category_words` for humidity (luftfeuchtigkeit, luftfeuchte, feuchtigkeit, feuchte) in `config.yaml`/`config.example.yaml` (Refs #47)
* Changed: satellite deletion moved fully into Hannah Core — `RoomManager.delete_satellite()` + new Web UI "Löschen" button on `/satellites` (only shown for offline satellites) replace the old AdminUI-only path that never touched Core's DB, leaving ghost entries behind; `HannahServicer.agent_satellite_deleted()` pushes the new `AgentSatelliteDeleted` command (`AgentCommand.satellite_deleted`) to tell the adapter to remove the object tree (Refs #42)

### Hannah Proxy
* Changed: proto updated — `AgentSatelliteDeleted` added (Refs #42)

### Telegram
* Changed: proto updated — `AgentSatelliteDeleted` added (Refs #42)

## 0.37.1
### Hannah Core
* Fixed: `IoBrokerClient.handle_state_update` silently dropped live updates for state suffixes missing from `config.yaml`'s `iobroker.state_names` — affected `iaq`/`co2_equiv`/`voc_equiv` (added in the `air_quality_sensor` category) since they were never added there; the initial gRPC snapshot writes the raw suffix directly (no `state_names` translation), so affected values froze at whatever the last snapshot held instead of updating live (Refs #21)
* Fixed: `_describe_category` repeated the device name twice in single-device responses (e.g. "Sofaecke im Wohnzimmer: Sofaecke: okay, ...") — the per-device name prefix is now only added when there's more than one device in the room; affects all single-device sensor categories (temperature, window, door, air quality), not just air quality
* Changed: `air_quality_sensor` category — `co2_equiv`/`voc_equiv` units now read "ppm CO₂"/"ppm VOC" instead of plain "ppm" so the two values are distinguishable by voice

### Telegram
* Added: `_device_status_text` now renders `iaq`/`co2_equiv`/`voc_equiv` for air-quality devices (was missing entirely — the device showed up in `/haus` menus with no values); `_iaq_label` mirrored from Hannah Core for the same plain-text assessment

## 0.37.0
### Hannah Core
* Added: `air_quality_sensor` sensor category — `_CATEGORY_STATES["air_quality_sensor"]` with `iaq` (rendered as plain-text assessment via new `_iaq_label()`: 0–50 good, 51–100 okay, 101–150 slightly polluted, >150 bad), `co2_equiv` and `voc_equiv` (ppm); reuses the existing generic category-query mechanism instead of a Hannah-specific cache, so any ioBroker-known air quality sensor works, not just Hannah's own satellites (Refs #21)
* Added: `category_words` for air quality (luftqualitaet, iaq, co2, voc, luftguete, luft, raumluft) in `config.yaml`/`config.example.yaml` (Refs #21)

## 0.36.2
### Satellite Firmware
* Fixed: `bsec_set_configuration` returned `BSEC_E_CONFIG_VERSIONMISMATCH` (-34) — `libalgobsec.a` (esp32s3) was linked from the BSEC2 "Selectivity" algorithm variant, while `bme680_iaq_33v_3s_4d.bin` is a config for the classic "IAQ" variant; replaced both with the matching `bsec_IAQ` build (BSEC 2.6.1.0 generic release) and stripped a 4-byte length header that the source `.config` file carries in front of the raw 492-byte config blob (closes #24)
* Fixed: unused variable `cfg` in `status_handler` (`hannah_webserver.c`) — leftover from the device-ID/room removal in #26/#32, never read (closes #46)

## 0.36.1
### Hannah Core
* Added: `RoomManager` cleans up provisioned-but-never-paired satellite seeds older than `seed_ttl_days` (default 7) via a background thread, configurable in `config.yaml` (Refs #41)

## 0.36.0
### Hannah Core
* Added: `AgentRoomSnapshot`/`AgentRoom` proto message + `AgentMessage.send_rooms` — adapter now sends the full `enum.rooms.*` catalog (independent of devices) on connect and on enum change; `RoomManager.sync_rooms()` is fed from it via a new `on_agent_room_snapshot` callback, so provisioning a satellite into a brand-new room with no devices yet no longer fails with `FOREIGN KEY constraint failed` (Refs #40)

### Hannah Proxy
* Changed: proto updated — `AgentRoomSnapshot`/`AgentRoom` added (Refs #40)

### Telegram
* Changed: proto updated — `AgentRoomSnapshot`/`AgentRoom` added (Refs #40)

## 0.35.0
### Hannah Core
* Fixed: `NotifySatelliteRegistered` now skips satellites with no room in RoomManager instead of propagating empty `room_id` to the adapter — prevents ghost registrations from unpaired MAC-based device IDs (Refs #37)

### Hannah Proxy
* Refactor: removed `room` from all Go callbacks and gRPC calls — `AudioCallback`, `SatelliteChangeCallback`, `SubmitSatelliteAudio`, `NotifySatelliteRegistered`, `NotifySatelliteGone`; `SatelliteInfo.Room` removed; `RegisteredDevices()` now returns `[]string` (Refs #38)

## 0.34.1
### Hannah Core
* Fixed: `_on_agent_satellite_control` (mute/dnd/volume/announcement/announcement_ssml/announcement_rephrase via the adapter) matched only against the satellite's self-reported room, which is always empty since #35 removed room reporting from firmware — now uses `_resolve_targets()` like all other room-based routing, so `RoomManager` assignments are honored (closes #39)

## 0.34.0
### Hannah Core
* Changed: `GrpcServer.NotifySatelliteRegistered` no longer uses the satellite-reported room as fallback; `RoomManager` is now the sole authority for room assignment (Refs #35)
* Changed: `GrpcServer.SubmitSatelliteAudio` resolves room from `_proxy_satellites` / `RoomManager` instead of `request.room` (Refs #35)
* Changed: proto — `SatelliteRegistration.room` (field 2) reserved; room assignment is now a server-side concern only (Refs #35)

### Hannah Proxy
* Changed: proto updated — `SatelliteRegistration.room` (field 2) reserved (Refs #35)
* Note: proxy Go code still passes `room` in callbacks/RPCs — full cleanup pending proxy refactoring

### Telegram
* Changed: proto updated — `SatelliteRegistration.room` (field 2) reserved (Refs #35)

### Firmware (satellite-esp)
* Changed: removed `room` field from `hannah_config_t`, NVS, and register JSON message (Refs #35)
* Changed: removed `HANNAH_ROOM_NAME` from Kconfig (Refs #35)

### ioBroker Adapter
* Changed: `NvsDialog` — removed `room` field; re-flashing NVS no longer requires room selection; `provisionSatellite` call no longer passes `roomId` (Refs #35)
* Changed: `FlashDialog` — room free-text field replaced with dropdown populated from `enum.rooms.*`; `provisionSatellite` now called before flash with `seed` + `roomId`; `seed` written to NVS partition (Refs #35)
* Changed: `provisionSatellite` sendTo handler — `roomId` is now optional; enables seed-only re-provisioning without changing the satellite's room assignment (Refs #35)

## 0.33.0
### Hannah Core
* Changed: `AgentDevice.room` now carries the enum ID segment (e.g. `wohnzimmer`) instead of the German display name; `room_names` map added with all available languages for NLU matching (Refs #33)
* Changed: `IoBrokerClient` keys rooms by enum ID; `Device.room_display_name` carries the German display name for spoken responses (Refs #33)
* Changed: `NLU._find_room` matches on display name (`room_names["de"]`) instead of the enum key — NLU behaviour unchanged, but now stable when enum IDs differ from German names (Refs #33)
* Changed: `GrpcServer` resolves `room_id` from `RoomManager` on satellite registration; `AgentSatelliteUpdate.room` now carries the enum ID so the adapter can use it as a language-neutral ioBroker path segment (Refs #33)
* Changed: proto — `AgentDevice.room_names: map<string, string>` added (field 8); comments updated on `AgentSatelliteUpdate.room` and `AgentSatelliteControl.room` to clarify room_id semantics (Refs #33)

### Hannah Proxy
* Changed: proto updated — `AgentDevice.room_names` map added (field 8) (Refs #33)

### Telegram
* Changed: proto updated — `AgentDevice.room_names` map added (field 8) (Refs #33)

## 0.32.0
### Hannah Core
* Added: `RoomManager.resolve_satellite_name(device_id, serial)` — returns provisioned `display_name` from DB; looked up by serial if present, else by device_id (Refs #26)
* Added: `display_name` field (8) to `AgentSatelliteUpdate` — Core populates it from DB on every satellite registration event so the adapter can show a human-readable name in ioBroker (Refs #26)
* Added: `display_name` field (5) to `Satellite` message — returned by `GetSatellites` so the adapter has the correct name on initial connect without waiting for a re-registration event (Refs #26)
* Added: `resolve_satellite_name` callback parameter to `HannahServicer`; wired to `RoomManager.resolve_satellite_name` in `main.py` (Refs #26)
* Changed: `GetSatellites` now resolves `serial` and `display_name` per satellite from internal proxy state and DB (Refs #26)
* Added: `AgentSatelliteUpdate.display_name` (field 8) — human-readable satellite name from Core DB (Refs #26)
* Added: `Satellite.display_name` (field 5) — human-readable name included in `GetSatellites` response (Refs #26)
* Changed: `device_id` is now always derived from the eFuse MAC at boot (12-char lowercase hex) — replaces the previously NVS-configurable string; `serial` fields removed from proto, DB, and proxy (Refs #32)
* Changed: proto — removed `serial` from `Satellite` (field 4 reserved), `SatelliteRegistration` (field 4 reserved), `AgentSatelliteUpdate` (field 7 reserved) — field numbers reserved to prevent future accidental reuse (Refs #32)
* Changed: `room_manager.py` — removed `serial` column from `satellites` table; `pair_satellite` and `resolve_satellite_name` now operate on `device_id` only; removed `get_satellite_by_serial()` (Refs #32)
* Changed: `grpc_server.py` — `_proxy_satellites` keyed exclusively by `device_id`; removed dual-key serial/device_id lookup; `agent_satellite_update` no longer carries `serial` (Refs #32)

### Satellite Firmware
* Changed: status page (`/`) shows hardware serial (eFuse MAC) instead of configurable device-ID at "Gerät" row (Refs #26)
* Changed: settings page (`/settings`) no longer exposes "Geräte-ID" and "Raum" input fields — both are now managed by Hannah Core; NVS values remain intact and are still used for routing (Refs #26)
* Changed: `device_id` is now always the eFuse MAC (computed in `hannah_config_init`); `CONFIG_HANNAH_DEVICE_ID` Kconfig option removed; NVS key `device_id` no longer written or read (Refs #32)
* Changed: `send_register()` no longer sends a `"serial"` JSON field — `device` already carries the eFuse MAC (Refs #32)

### Hannah Proxy
* Changed: proto updated — `serial` removed from `SatelliteRegistration`; `NotifySatelliteRegistered` and satellite callbacks no longer carry or store serial (Refs #32)

## 0.31.1
### Hannah Core
* Fixed: `_migrate_db` in `room_manager.py` failed with `sqlite3.OperationalError: Cannot add a UNIQUE column` — SQLite does not support `ADD COLUMN … UNIQUE`; replaced with `ADD COLUMN serial TEXT` followed by `CREATE UNIQUE INDEX … WHERE serial IS NOT NULL` (Refs #26)

## 0.31.0
### Hannah Core
* Added: `satellites` table extended with `serial`, `seed`, `paired_at` columns; auto-migrates existing DBs (Refs #26)
* Added: `provision_satellite(seed, display_name, room_id)` — pre-registers a satellite before WebFlash (Refs #26)
* Added: `pair_satellite(device_id, serial, seed)` — links hardware serial to pre-provisioned seed entry on first connect (Refs #26)
* Added: `get_satellite_by_serial(serial)` — lookup by hardware serial (Refs #26)
* Added: `ProvisionSatellite` RPC + `ProvisionSatelliteRequest` message — adapter pre-provisions before flash (Refs #26)
* Added: `SatelliteRegistration.serial` (field 4) and `SatelliteRegistration.seed` (field 5) — sent by satellite on first connect (Refs #26)
* Added: `Satellite.serial` (field 4) — hardware serial in `GetSatellites` response (Refs #26)
* Changed: `NotifySatelliteRegistered` now returns `message="paired"` when seed pairing succeeds (Refs #26)
* Changed: `_proxy_satellites` keyed by serial for paired satellites; `device_id` stored in dict value for proxy routing (Refs #26)
* Changed: `stream_audio_to_proxy` resolves `proxy_device_id` from sat info — works with serial or device_id as `target` (Refs #26)
* Changed: `get_satellite_room_map()` returns both `device_id` and `serial` as keys so `_resolve_targets()` resolves rooms for paired satellites (Refs #26)
* Added: `AgentSatelliteUpdate.serial` (field 7) — hardware serial sent to adapter on registration; adapter uses as ioBroker object-ID (Refs #26)
* Added: `get_proxy_satellite_info(key)` helper on `HannahServicer` — resolves `(device_id, serial)` from a snapshot key (which may be serial or device_id) (Refs #26)
* Fixed: `_on_satellite_change` in `main.py` now resolves correct `device_id`/`serial` for paired satellites via `get_proxy_satellite_info()` instead of passing serial as device_id (Refs #26)

### Hannah Proxy
* Updated: `proto/hannah.proto` synced with Core — `ProvisionSatellite` RPC, `serial`/`seed` fields in `SatelliteRegistration` (Refs #26)
* Changed: `NotifySatelliteRegistered` now forwards `serial` and `seed` from the satellite register payload to Core; sends `{"type":"paired"}` to satellite if Core confirms pairing (Refs #26)
* Fixed: `SatelliteChangeCallback` signature in unit tests updated to match new `serial, seed` parameters (Refs #26)

### Satellite Firmware
* Added: hardware serial read from eFuse MAC (`esp_efuse_mac_get_default`) and sent in every Register message as `serial` field (Refs #26)
* Added: `seed` NVS key — one-time pairing token written during WebFlash; included in Register if present, cleared from NVS on `{"type":"paired"}` ACK from proxy (Refs #26)

## 0.30.0
### Hannah Core
* Added: `RoomManager` — SQLite persistence for rooms (synced from ioBroker), n:n room groups, and satellite-to-room assignment (`core/hannah/room_manager.py`) (Refs #25)
* Added: Web UI (`core/hannah/webui.py`) — Flask app for room/group/satellite management; starts as daemon thread on configurable port (default 8080); `flask>=3.0.0` added to `requirements.txt` (Refs #25)
* Added: `web_ui` and `room_manager` config sections in `config.example.yaml` (Refs #25)
* Added: `_resolve_targets` uses DB satellite room assignments (overrides self-reported room) and DB groups (fallback: `config.yaml groups:`); NLU room list updated with DB groups on device snapshot (Refs #25)

## 0.29.3
### AutoDeploy
* Added: optional `post_install` shell command in component config — executed after extraction, before state save and service restart; non-zero exit aborts the deployment

### VoiceID
* Added: `requirements.txt` with service dependencies (`torch`, `numpy`, `PyYAML`, `fastapi`, `uvicorn`, `speechbrain`)

## 0.29.2
### Satellite Firmware
* Added: BSEC2 3.3V config binary (`bme680_iaq_33v_3s_4d.bin`) embedded via `EMBED_FILES` and loaded with `bsec_set_configuration()` after `bsec_init()` to improve self-heating compensation for 3.3V supply; falls back to 1.8V defaults with a warning on version mismatch (Refs #17, Refs #24)
* Fixed: `work_buf[BSEC_MAX_WORKBUFFER_SIZE]` (4096 bytes) in `sensor_init()` declared `static` to prevent stack overflow that caused heap corruption and a boot loop

## 0.29.1
### Satellite Firmware
* Refactored: AudioLib integrated as an IDF component via EXTRA_COMPONENT_DIRS instead of a manual list of source files — future AudioLib updates will automatically include the source and header files (closes #23)
* Added: WebRTC VAD replaces RMS-based silence detection during streaming — `hannah_webrtc_vad_init/feed/free` (from AudioLib 0.2.0 / libfvad) distinguishes speech from music and background noise by spectral features instead of energy level; aggressiveness configurable via Kconfig (`HANNAH_VAD_WEBRTC_AGGRESSIVENESS`, default 2); `noise_ema` stays for the wakeword-onset guard (closes #20)

## 0.29.0
### Hannah Core
* Added: MQTT sensor handler forwards IAQ, IAQ accuracy, CO₂ equivalent and VOC equivalent from satellite MQTT payload through to gRPC `AgentSensorUpdate` (Refs #17)

### Proto
* Added: `AgentSensorUpdate` extended with fields `iaq` (float), `iaq_accuracy` (uint32), `co2_equiv` (float), `voc_equiv` (float) — fields 6–9; zero when BSEC2 not calibrated (Refs #17)

### Hannah Proxy
* Updated: `proto/hannah.proto` synced with Core — `AgentSensorUpdate` extended with BSEC2 fields `iaq`, `iaq_accuracy`, `co2_equiv`, `voc_equiv`; field 5 (`gas_resistance`) reserved (Refs #17)

### Telegram
* Updated: `proto/hannah.proto` synced with Core — `AgentSensorUpdate` extended with BSEC2 fields `iaq`, `iaq_accuracy`, `co2_equiv`, `voc_equiv`; field 5 (`gas_resistance`) reserved (Refs #17)

### Satellite Firmware
* Added: BSEC2 library integration for BME680 — replaces raw gas resistance (Ω) with meaningful IAQ (0–500), Static IAQ, CO₂ equivalent (ppm), and breath VOC equivalent (ppm); accuracy level (0–3) published alongside; BSEC2 calibration state persisted to NVS every 30 min and restored on boot to retain accuracy across reboots (Refs #17)
* Added: `bme68x` and `bsec2` as local IDF components (`components/bme68x/`, `components/bsec2/`) with precompiled `libalgobsec.a` for ESP32-S3 (Xtensa LX7); workaround for IDF 6.0 `component_requirements.py` Windows path bug via explicit `target_include_directories` / `target_link_libraries` in `hannah_sensors/CMakeLists.txt`

## 0.28.3
### Satellite Firmware
* Fixed: PDM clock inversion flag set to `true` (`clk_inv = true`) — SPH0641 with SEL=GND outputs data on the falling CLK edge; reading on the rising edge caused white noise instead of signal (Refs #5)
* Fixed: VAD `noise_ema` stuck at initial value 0.02 — `noise_ema` is now calibrated during the 5 s mic warmup (excluding TTS frames via `s_speaking_active` guard) so the correct floor is known before the first stream; idle tracking also gated on `!s_speaking_active` to prevent speaker bleed from contaminating the noise floor estimate (Refs #19)

## 0.28.2
### Hannah Core
* Fixed: `_ask_fn` routes `start_listening` via MQTT instead of UDP — UDP-based send silently failed for proxy-connected satellites (closes #18)

### Satellite Firmware
* Fixed: `hannah_net` subscribes to `hannah/satellite/{device}/listen` MQTT topic and calls `start_listening` callback on receipt — proxy satellites now receive the command
* Fixed: `hannah_audio_start_listen_after_tts` activates virtual PTT immediately if TTS has already ended, avoiding a missed trigger when the MQTT message arrives after the sentinel

## 0.28.1
### Hannah Core
* Fixed: `_ask_fn` now sends `start_listening` UDP command to all satellites in the room after TTS — satellites were not entering listening mode after the question was played, so no answer ever arrived at Hannah

### Satellite Firmware
* Fixed: added `start_listening` UDP command handler in `hannah_net` — triggers `hannah_audio_start_listen_after_tts()` callback
* Fixed: `hannah_audio`: after TTS playback drains (end-sentinel), if `start_listening` was received, sets virtual PTT active with 8s auto-timeout; PTT-mode mic task decrements counter and clears PTT on timeout; wakeword-mode cleans up virtual listen state on stream end

### Scripts
* Fixed: `release.js` now removes the `## **WORK IN PROGRESS**` line when promoting WIP entries to a version — the HTML comment above it is preserved

## 0.28.0
### Hannah Core
* Added: `AgentAskResident` 

### Proto
* Added: `correlation_id` field to `AgentAskResident` — identifies a pending question across the round-trip; `AgentResidentAnswered` message carries the resident's spoken answer back to the adapter; `resident_answered` variant added to `AgentCommand` oneof so Hannah can push the answer over the existing adapter stream

## 0.27.0
### Hannah Core
* Added: `for:` delay in triggers — state-trigger can specify `for: "5h"` (or `"30m"`, `"90s"`) to defer execution until the duration elapses; the Timer Service registers a SQLite-persistent timer so delays survive Hannah restarts; `cancel_when:` cancels the pending timer if a counter-condition is met before the delay fires; on reconnect, `TimerListRequest` reconciles active trigger timers against current state (stale timers cancelled, active ones restored into RAM); `cancel_when` state IDs included in `WatchMore` so the adapter watches them

## 0.26.0
### Hannah Core
* Added: Trigger-Engine supports active questioning — triggers can use `ask` instead of `say` to pose a question via TTS and route the next utterance from that room as the answer; `on_response` rules match the free-form answer via `llm_match("category")` (LLM classification prompt) and execute `say` actions accordingly; unanswered questions time out after 60s; answered utterances bypass NLU routing (`AnswerPending` intent)
* Added: `LLMClient.match(text, category)` — classifies whether a free-form answer belongs to a semantic category using a yes/no LLM prompt; `DummyLLM` always returns `False`
* Added: `set_state` action in `on_response` rules — sets an ioBroker state directly when a response condition matches (`set_state: {id: "...", value: ...}`); can be combined with `say` in the same rule

### Hannah Proxy
* Changed: replaced `gopkg.in/yaml.v3` with `sigs.k8s.io/yaml` for config parsing — struct tags switched from `yaml:"..."` to `json:"..."` accordingly (config.yaml format unchanged)

## 0.25.2
### Hannah Proxy
* Fixed: `SendTTSChunk()` now throttles UDP packet sending to playback rate — each 1400-byte packet is followed by a sleep proportional to its audio duration (`chunk_bytes / (sample_rate × 2)`); without this, the proxy sent all packets in a burst that overflowed the satellite's lwIP socket buffer, dropping most audio and causing garbled/truncated TTS on long responses

## 0.25.1
### Satellite Firmware
* Changed: Speaker audio buffering replaced per-chunk `malloc`/`free` with a FreeRTOS `RINGBUF_TYPE_NOSPLIT` ring buffer (32 KB internal DRAM, ~640ms buffer at 24kHz) — `hannah_audio_play()` uses `xRingbufferSendAcquire`/`xRingbufferSendComplete` to write directly into the ring buffer without heap allocation; `speaker_task` uses `xRingbufferReceive`/`vRingbufferReturnItem`; end-of-stream signalled by a sentinel item with `len=0`; internal DRAM required (PSRAM not suitable for I2S-DMA source)

## 0.25.0
### Hannah Core
* Added: `stream_audio_to_proxy()` — slices full TTS PCM into ~100ms chunks (4800 bytes @ 24kHz) and sends each as a separate `PlayAudioCommand` with `is_last=true` on the final chunk; reduces satellite startup latency from full Azure response time to first chunk arrival

### Hannah Proxy
* Added: `SendTTSChunk()` / `SendTTSEnd()` on the UDP server — proxy forwards each `PlayAudioCommand` chunk immediately without buffering; `tts_end` is sent only when `is_last=true`; removed 300ms sleep before `tts_end`
* Changed: `PlayAudioFunc` callback is now synchronous (no goroutine) to preserve chunk order within the gRPC stream

### Proto
* Changed: `PlayAudioCommand` — added `bool is_last = 4`; signals the proxy to send `tts_end` after the final chunk

## 0.24.13
### Satellite Firmware
* Added: Asset Server URL and Token fields to the satellite settings web interface (`/settings`) — token inputs are write-only (password type); submitting an empty token field leaves the stored value unchanged
* Added: Update Server Token field to the satellite settings web interface — same write-only behaviour
* Added: "Disable TLS certificate validation" checkbox in settings web interface — stored in NVS (`tls_skip`), default off; when enabled, `crt_bundle_attach` is omitted so ESP-IDF skips chain verification (useful for self-signed certificates)

## 0.24.12
### Satellite Firmware
* Fixed: `hannah_asset` now verifies the SHA256 of a downloaded asset against the manifest before caching it — previously an aborted partial download (e.g. 512 bytes from a dropped TLS connection) was accepted as valid (`total > 0`), its manifest hash stored in NVS, and the corrupt file served forever; mismatching files are now discarded and re-fetched on the next cycle (SHA256 via PSA Crypto API, mbedTLS 4.x compatible)
* Changed: BLE (NimBLE) memory footprint reduced — host heap moved to PSRAM (`BT_NIMBLE_MEM_ALLOC_MODE_EXTERNAL`) and roles restricted to observer-only (central/peripheral/broadcaster/SMP disabled), since `hannah_ble` is a pure passive scanner; frees scarce internal RAM that AES/I2S DMA and WiFi mgmt-frames compete for (TLS asset download failed with `esp-aes: Failed to allocate memory` while BLE was active)

## 0.24.11
### Satellite Firmware
* Fixed: `asset_upd` task stack increased from 8 KB to 16 KB — with mbedTLS now able to complete the TLS handshake (v0.24.10), the ECDHE MPI hardware-acceleration operations (`mpi_ll_read_from_mem_block`) ran out of stack during the asset download, causing a stack overflow and reboot

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

### Hannah Proxy
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

### Hannah Proxy
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
