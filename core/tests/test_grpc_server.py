from unittest.mock import MagicMock

from hannah.grpc_server import HannahServicer
from hannah.user_manager import UserManager
from hannah.iobroker import IoBrokerClient
from hannah.proto.hannah_pb2 import AgentDevice, AgentStateValue, AgentResident, AgentRoom, SatelliteRegistration, ResidentType

def _make_server(user_manager=None,handle_text=None,handle_voice=None,get_satellites=None,get_car_state=None,announce=None,notificate=None,on_agent_device_snapshot=None,on_agent_send_residents=None,on_agent_room_snapshot=None,on_satellite_change=None,resolve_satellite_room=None):
    return HannahServicer(
        user_manager=user_manager or MagicMock(),
        handle_text=handle_text or MagicMock(),
        handle_voice=handle_voice or MagicMock(),
        announce=announce or MagicMock(),
        notificate=notificate or MagicMock(),
        get_satellites=get_satellites or MagicMock(),
        get_car_state=get_car_state or MagicMock(),
        on_agent_device_snapshot=on_agent_device_snapshot,
        on_agent_send_residents = on_agent_send_residents,
        on_agent_room_snapshot=on_agent_room_snapshot,
        on_satellite_change=on_satellite_change,
        resolve_satellite_room=resolve_satellite_room,
    )

def test_device_snapshot_dispatched():
    client = IoBrokerClient({"host": "localhost", "port": 8093})
    servicer = _make_server(on_agent_device_snapshot=client.handle_device_snapshot)

    devices = [
        AgentDevice(
            state_id="javascript.0.virtualDevice.Licht.EG.Wohnzimmer.Decke.on",
            room="wohnzimmer",
            device="Decke",
            functions=["Licht"],
            value=AgentStateValue(value="true", ack=True),
            room_names={"de": "Wohnzimmer", "en": "Living Room"},
        )
    ]
    servicer._on_agent_device_snapshot(devices)
    assert "wohnzimmer" in client.rooms

def test_room_snapshot_dispatched():
    sync_rooms = MagicMock()
    servicer = _make_server(on_agent_room_snapshot=sync_rooms)
    rooms = [
        AgentRoom(room_id="wohnzimmer", display_names={"de": "Wohnzimmer", "en": "Living Room"}),
    ]
    servicer._on_agent_room_snapshot(rooms)
    sync_rooms.assert_called_once_with(rooms)

def test_notify_satellite_registered_does_not_double_send():
    on_satellite_change = MagicMock()
    servicer = _make_server(on_satellite_change=on_satellite_change, resolve_satellite_room=lambda _d: "wohnzimmer")
    servicer.agent_satellite_update = MagicMock()

    request = SatelliteRegistration(device_id="wz-sat", address="192.168.1.50")
    response = servicer.NotifySatelliteRegistered(request, None)

    assert response.ok
    servicer.agent_satellite_update.assert_not_called()
    on_satellite_change.assert_called_once_with({"wz-sat": "wohnzimmer"})

def test_notify_satellite_gone_does_not_double_send():
    on_satellite_change = MagicMock()
    servicer = _make_server(on_satellite_change=on_satellite_change, resolve_satellite_room=lambda _d: "wohnzimmer")
    servicer.agent_satellite_update = MagicMock()
    servicer.NotifySatelliteRegistered(SatelliteRegistration(device_id="wz-sat", address="192.168.1.50"), None)
    on_satellite_change.reset_mock()

    request = SatelliteRegistration(device_id="wz-sat")
    response = servicer.NotifySatelliteGone(request, None)

    assert response.ok
    servicer.agent_satellite_update.assert_not_called()
    on_satellite_change.assert_called_once_with({})