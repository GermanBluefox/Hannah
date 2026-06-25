import os
from unittest.mock import MagicMock

from werkzeug.security import generate_password_hash

import hannah.utils.db as db_module
from hannah.user_manager import UserManager


def _make_user_manager(tmp_path):
    """Real (non-mocked) UserManager against a throwaway SQLite DB — see
    test_grpc_server.py's _make_user_manager_with_leonie for why DB_PATH has to be
    patched as a module attribute rather than just an env var."""
    db_module.DB_PATH = os.path.join(str(tmp_path), "h.db")
    db_module.init_db()
    return UserManager(db_module.get_db)


class TestDumpPresentUsers:
    def test_present_user_with_residents_link_gets_pushed(self, tmp_path):
        user_manager = _make_user_manager(tmp_path)
        pusher = MagicMock()
        user_manager.set_residents_pusher(pusher)
        user = user_manager.create_user("leonie", generate_password_hash("x"), email="leonie@example.com")
        user.link_account("residents", "leonie_roomie", provider_payload={"roomie_id": "leonie", "resident_type": "roomie"})
        user.presence = True

        user_manager.dump_present_users()

        pusher.assert_called_once_with("leonie", True, "roomie")

    def test_absent_user_is_not_pushed(self, tmp_path):
        user_manager = _make_user_manager(tmp_path)
        pusher = MagicMock()
        user_manager.set_residents_pusher(pusher)
        user = user_manager.create_user("leonie", generate_password_hash("x"), email="leonie@example.com")
        user.link_account("residents", "leonie_roomie", provider_payload={"roomie_id": "leonie", "resident_type": "roomie"})
        # presence bleibt False (Default) — kein Aufruf erwartet

        user_manager.dump_present_users()

        pusher.assert_not_called()

    def test_present_user_without_residents_link_is_skipped(self, tmp_path):
        """Regression: ein User ohne residents-Link darf keinen Pusher-Aufruf auslösen
        (z.B. roomie_id=None würde sonst als 'anwesend' Richtung ioBroker gepusht)."""
        user_manager = _make_user_manager(tmp_path)
        pusher = MagicMock()
        user_manager.set_residents_pusher(pusher)
        user = user_manager.create_user("leonie", generate_password_hash("x"), email="leonie@example.com")
        user.presence = True

        user_manager.dump_present_users()

        pusher.assert_not_called()

    def test_no_pusher_set_does_not_crash(self, tmp_path):
        user_manager = _make_user_manager(tmp_path)
        user = user_manager.create_user("leonie", generate_password_hash("x"), email="leonie@example.com")
        user.presence = True

        user_manager.dump_present_users()
