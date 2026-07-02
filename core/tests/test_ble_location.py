from hannah.ble_location import BleLocationEngine


class TestTagLoading:
    """#115: BleTag ist jetzt ein eigenes DB-Modell mit user_id direkt als FK-Spalte —
    BleLocationEngine bekommt user_id daher schon aufgelöst rein (kein Username-Lookup
    mehr nötig, das übernimmt hannah.ble_tags.BleTagManager/das Model selbst)."""

    def test_tag_with_user_id_is_loaded(self):
        engine = BleLocationEngine(
            {"tags": [{"mac_address": "AA:BB:CC:DD:EE:FF", "label": "leonie", "user_id": 42}]},
            get_satellite_room=lambda _d: None,
        )

        tag = engine._tags["aa:bb:cc:dd:ee:ff"]
        assert tag.mac == "aa:bb:cc:dd:ee:ff"
        assert tag.label == "leonie"
        assert tag.user_id == 42

    def test_tag_without_user_id_is_valid(self):
        """Tags ohne Owner sind valide (reines Location-Tracking, keine Resident-Bindung)."""
        engine = BleLocationEngine(
            {"tags": [{"mac_address": "AA:BB:CC:DD:EE:FF", "label": "keychain"}]},
            get_satellite_room=lambda _d: None,
        )

        tag = engine._tags["aa:bb:cc:dd:ee:ff"]
        assert tag.user_id is None

    def test_legacy_mac_key_still_accepted(self):
        """"mac" (statt "mac_address") wird weiterhin akzeptiert."""
        engine = BleLocationEngine(
            {"tags": [{"mac": "AA:BB:CC:DD:EE:FF", "label": "leonie", "user_id": 7}]},
            get_satellite_room=lambda _d: None,
        )

        tag = engine._tags["aa:bb:cc:dd:ee:ff"]
        assert tag.user_id == 7
