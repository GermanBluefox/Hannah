import os

import pytest
from werkzeug.security import generate_password_hash

import hannah.utils.db as db_module
from hannah.car_registry import CarRegistry
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
def registry(db):
    return CarRegistry(db)


class TestCRUD:
    """#115: Car als eigenes Modell + user_to_car-Pivot statt JSON-Blob
    (owner_roomies) im generischen Settings-System. #123: eigenes name-Feld
    fürs Anzeigefeld, getrennt vom technischen topic_prefix."""

    def test_create_and_get(self, registry, db):
        u1 = _create_user(db, "leonie")
        u2 = _create_user(db, "zoey")

        created = registry.create_car("Mein Auto", "auto1", "Musterstr. 1", [u1, u2])

        assert created is not None
        records = registry.get_car_records()
        assert len(records) == 1
        assert records[0]["name"] == "Mein Auto"
        assert records[0]["topic_prefix"] == "auto1"
        assert records[0]["home_address"] == "Musterstr. 1"
        assert sorted(records[0]["owner_user_ids"]) == sorted([u1, u2])

    def test_create_without_owners(self, registry):
        created = registry.create_car("Mein Auto", "auto1", "", [])

        assert created["owner_user_ids"] == []
        assert registry.get_car_records()[0]["owner_user_ids"] == []

    def test_create_duplicate_topic_prefix_fails(self, registry):
        registry.create_car("Mein Auto", "auto1", "", [])

        duplicate = registry.create_car("Anderes Auto", "auto1", "", [])

        assert duplicate is None

    def test_update_replaces_owners(self, registry, db):
        u1 = _create_user(db, "leonie")
        u2 = _create_user(db, "zoey")
        created = registry.create_car("Mein Auto", "auto1", "", [u1])

        ok = registry.update_car(created["id"], "Neuer Name", "auto1", "Neue Adresse", [u2])

        assert ok is True
        record = registry.get_car_records()[0]
        assert record["name"] == "Neuer Name"
        assert record["home_address"] == "Neue Adresse"
        assert record["owner_user_ids"] == [u2]

    def test_update_not_found(self, registry):
        assert registry.update_car(999, "Mein Auto", "auto1", "", []) is False

    def test_delete_cascades_owners(self, registry, db):
        u1 = _create_user(db, "leonie")
        created = registry.create_car("Mein Auto", "auto1", "", [u1])

        assert registry.delete_car(created["id"]) is True
        assert registry.get_car_records() == []

    def test_delete_not_found(self, registry):
        assert registry.delete_car(999) is False


class TestTrackerConfigs:
    """get_tracker_configs() übersetzt Owner-User-IDs für car_tracker.py (das nur
    Roomie-IDs kennt) via die vom Aufrufer übergebene resolve_roomie_id-Funktion."""

    def test_resolves_owners_to_roomie_ids(self, registry, db):
        u1 = _create_user(db, "leonie")
        registry.create_car("Mein Auto", "auto1", "Musterstr. 1", [u1])

        configs = registry.get_tracker_configs(resolve_roomie_id=lambda uid: "leonie" if uid == u1 else "")

        assert configs == [{
            "topic_prefix": "auto1", "home_address": "Musterstr. 1", "owner_roomies": ["leonie"],
        }]

    def test_owner_without_roomie_link_is_skipped(self, registry, db):
        u1 = _create_user(db, "leonie")
        registry.create_car("Mein Auto", "auto1", "", [u1])

        configs = registry.get_tracker_configs(resolve_roomie_id=lambda _uid: "")

        assert configs == [{"topic_prefix": "auto1", "home_address": "", "owner_roomies": []}]

    def test_returns_empty_list_when_no_cars(self, registry):
        assert registry.get_tracker_configs(resolve_roomie_id=lambda _uid: "") == []
