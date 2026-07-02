import json
from types import SimpleNamespace

from hannah.mqtt_handler import MQTTHandler


def _msg(topic: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode())


class TestPlayAssetResult:
    """#116: play_asset war Fire-and-Forget — der Satellit meldet jetzt per
    hannah/satellite/{device}/play_asset/result ein Ack/Nack zurück."""

    def test_dispatches_ok_result(self):
        handler = MQTTHandler({}, {})
        results = []
        handler.set_play_asset_result_handler(lambda device, asset_id, ok: results.append((device, asset_id, ok)))

        handler._on_message(None, None, _msg(
            "hannah/satellite/wz-sat/play_asset/result", {"asset_id": "alarm_ring", "ok": True},
        ))

        assert results == [("wz-sat", "alarm_ring", True)]

    def test_dispatches_nack_result(self):
        handler = MQTTHandler({}, {})
        results = []
        handler.set_play_asset_result_handler(lambda device, asset_id, ok: results.append((device, asset_id, ok)))

        handler._on_message(None, None, _msg(
            "hannah/satellite/wz-sat/play_asset/result", {"asset_id": "alarm_ring", "ok": False},
        ))

        assert results == [("wz-sat", "alarm_ring", False)]

    def test_missing_asset_id_is_ignored(self):
        handler = MQTTHandler({}, {})
        results = []
        handler.set_play_asset_result_handler(lambda *a: results.append(a))

        handler._on_message(None, None, _msg("hannah/satellite/wz-sat/play_asset/result", {"ok": True}))

        assert results == []

    def test_malformed_payload_does_not_raise(self):
        handler = MQTTHandler({}, {})
        handler.set_play_asset_result_handler(lambda *a: None)

        handler._on_message(None, None, SimpleNamespace(
            topic="hannah/satellite/wz-sat/play_asset/result", payload=b"not json",
        ))

    def test_no_handler_registered_does_not_raise(self):
        handler = MQTTHandler({}, {})

        handler._on_message(None, None, _msg(
            "hannah/satellite/wz-sat/play_asset/result", {"asset_id": "alarm_ring", "ok": True},
        ))
