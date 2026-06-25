from unittest.mock import MagicMock

from hannah.ble_location import BleLocationEngine


def _make_user(user_id):
    user = MagicMock()
    user.id = user_id
    return user


class TestTagUsernameResolution:
    def test_known_username_resolves_to_user_id(self):
        user_manager = MagicMock()
        user_manager.get_user_by_username.return_value = _make_user(42)

        engine = BleLocationEngine(
            {"tags": [{"mac": "AA:BB:CC:DD:EE:FF", "label": "leonie", "username": "leonie"}]},
            get_satellite_room=lambda _d: None,
            user_manager=user_manager,
        )

        tag = engine._tags["aa:bb:cc:dd:ee:ff"]
        assert tag.user_id == 42
        user_manager.get_user_by_username.assert_called_once_with(username="leonie")

    def test_unknown_username_warns_and_leaves_user_id_none(self, caplog):
        user_manager = MagicMock()
        user_manager.get_user_by_username.return_value = None

        engine = BleLocationEngine(
            {"tags": [{"mac": "AA:BB:CC:DD:EE:FF", "label": "leonie", "username": "typo"}]},
            get_satellite_room=lambda _d: None,
            user_manager=user_manager,
        )

        tag = engine._tags["aa:bb:cc:dd:ee:ff"]
        assert tag.user_id is None
        assert "typo" in caplog.text
        assert "Tippfehler" in caplog.text

    def test_tag_without_username_is_not_a_typo_warning(self, caplog):
        """Regression: tags without a username are valid (pure location tracking,
        no resident binding) — must not be flagged as if they were a config typo."""
        user_manager = MagicMock()

        engine = BleLocationEngine(
            {"tags": [{"mac": "AA:BB:CC:DD:EE:FF", "label": "keychain"}]},
            get_satellite_room=lambda _d: None,
            user_manager=user_manager,
        )

        tag = engine._tags["aa:bb:cc:dd:ee:ff"]
        assert tag.user_id is None
        user_manager.get_user_by_username.assert_not_called()
        assert "Tippfehler" not in caplog.text
