#!/usr/bin/env bash
# Regeneriert die Python-gRPC-Stubs aus den .proto-Quelldateien.
#
# Voraussetzung: grpcio-tools ist installiert (in telegram/venv oder system-weit).
#   pip install grpcio-tools
#
# Aufruf (aus dem Repo-Root):
#   bash scripts/gen_proto.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_CORE="$REPO_ROOT/core/proto"      # kanonische Quelle für Core + Adapter
PROTO_TELEGRAM="$REPO_ROOT/telegram/proto"  # Telegram-Subset
PROTO_WEBUI="$REPO_ROOT/webui/proto"        # WebUI-Subset

# Python mit grpcio-tools finden
PYTHON=""
for candidate in \
    "$REPO_ROOT/telegram/venv/bin/python" \
    "$REPO_ROOT/core/venv/bin/python" \
    "python3" \
    "python"
do
    if command -v "$candidate" &>/dev/null 2>&1 || [ -x "$candidate" ]; then
        if "$candidate" -c "import grpc_tools" &>/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: grpcio-tools nicht gefunden. Bitte installieren:"
    echo "  pip install grpcio-tools"
    exit 1
fi

echo "Nutze Python: $PYTHON"

# Core-Stubs generieren (vollständige Proto — enthält alle Agent-Messages)
echo "→ core/hannah/proto/"
"$PYTHON" -m grpc_tools.protoc \
    -I "$PROTO_CORE" \
    --python_out="$REPO_ROOT/core/hannah/proto" \
    --grpc_python_out="$REPO_ROOT/core/hannah/proto" \
    "$PROTO_CORE/hannah.proto"

# Telegram-Stubs generieren (Telegram-Subset)
echo "→ telegram/hannah_telegram/proto/"
"$PYTHON" -m grpc_tools.protoc \
    -I "$PROTO_TELEGRAM" \
    --python_out="$REPO_ROOT/telegram/hannah_telegram/proto" \
    --grpc_python_out="$REPO_ROOT/telegram/hannah_telegram/proto" \
    "$PROTO_TELEGRAM/hannah.proto"

# WebUI-Stubs generieren (WebUI-Subset)
echo "→ webui/hannah_webui/proto/"
"$PYTHON" -m grpc_tools.protoc \
    -I "$PROTO_WEBUI" \
    --python_out="$REPO_ROOT/webui/hannah_webui/proto" \
    --grpc_python_out="$REPO_ROOT/webui/hannah_webui/proto" \
    "$PROTO_WEBUI/hannah.proto"

# protoc erzeugt absolute Imports in *_grpc.py — innerhalb eines Python-Packages
# müssen diese relativ sein, sonst gibt es ModuleNotFoundError beim Import.
echo "→ Absolute Imports in *_grpc.py auf relativ patchen"
sed -i 's/^import hannah_pb2 as hannah__pb2$/from . import hannah_pb2 as hannah__pb2/' \
    "$REPO_ROOT/core/hannah/proto/hannah_pb2_grpc.py" \
    "$REPO_ROOT/telegram/hannah_telegram/proto/hannah_pb2_grpc.py" \
    "$REPO_ROOT/webui/hannah_webui/proto/hannah_pb2_grpc.py"

echo "Fertig."
