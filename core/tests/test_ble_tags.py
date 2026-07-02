import os

import pytest
from werkzeug.security import generate_password_hash

import hannah.utils.db as db_module
from hannah.ble_tags import BleTagManager
from hannah.models.user import User


@pytest.fixture
def db(tmp_path):
    db_module.DB_PATH = os.path.join(str(tmp_path), "h.db")
    db_module.init_db()
    return db_module.get_db


def _create_user(db, username="leonie") -> int:
    User.create(
        db(), username=username, display_name=username, email=f"{username}@example.com",
        password_hash=generate_password_hash("x"), trust_level=5, mood_level=5,
        system_messages=0, type="roomie", is_active=1,
    )
    return User.get(db(), username=username).id


@pytest.fixture
def manager(db):
    return BleTagManager(db)


class TestCRUD:
    """#115: BleTag als eigenes Modell (mac_address/label/user_id) statt JSON-Blob
    im generischen Settings-System."""

    def test_create_and_get(self, manager):
        created = manager.create_tag("AA:BB:CC:DD:EE:FF", "Schlüsselbund")

        assert created is not None
        records = manager.get_tag_records()
        assert len(records) == 1
        assert records[0]["mac_address"] == "aa:bb:cc:dd:ee:ff"
        assert records[0]["label"] == "Schlüsselbund"
        assert records[0]["user_id"] is None

    def test_create_with_owner(self, manager, db):
        user_id = _create_user(db)

        created = manager.create_tag("AA:BB:CC:DD:EE:FF", "Leonies Tag", user_id=user_id)

        assert created["user_id"] == user_id

    def test_create_duplicate_mac_fails(self, manager):
        manager.create_tag("AA:BB:CC:DD:EE:FF", "Tag 1")

        duplicate = manager.create_tag("aa:bb:cc:dd:ee:ff", "Tag 2")

        assert duplicate is None

    def test_update(self, manager):
        created = manager.create_tag("AA:BB:CC:DD:EE:FF", "Tag 1")

        ok = manager.update_tag(created["id"], "11:22:33:44:55:66", "Tag umbenannt", None)

        assert ok is True
        records = manager.get_tag_records()
        assert records[0]["mac_address"] == "11:22:33:44:55:66"
        assert records[0]["label"] == "Tag umbenannt"

    def test_update_not_found(self, manager):
        assert manager.update_tag(999, "aa:bb", "x", None) is False

    def test_delete(self, manager):
        created = manager.create_tag("AA:BB:CC:DD:EE:FF", "Tag 1")

        assert manager.delete_tag(created["id"]) is True
        assert manager.get_tag_records() == []

    def test_delete_not_found(self, manager):
        assert manager.delete_tag(999) is False
