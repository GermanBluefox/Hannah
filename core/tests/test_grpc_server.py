from unittest.mock import MagicMock

from hannah.grpc_server import HannahServicer
from hannah.user_registry import UserRegistry
from hannah.iobroker import IoBrokerClient
from hannah.proto.hannah_pb2 import AgentDevice, AgentStateValue, AgentResident

def _make_server(registry=None,handle_text=None,handle_voice=None,get_satellites=None,get_car_state=None,announce=None,notificate=None,on_agent_device_snapshot=None,on_agent_send_residents=None):
    return HannahServicer(
        registry=registry or MagicMock(),
        handle_text=handle_text or MagicMock(),
        handle_voice=handle_voice or MagicMock(),
        announce=announce or MagicMock(),
        notificate=notificate or MagicMock(),
        get_satellites=get_satellites or MagicMock(),
        get_car_state=get_car_state or MagicMock(),
        on_agent_device_snapshot=on_agent_device_snapshot,
        on_agent_send_residents = on_agent_send_residents
    )

def test_device_snapshot_dispatched():
    client = IoBrokerClient({"host": "localhost", "port": 8093})
    servicer = _make_server(on_agent_device_snapshot=client.handle_device_snapshot)

    devices = [
        AgentDevice(
            state_id="javascript.0.virtualDevice.Licht.EG.Wohnzimmer.Decke.on",
            room="Wohnzimmer",
            device="Decke",
            functions=["Licht"],
            value=AgentStateValue(value="true", ack=True),
        )
    ]
    servicer._on_agent_device_snapshot(devices)
    assert "wohnzimmer" in client.rooms

def test_resident_snapshot_dispatched():
    registry = MagicMock(spec=UserRegistry)
    servicer = _make_server(on_agent_send_residents=registry.sync)
    residents = [
        AgentResident(
            roomie_id="test1",
            name="Test 1",
            is_guest = False
        ),
        AgentResident(
            roomie_id="test2",
            name="Test 2",
            is_guest = True
        )
    ]
    servicer._on_agent_send_residents(residents)
    registry.sync.assert_called_once_with(residents)