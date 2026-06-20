import tempfile
import os

import pytest

from hannah.room_manager import RoomManager


@pytest.fixture
def manager():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    mgr = RoomManager({"db_path": path, "seed_ttl_days": 7})
    yield mgr
    try:
        os.remove(path)
    except PermissionError:
        pass  # sqlite3-Connection-Objekte werden erst beim GC geschlossen (Windows hält Datei-Handle)


def _insert_satellite(mgr, device_id, seed, days_old):
    with mgr._connect() as conn:
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
        with manager._connect() as conn:
            conn.execute(
                """INSERT INTO satellites (device_id, seed, display_name, paired_at, created_at)
                   VALUES (?, NULL, ?, datetime('now', '-30 days'), datetime('now', '-30 days'))""",
                ("paired-sat", "paired-sat"),
            )

        removed = manager.cleanup_stale_seeds()

        assert removed == 0
        assert manager.get_satellite("paired-sat") is not None


class TestSyncRooms:
    def test_empty_snapshot_is_noop(self, manager):
        manager.sync_rooms({"wohnzimmer": "Wohnzimmer"})

        orphaned = manager.sync_rooms({})

        assert orphaned == []
        assert manager.get_rooms() == [{"room_id": "wohnzimmer", "display_name": "Wohnzimmer"}]

    def test_vanished_room_orphans_its_satellite(self, manager):
        manager.sync_rooms({"wohnzimmer": "Wohnzimmer"})
        _insert_satellite(manager, "wz-esp", "seed-1", days_old=0)
        manager.set_satellite_room("wz-esp", "wohnzimmer")

        orphaned = manager.sync_rooms({"kueche": "Küche"})

        assert orphaned == [("wz-esp", "wohnzimmer")]
        assert manager.get_satellite_room("wz-esp") is None
        assert manager.get_rooms() == [{"room_id": "kueche", "display_name": "Küche"}]

    def test_vanished_room_without_satellites_just_removed(self, manager):
        manager.sync_rooms({"keller": "Keller"})

        orphaned = manager.sync_rooms({"kueche": "Küche"})

        assert orphaned == []
        assert manager.get_rooms() == [{"room_id": "kueche", "display_name": "Küche"}]

    def test_room_still_present_keeps_its_satellite(self, manager):
        manager.sync_rooms({"wohnzimmer": "Wohnzimmer"})
        _insert_satellite(manager, "wz-esp", "seed-1", days_old=0)
        manager.set_satellite_room("wz-esp", "wohnzimmer")

        orphaned = manager.sync_rooms({"wohnzimmer": "Wohnzimmer"})

        assert orphaned == []
        assert manager.get_satellite_room("wz-esp") == "wohnzimmer"
