---
name: run
description: Verify Hannah changes locally via each component's own test suite. Hannah Core cannot be launched interactively from a dev machine — it depends on live infrastructure (ioBroker REST API, MQTT broker, Ollama, physical satellite hardware/audio) that only exists on the home network / Raspberry Pi. Use when asked to run, start, test, or verify a change anywhere in this mono-repo.
---

# Running / verifying Hannah

Hannah is not a locally-launchable app in the usual sense. `core/` is a Python
service meant to run on a Raspberry Pi against real infrastructure: ioBroker's
REST API (`192.168.8.1:8093`), a real MQTT broker, Ollama on `psrvai01`, and
physical ESP32-S3 satellites with real microphones/speakers. There is no
"start it and try the feature in a browser" step here — don't attempt to spin
up `core/main.py` directly as a way to "see it work."

**The real local verification loop is each component's own test suite** —
exactly what CI runs (`.gitlab-ci.yml` is the source of truth if these drift):

| Component | Command |
|---|---|
| Hannah Core (`core/`) | `cd core && python -m pytest tests/ -v` |
| Telegram microservice (`telegram/`) | `PYTHONPATH=telegram pytest telegram/tests/ -v` (run from repo root) |
| VoiceID (`voiceid/`) | `PYTHONPATH=voiceid pytest voiceid/tests/ -v` (run from repo root) |
| Go proxy (`proxy/`) | `cd proxy && go test ./... -v` |
| satellite-pi (legacy) | `cd satellite-pi && python -m pytest tests/ -v` (check `requirements-test.txt` first) |
| satellite-esp firmware | Build-only, no unit tests: activate ESP-IDF (`C:\esp\v6.0.1\esp-idf\export.ps1`), then `cd satellite-esp && idf.py build` |
| ioBroker adapter (`iobroker.hannah/`, submodule) | `cd iobroker.hannah && npm test` |

Run the test suite for whatever component you touched before claiming a fix
works. If a change spans components (e.g. a proto change), run tests for
every consumer you touched.

## What this does NOT cover

Real end-to-end behavior — an actual voice command through a satellite, a
real ioBroker state round-trip, live MQTT wiring — can only be verified on
the real Raspberry Pi. That requires SSH access, restarting the systemd
service, and tailing logs, all on hardware this dev machine cannot reach.

**Never attempt or assume this autonomously.** If a task genuinely needs
end-to-end confirmation, say so explicitly and ask the user to run the
verification step on the Pi themselves — per her standing instruction that
remote-host actions must be called out plainly, not just shown as a code
block for her to notice and run herself.
