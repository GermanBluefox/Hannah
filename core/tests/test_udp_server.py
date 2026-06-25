import json
import time
from unittest.mock import MagicMock

from hannah.udp_server import UDPServer


def _make_server(callback=None, resolve_satellite_room=None, upsert_satellite=None):
    return UDPServer(
        cfg={"host": "127.0.0.1", "port": 0},
        on_audio=MagicMock(),
        on_satellite_change=callback or MagicMock(),
        resolve_satellite_room=resolve_satellite_room,
        upsert_satellite=upsert_satellite,
    )


def _register(server, device, addr=("192.168.1.50", 7776)):
    payload = json.dumps({"type": "register", "device": device}).encode("utf-8")
    server._handle_control(payload, addr)


def _heartbeat(server, device, addr=("192.168.1.50", 7776)):
    payload = json.dumps({"type": "heartbeat", "device": device}).encode("utf-8")
    server._handle_control(payload, addr)


class TestHeartbeatWatchdog:
    def test_stale_satellite_removed(self):
        server = _make_server()
        with server._lock:
            server._satellites["stale-sat"] = {
                "addr": ("192.168.1.100", 7776),
                "tts_addr": ("192.168.1.100", 7776),
                "room": "Wohnzimmer",
                "last_heartbeat": time.monotonic() - 31.0,
            }

        server._check_heartbeats()

        with server._lock:
            assert "stale-sat" not in server._satellites

    def test_stale_satellite_triggers_callback(self):
        callback = MagicMock()
        server = _make_server(callback)
        with server._lock:
            server._satellites["stale-sat"] = {
                "addr": ("192.168.1.100", 7776),
                "tts_addr": ("192.168.1.100", 7776),
                "room": "Wohnzimmer",
                "last_heartbeat": time.monotonic() - 31.0,
            }

        server._check_heartbeats()
        time.sleep(0.1)  # callback runs in daemon thread

        callback.assert_called_once()
        snapshot = callback.call_args[0][0]
        assert "stale-sat" not in snapshot

    def test_fresh_heartbeat_not_removed(self):
        callback = MagicMock()
        server = _make_server(callback)
        with server._lock:
            server._satellites["fresh-sat"] = {
                "addr": ("192.168.1.100", 7776),
                "tts_addr": ("192.168.1.100", 7776),
                "room": "Wohnzimmer",
                "last_heartbeat": time.monotonic(),
            }

        server._check_heartbeats()

        with server._lock:
            assert "fresh-sat" in server._satellites
        callback.assert_not_called()

    def test_partial_timeout_only_removes_stale(self):
        callback = MagicMock()
        server = _make_server(callback)
        with server._lock:
            server._satellites["stale-sat"] = {
                "addr": ("192.168.1.100", 7776),
                "tts_addr": ("192.168.1.100", 7776),
                "room": "Wohnzimmer",
                "last_heartbeat": time.monotonic() - 31.0,
            }
            server._satellites["fresh-sat"] = {
                "addr": ("192.168.1.101", 7776),
                "tts_addr": ("192.168.1.101", 7776),
                "room": "Küche",
                "last_heartbeat": time.monotonic(),
            }

        server._check_heartbeats()
        time.sleep(0.1)

        with server._lock:
            assert "stale-sat" not in server._satellites
            assert "fresh-sat" in server._satellites

        snapshot = callback.call_args[0][0]
        assert "stale-sat" not in snapshot
        assert "fresh-sat" in snapshot


class TestHeartbeatUpsertsLastSeen:
    def test_heartbeat_from_known_satellite_upserts(self):
        """Regression: heartbeats only refreshed the in-memory watchdog state, never
        RoomManager's last_seen — DB showed a satellite as never-updated forever,
        even while it kept heartbeating and staying connected."""
        upsert = MagicMock()
        server = _make_server(upsert_satellite=upsert)
        with server._lock:
            server._satellites["wz-sat"] = {
                "addr": ("192.168.1.100", 7776),
                "tts_addr": ("192.168.1.100", 7776),
                "room": "Wohnzimmer",
                "last_heartbeat": time.monotonic() - 5.0,
            }

        _heartbeat(server, "wz-sat")

        upsert.assert_called_once_with("wz-sat")

    def test_heartbeat_from_unknown_satellite_does_not_upsert(self):
        upsert = MagicMock()
        server = _make_server(upsert_satellite=upsert)

        _heartbeat(server, "ghost-sat")

        upsert.assert_not_called()


class TestRegisterRoomCheck:
    def test_register_without_room_not_tracked(self):
        callback = MagicMock()
        upsert = MagicMock()
        server = _make_server(callback, resolve_satellite_room=lambda _d: None, upsert_satellite=upsert)

        _register(server, "roomless-sat")

        with server._lock:
            assert "roomless-sat" not in server._satellites
        upsert.assert_called_once_with("roomless-sat")
        callback.assert_not_called()

    def test_register_with_room_tracked(self):
        callback = MagicMock()
        upsert = MagicMock()
        server = _make_server(callback, resolve_satellite_room=lambda _d: "wohnzimmer", upsert_satellite=upsert)

        _register(server, "wz-sat")
        time.sleep(0.1)  # callback runs in daemon thread

        with server._lock:
            assert server._satellites["wz-sat"]["room"] == "wohnzimmer"
        upsert.assert_called_once_with("wz-sat")
        callback.assert_called_once()
        snapshot = callback.call_args[0][0]
        assert snapshot.get("wz-sat") == "wohnzimmer"
