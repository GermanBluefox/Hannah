#!/usr/bin/env bash
# auto-deploy.sh — Prüft ob neue Commits vorliegen und deployed bei Änderung.
# Wird von hannah-auto-deploy.timer alle 5 Minuten aufgerufen.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/hannah-core}"
LOG_TAG="hannah-auto-deploy"

log() { logger -t "$LOG_TAG" "$*"; }

cd "$REPO_DIR"

# Tags und Commits holen
git fetch origin --tags --force --quiet

LOCAL_TAG=$(git describe --tags --abbrev=0 HEAD 2>/dev/null || echo "")
REMOTE_TAG=$(git describe --tags --abbrev=0 origin/master 2>/dev/null || echo "")

if [ "$LOCAL_TAG" = "$REMOTE_TAG" ]; then
    exit 0
fi

log "Neues Release gefunden ($LOCAL_TAG → $REMOTE_TAG), starte Update..."

# Welche Dateien haben sich geändert?
CHANGED=$(git diff --name-only HEAD origin/master)

git restore .
git pull --ff-only --quiet
log "git pull abgeschlossen."

# Version in __version__.py schreiben (git describe → "v0.1.0" oder "v0.1.0-3-gabcdef")
VERSION=$(git describe --tags --always 2>/dev/null || echo "dev")
echo "VERSION = '${VERSION}'" > "$REPO_DIR/core/hannah/__version__.py"
log "Version: ${VERSION}"

# Nur betroffene Services neu starten
if echo "$CHANGED" | grep -q "^core/"; then
    log "Core-Dateien geändert → hannah.service neu starten"
    systemctl restart hannah
    log "hannah.service neu gestartet."
fi

if echo "$CHANGED" | grep -q "^telegram/"; then
    log "Telegram-Dateien geändert → hannah-telegram neu starten"
    systemctl restart hannah-telegram
    log "hannah-telegram neu gestartet."
fi

log "Update abgeschlossen ($REMOTE_TAG)."
