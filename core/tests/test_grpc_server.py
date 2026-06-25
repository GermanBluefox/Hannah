import os
from unittest.mock import MagicMock

from werkzeug.security import generate_password_hash

from hannah.grpc_server import HannahServicer, _user_to_pb
from hannah.user_manager import UserManager
from hannah.models.user import User
from hannah.iobroker import IoBrokerClient
from hannah.proto.hannah_pb2 import AgentDevice, AgentStateValue, AgentResident, AgentRoom, SatelliteRegistration, ResidentType, LinkAccountRequest, ProxyHeartbeat

def _make_server(user_manager=None,handle_text=None,handle_voice=None,get_satellites=None,get_car_state=None,announce=None,notificate=None,on_agent_device_snapshot=None,on_agent_send_residents=None,on_agent_room_snapshot=None,on_satellite_change=None,resolve_satellite_room=None,upsert_satellite=None):
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
        upsert_satellite=upsert_satellite,
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

def test_notify_satellite_registered_upserts_last_seen():
    """Regression: NotifySatelliteRegistered never refreshed RoomManager's last_seen,
    unlike the UDP "register" path — satellites connected via the proxy showed a
    last_seen frozen at whatever it last was before they switched to proxy routing."""
    upsert = MagicMock()
    servicer = _make_server(resolve_satellite_room=lambda _d: "wohnzimmer", upsert_satellite=upsert)

    servicer.NotifySatelliteRegistered(SatelliteRegistration(device_id="wz-sat", address="192.168.1.50"), None)

    upsert.assert_called_once_with("wz-sat")

def test_register_proxy_heartbeat_upserts_known_satellites():
    """Regression: the proxy never forwards individual satellite heartbeats, only one
    heartbeat per proxy connection — without touching last_seen here too, it would
    freeze again right after the registration-time upsert for the whole proxy session."""
    upsert = MagicMock()
    servicer = _make_server(resolve_satellite_room=lambda _d: "wohnzimmer", upsert_satellite=upsert)
    servicer.NotifySatelliteRegistered(SatelliteRegistration(device_id="wz-sat", address="192.168.1.50"), None)
    upsert.reset_mock()

    class _FakeContext:
        def __init__(self):
            self._active = True
        def is_active(self):
            active = self._active
            self._active = False
            return active

    list(servicer.RegisterProxy(iter([ProxyHeartbeat(proxy_id="proxy-1")]), _FakeContext()))

    upsert.assert_called_once_with("wz-sat")

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

def _make_user_manager_with_leonie(tmp_path):
    """Real (non-mocked) UserManager against a throwaway SQLite DB. User/LinkedAccount
    bugs only show up against the real model layer — a MagicMock hides them.

    hannah.utils.db.DB_PATH is read once at import time, so the env var alone
    only takes effect on the very first import in this test session — patch
    the module attribute directly to get a fresh DB per test.
    """
    import hannah.utils.db as db_module
    db_module.DB_PATH = os.path.join(str(tmp_path), "h.db")
    db_module.init_db()
    User.create(
        db_module.get_db(), username="leonie", display_name="Leonie", email="leonie@example.com",
        password_hash=generate_password_hash("x"), trust_level=10, mood_level=5,
        system_messages=0, type="roomie", is_active=1,
    )
    get_db = db_module.get_db
    return UserManager(get_db), get_db

def test_link_account_accepts_int32_user_id(tmp_path):
    """Regression: get_user_by_id() must accept the int32 proto user_id and find the
    just-cached user — used to KeyError because the cache is int-keyed but a
    digit-string slipped through before user_id became int32 on the wire."""
    user_manager, _get_db = _make_user_manager_with_leonie(tmp_path)
    user = user_manager.get_user_by_username("leonie")
    servicer = _make_server(user_manager=user_manager)

    request = LinkAccountRequest(user_id=user.id, service="telegram", account_id="99999")
    response = servicer.LinkAccount(request, MagicMock())

    assert response.ok is True

def test_user_to_pb_with_linked_account(tmp_path):
    """Regression: _user_to_pb crashed with AttributeError on acc.service (the model
    attribute is .provider) for any user with a linked account; also covers
    provider_payload="" round-tripping without a JSONDecodeError."""
    user_manager, get_db = _make_user_manager_with_leonie(tmp_path)
    user = user_manager.get_user_by_username("leonie")
    user.link_account("telegram", "99999")

    fresh = User.get(get_db(), id=user.id)
    pb_user = _user_to_pb(fresh)

    assert pb_user.linked_accounts["telegram"] == "99999"