#!/usr/bin/env bash
# Generiert Python-Stubs aus hannah.proto und patcht den relativen Import
# (grpc_tools generiert absoluten Import, der im Package nicht funktioniert).
#
# Achtung: grpc_tools.protoc schreibt die lokal installierte grpcio-tools-Version
# als Mindest-grpcio-Laufzeitanforderung in den generierten _grpc.py-Code. Ist die
# lokale grpcio-tools-Version neuer als das in requirements.txt gepinnte grpcio,
# startet der Service beim Deploy nicht mehr ("RuntimeError: ... depends on
# grpcio>=X"), weil pip ein bereits installiertes, älteres grpcio nicht automatisch
# hochzieht. Vor dem Ausführen prüfen: lokale grpcio-tools-Version <= requirements.txt's
# grpcio-Pin, sonst dort zuerst hochziehen (core/ UND telegram/, beide nutzen denselben
# generierten Code).
set -e
cd "$(dirname "$0")/.."

python -m grpc_tools.protoc \
  -I proto \
  --python_out=hannah/proto \
  --grpc_python_out=hannah/proto \
  proto/hannah.proto

# grpc_tools-Bug: "import hannah_pb2" → "from . import hannah_pb2"
sed -i 's/^import hannah_pb2/from . import hannah_pb2/' hannah/proto/hannah_pb2_grpc.py

echo "✓ Python proto stubs generated in hannah/proto/"
