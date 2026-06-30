import os

import pytest

import hannah.utils.db as db_module
from hannah.satellite_manager import SatelliteManager


@pytest.fixture
def manager(tmp_path):
    """Real (non-mocked) SatelliteManager against a throwaway SQLite DB — see
    hannah.utils.db.DB_PATH docstring note in test_grpc_server.py for why this
    has to patch the module attribute directly rather than just an env var."""
    db_module.DB_PATH = os.path.join(str(tmp_path), "h.db")
    db_module.init_db()
    yield SatelliteManager(db_module.get_db, {"seed_ttl_days": 7})


def _insert_satellite(mgr, device_id, seed, days_old):
    with mgr._db() as conn:
        conn.execute(
            """INSERT INTO satellites (device_id, seed, display_name, created_at)
               VALUES (?, ?, ?, datetime('now', ?))""",
            (device_id, seed, device_id, f"-{days_old} days"),
        )


class TestCleanupStaleSeeds:
    def test_stale_unpaired_seed_removed(self, manager):
        _insert_satellite(manager, "old-seed", "seed-abc", days_old=8)

        removed = manager.cleanup_stale_seeds()

        assert removed == 1
        assert manager.get_satellite("old-seed") is None

    def test_fresh_unpaired_seed_kept(self, manager):
        _insert_satellite(manager, "new-seed", "seed-def", days_old=1)

        removed = manager.cleanup_stale_seeds()

        assert removed == 0
        assert manager.get_satellite("new-seed") is not None

    def test_paired_satellite_kept_regardless_of_age(self, manager):
        with manager._db() as conn:
            conn.execute(
                """INSERT INTO satellites (device_id, seed, display_name, paired_at, created_at)
                   VALUES (?, NULL, ?, datetime('now', '-30 days'), datetime('now', '-30 days'))""",
                ("paired-sat", "paired-sat"),
            )

        removed = manager.cleanup_stale_seeds()

        assert removed == 0
        assert manager.get_satellite("paired-sat") is not None


class TestOwner:
    def test_set_and_get_owner(self, manager):
        _insert_satellite(manager, "wz-esp", "seed-1", days_old=0)

        ok = manager.set_satellite_owner("wz-esp", 1)

        assert ok is True
        assert manager.get_satellite_owner("wz-esp") == 1

    def test_clear_owner(self, manager):
        _insert_satellite(manager, "wz-esp", "seed-1", days_old=0)
        manager.set_satellite_owner("wz-esp", 1)

        manager.set_satellite_owner("wz-esp", None)

        assert manager.get_satellite_owner("wz-esp") is None

    def test_unknown_device_returns_false(self, manager):
        assert manager.set_satellite_owner("unknown", 1) is False


class TestRoomAndUserLookup:
    """get_room_satellite_ids/get_user_satellites — Grundlage für #31s Announce-Routing."""

    def test_get_room_satellite_ids(self, manager):
        with manager._db() as conn:
            conn.execute("INSERT INTO rooms (room_id, display_name) VALUES ('wohnzimmer', 'Wohnzimmer')")
        _insert_satellite(manager, "wz-esp", "seed-1", days_old=0)
        _insert_satellite(manager, "ku-esp", "seed-2", days_old=0)
        manager.set_satellite_room("wz-esp", "wohnzimmer")

        assert manager.get_room_satellite_ids("wohnzimmer") == ["wz-esp"]

    def test_get_room_satellite_ids_empty_room(self, manager):
        with manager._db() as conn:
            conn.execute("INSERT INTO rooms (room_id, display_name) VALUES ('keller', 'Keller')")

        assert manager.get_room_satellite_ids("keller") == []

    def test_get_user_satellites(self, manager):
        _insert_satellite(manager, "wz-esp", "seed-1", days_old=0)
        _insert_satellite(manager, "ku-esp", "seed-2", days_old=0)
        manager.set_satellite_owner("wz-esp", 1)

        result = manager.get_user_satellites(1)

        assert [s["device_id"] for s in result] == ["wz-esp"]

    def test_get_user_satellites_none_assigned(self, manager):
        assert manager.get_user_satellites(1) == []
