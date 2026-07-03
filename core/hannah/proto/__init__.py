# Generated gRPC stubs — do not edit the *_pb2*.py files manually.
# Re-generate with:
#   bash scripts/gen_proto.sh   (from repo root)
#
# #44: hannah.proto was split by scope into multiple .proto files. protoc's Python
# codegen keeps each file's messages/enums in that file's own generated module
# (agent_pb2, car_state_pb2, ...) rather than re-exporting them into hannah_pb2 —
# but existing code across the repo does `from hannah.proto import hannah_pb2 as pb`
# and expects every message (pb.AgentDevice, pb.CarStateProto, pb.ResidentType, ...)
# to be reachable there, same as before the split (Go/TS aren't affected: Go keeps
# one flat package namespace across files, and @grpc/proto-loader builds its
# namespace from the proto `package`, not the source file). Patch every scope
# module's public names onto hannah_pb2 here so that keeps working without
# touching dozens of call sites in grpc_server.py/iobroker.py/residents_manager.py.
from . import (
    agent_pb2,
    car_state_pb2,
    control_pb2,
    device_control_menu_pb2,
    event_stream_pb2,
    hannah_pb2,
    satellite_provisioning_pb2,
    satellite_proxy_pb2,
    shared_pb2,
    speaker_enrollment_pb2,
    timer_service_pb2,
    user_registry_pb2,
    wakeword_capture_pb2,
)

for _module in (
    shared_pb2,
    user_registry_pb2,
    control_pb2,
    car_state_pb2,
    event_stream_pb2,
    satellite_proxy_pb2,
    device_control_menu_pb2,
    satellite_provisioning_pb2,
    speaker_enrollment_pb2,
    agent_pb2,
    wakeword_capture_pb2,
    timer_service_pb2,
):
    for _name in dir(_module):
        if not _name.startswith("_") and not hasattr(hannah_pb2, _name):
            setattr(hannah_pb2, _name, getattr(_module, _name))
del _module, _name
