import os

import pytest
from werkzeug.security import generate_password_hash

import hannah.utils.db as db_module
from hannah.models.ble_tag import BleTag
from hannah.models.car import Car
from hannah.models.user import User


@pytest.fixture
def db(tmp_path):
    db_module.DB_PATH = os.path.join(str(tmp_path), "h.db")
    db_module.init_db()
    return db_module.get_db


def _create_user(db, username="leonie") -> User:
    User.create(
        db(), username=username, display_name=username, email=f"{username}@example.com",
        password_hash=generate_password_hash("x"), trust_level=5, mood_level=5,
        system_messages=0, type="roomie", is_active=1,
    )
    return User.get(db(), username=username)


class TestBleTagUserRelation:
    """#115: BleTag.user_id ist eine echte FK-Spalte (1:n) — .user liefert das
    zugehörige User-Objekt, analog zu User.linked_accounts/satellites."""

    def test_user_property_returns_owner(self, db):
        user = _create_user(db)
        BleTag.create(db(), mac_address="aa:bb:cc:dd:ee:ff", label="leonie", user_id=user.id)
        tag = BleTag.get(db(), mac_address="aa:bb:cc:dd:ee:ff")

        assert tag.user.id == user.id
        assert tag.user.username == "leonie"

    def test_user_property_none_when_unowned(self, db):
        BleTag.create(db(), mac_address="aa:bb:cc:dd:ee:ff", label="keychain")
        tag = BleTag.get(db(), mac_address="aa:bb:cc:dd:ee:ff")

        assert tag.user is None

    def test_reverse_ble_tags_property_on_user(self, db):
        user = _create_user(db)
        BleTag.create(db(), mac_address="aa:bb:cc:dd:ee:ff", label="leonie", user_id=user.id)
        BleTag.create(db(), mac_address="11:22:33:44:55:66", label="keychain")

        tags = user.ble_tags

        assert [t.mac_address for t in tags] == ["aa:bb:cc:dd:ee:ff"]


class TestCarUserRelation:
    """#115: Car ↔ User ist n:n über die user_to_car-Pivot-Tabelle — .owners auf Car
    und .cars auf User spiegeln sich, analog zur linked_accounts/satellites-Logik."""

    def test_owners_property_returns_all_owners(self, db):
        u1 = _create_user(db, "leonie")
        u2 = _create_user(db, "zoey")
        car = Car.create(db(), topic_prefix="auto1", home_address="")
        conn = db()
        conn.execute("INSERT INTO user_to_car (user_id, car_id) VALUES (?, ?)", (u1.id, car.id))
        conn.execute("INSERT INTO user_to_car (user_id, car_id) VALUES (?, ?)", (u2.id, car.id))
        conn.commit()

        owners = car.owners

        assert sorted(u.username for u in owners) == ["leonie", "zoey"]

    def test_owners_property_empty_when_unowned(self, db):
        car = Car.create(db(), topic_prefix="auto1", home_address="")

        assert car.owners == []

    def test_reverse_cars_property_on_user(self, db):
        user = _create_user(db)
        car = Car.create(db(), topic_prefix="auto1", home_address="")
        conn = db()
        conn.execute("INSERT INTO user_to_car (user_id, car_id) VALUES (?, ?)", (user.id, car.id))
        conn.commit()

        cars = user.cars

        assert [c.topic_prefix for c in cars] == ["auto1"]
