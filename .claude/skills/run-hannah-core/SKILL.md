---
name: run-hannah-core
description: Build, test, and drive Hannah Core's web UI (rooms/groups/satellites/users CRUD) standalone, without the full audio/MQTT/ioBroker/gRPC daemon. Use when asked to start Hannah Core, run its tests, take a screenshot of its web UI, or exercise the rooms/groups/satellites/users routes.
---

Hannah Core (`main.py`) is a Raspberry-Pi voice-assistant daemon (audio,
MQTT, gRPC, STT/TTS, ioBroker) that can't run headless without real
hardware/services. Its `hannah.webui` Flask app, however, only depends on
`RoomManager` + `UserManager` (both plain SQLite) — `.claude/skills/run-hannah-core/driver.py`
builds that app standalone with a seeded fixture DB and serves it on
`127.0.0.1`. Drive it with `curl` (server-rendered HTML forms, no client JS
of note) and `.claude/skills/run-hannah-core/screenshot.py` (Playwright) for
a visual check.

This skill's own files live at `.claude/skills/run-hannah-core/` (repo
root), but the venv/tests/fixtures it drives live in `core/`. All commands
below assume `cd core/` first; the two skill scripts are then reached via
`../.claude/skills/run-hannah-core/...`. Shown as plain POSIX-style shell
(run via Git Bash on this machine); adjust slashes/`.exe` suffixes for
PowerShell or another OS.

## Prerequisites

The webui only needs Flask (Werkzeug comes with it) — **not** the rest of
`requirements.txt` (faster-whisper, piper-tts, grpcio, ... are for the full
daemon and untouched by this surface):

```bash
python -m venv venv
venv/Scripts/python -m pip install flask   # venv/bin/python on Linux/Mac
```

For the test suite (matches `.gitlab-ci.yml`'s `test:core` job):

```bash
python -m venv .venv-test
.venv-test/Scripts/python -m pip install -r tests/requirements-test.txt
```

For screenshots (Playwright + Chromium; no extra system packages needed —
verified headless launch with just `--no-sandbox`, on both Windows and a
plain WSL Ubuntu with nothing preinstalled):

```bash
python -m venv /tmp/hannah-pw-venv
/tmp/hannah-pw-venv/Scripts/python -m pip install playwright
/tmp/hannah-pw-venv/Scripts/python -m playwright install chromium
```

## Test

```bash
PYTHONPATH=. .venv-test/Scripts/python -m pytest tests/ -v
```

72 passed (no webui/user_manager tests exist yet — this only covers
room_manager/iobroker/tool_agent/udp_server/grpc_server).

## Run (agent path)

Launch the seeded webui in the background (use the harness's own
background-task support — a plain trailing `&` inside a one-off shell
invocation dies the moment that invocation returns, see Gotchas):

```bash
venv/Scripts/python ../.claude/skills/run-hannah-core/driver.py --port 5151 --data-dir /tmp/hannah-webui-fixture
```

Seeds: rooms Küche/Wohnzimmer/Bad, group "Erdgeschoss" (Küche+Wohnzimmer),
one satellite `kueche-esp` (in Küche, reported "connected"), 4 users
(`hannah`/`admin` from first-run, plus `leonie` — pre-linked to resident
`leonie_roomie` — and `rene`, unlinked), and 3 fake residents (`Roomie`
objects, bypassing the real ioBroker-backed `residents_manager`) for the
`/users` link form.

Drive it with `curl` — every route is a normal HTML GET or a form POST that
302-redirects back to the list page:

```bash
curl -s http://127.0.0.1:5151/rooms | grep -oE 'Küche|Wohnzimmer|Bad'
curl -s -o /dev/null -w '%{http_code}\n' -X POST -d 'resident_id=rene_roomie' \
  http://127.0.0.1:5151/users/4/link-resident      # → 302, redirects to /users
curl -s http://127.0.0.1:5151/users | grep -A1 badge-room   # → "rene (roomie)" badge now shown
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:5151/users/4/unlink-resident
```

(User IDs: 1=hannah, 2=admin, 3=leonie, 4=rene, assigned in fixture-creation order.)

Screenshot a page:

```bash
/tmp/hannah-pw-venv/Scripts/python ../.claude/skills/run-hannah-core/screenshot.py \
  http://127.0.0.1:5151/users /tmp/hannah-shots/users.png
```

Prints any browser console errors first (check these — see Gotchas) then
`saved <path>`.

## Run (human path)

In production, `main.py` wires the same `create_app()` factory to the real
`RoomManager`/`UserManager`/`residents_manager` and serves it on
`config.yaml`'s `web_ui.host:port` (default `0.0.0.0:8080`) as a daemon
thread — but that needs MQTT, ioBroker, and the rest of the stack running.
Out of scope here; use `driver.py` instead.

## Gotchas

- **A plain `cmd &` inside one one-off shell invocation does not survive
  past that call** — the background process dies when the wrapper command
  exits, even with `nohup`/`disown`. Use the agent harness's own
  background-task mechanism (or run the whole interaction — launch, curl,
  shutdown — inside a single shell invocation).
- **`playwright install chromium` needs no extra system packages/sudo here**
  — verified `chromium.launch(args=['--no-sandbox'])` works both natively on
  Windows and against a bare WSL Ubuntu with nothing preinstalled.
- **Bootstrap JS never loads in a real browser.** `webui_templates/base.html`'s
  `<script>` tag for `bootstrap.bundle.min.js` has a stale/wrong SRI
  `integrity` hash — Chrome's subresource-integrity check blocks the
  download (visible via `screenshot.py`'s console-error report). Pages still
  render fine since everything is server-rendered HTML/CSS; only
  Bootstrap's JS-driven bits (mobile navbar collapse, JS-based dropdowns)
  are silently dead. Not fixed here — flagged, not in scope for this skill.
- **`get_residents` is normally backed by ioBroker presence updates** — the
  real `/users` "Resident wählen" dropdown is empty until ioBroker has sent
  at least one presence update per resident. `driver.py` sidesteps this by
  injecting fake `Roomie` objects directly.
