---
name: update-server
description: Query the Hannah OTA/release server (separate repo hannah-satellite-update-server, project 326) for firmware/binary release info — which versions are live per channel, latest version, release notes. Use when asked about deployed/released versions on the update server, not GitLab releases (that's a different system, see CHANGELOG.md / GitLab releases for those).
---

# Hannah Update Server — querying releases

Separate Go service (`gessinger/voice/hannah-satellite-update-server`, project 326)
that serves OTA firmware/binaries to ESP32 satellites and other components. Not
the same thing as a GitLab Release — this is Hannah's own channel-based release
store (used for firmware rollout, staged stable/dev channels, retention, etc).

## Credentials

Base URL + Bearer token live in `.claude/.hannah-update-server.env` (repo-root,
gitignored — never commit it). Load with:

```bash
set -a; source .claude/.hannah-update-server.env; set +a
```

Gives you `$HANNAH_UPDATE_BASE_URL` and `$HANNAH_UPDATE_TOKEN`.

If the file doesn't exist yet or the token stops working, ask the user — don't
try to provision a new service account yourself.

## Known channels

There is no working "list all channels" call for this account (see bug below).
The channels that actually exist, one pair of dev/stable (or per-arch variant)
per component — cross-check against `.gitlab-ci.yml`'s `upload_notes` calls if
this list ever looks stale:

```
autodeploy-dev            autodeploy-stable
core-dev                  core-stable
proxy-dev-amd64           proxy-stable-amd64
proxy-dev-arm64           proxy-stable-arm64
satellite-esp-dev         satellite-esp-stable
satellite-esp-rev2        satellite-esp-stable-init
telegram-dev              telegram-stable
timer-stable-amd64        timer-stable-arm64
voiceid-dev                voiceid-stable
webui-stable
```

## Querying

Per-channel endpoints work fine (`list`+`download` permissions are granted per
real channel name). Loop over the table above for an overview:

```bash
curl -s -H "Authorization: Bearer $HANNAH_UPDATE_TOKEN" \
  "$HANNAH_UPDATE_BASE_URL/releases?channel=core-stable"
# → [{"version":"v0.51.3","revision":1,"filename":"v0.51.3.bin","sha256":"...","size":139911,"has_notes":true}, ...]

curl -s -H "Authorization: Bearer $HANNAH_UPDATE_TOKEN" \
  "$HANNAH_UPDATE_BASE_URL/latest?channel=core-stable"
# → {"version":"v0.51.3","revision":1,"url":"...","sha256":"...","size":139911}

curl -s -H "Authorization: Bearer $HANNAH_UPDATE_TOKEN" \
  "$HANNAH_UPDATE_BASE_URL/releases/v0.51.3/notes?channel=core-stable"
# → {"content":"..."}
```

**Do NOT use `GET /channels`** (no `?channel=` param) — it always 403s for this
service account regardless of granted permissions. Root cause: it gates on the
literal channel name `"stable"` as a fixed default, which doesn't exist here
(all real channels are component-prefixed). Filed as
`hannah-satellite-update-server#2`. Use the per-channel loop above instead.

## Environment note

`curl` fails with "Permission denied" in this sandboxed Bash tool on Windows
(binary execution blocked, not a network/auth issue). Fall back to PowerShell's
`Invoke-RestMethod`/`Invoke-WebRequest`, or run curl from WSL if the user has a
shell open there — both work fine.
