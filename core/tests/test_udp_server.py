import time
from unittest.mock import MagicMock

from hannah.udp_server import UDPServer


def _make_server(callback=None):
    return UDPServer(
        cfg={"host": "127.0.0.1", "port": 0},
        on_audio=MagicMock(),
        on_satellite_change=callback or MagicMock(),
    )


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
