"""
Hannah Room Manager

SQLite-Persistenz für:
  - Räume (sync aus ioBroker)
  - Gruppen von Räumen (n:n)
  - Satelliten und ihre Raum-Zuweisung
"""
import logging
import sqlite3
import threading
from typing import Optional

log = logging.getLogger(__name__)


class RoomManager:
    def __init__(self, cfg: dict):
        self._db_path = cfg.get("db_path", "rooms.db")
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Schema

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS rooms (
                    room_id      TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS groups (
                    group_id     TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS group_rooms (
                    group_id TEXT NOT NULL REFERENCES groups(group_id) ON DELETE CASCADE,
                    room_id  TEXT NOT NULL REFERENCES rooms(room_id)   ON DELETE CASCADE,
                    PRIMARY KEY (group_id, room_id)
                );

                CREATE TABLE IF NOT EXISTS satellites (
                    device_id    TEXT PRIMARY KEY,
                    serial       TEXT UNIQUE,
                    seed         TEXT,
                    display_name TEXT,
                    room_id      TEXT REFERENCES rooms(room_id),
                    last_seen    TEXT,
                    paired_at    TEXT,
                    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)
            self._migrate_db(conn)

    def _migrate_db(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(satellites)")}
        for col, definition in [
            ("serial",    "TEXT"),
            ("seed",      "TEXT"),
            ("paired_at", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE satellites ADD COLUMN {col} {definition}")
        existing_indexes = {row[1] for row in conn.execute("PRAGMA index_list(satellites)")}
        if "uq_satellites_serial" not in existing_indexes:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_satellites_serial ON satellites(serial) WHERE serial IS NOT NULL")

    # ------------------------------------------------------------------
    # Räume

    def sync_rooms(self, rooms: dict[str, str]) -> None:
        """
        Übernimmt den Raum-Katalog aus ioBroker.
        rooms = {room_key: display_name}  (z.B. {"wohnzimmer": "Wohnzimmer"})
        Bereits vorhandene Räume werden nicht gelöscht (Gruppen-Referenzen bleiben erhalten).
        """
        if not rooms:
            return
        with self._lock, self._connect() as conn:
            for room_id, display_name in rooms.items():
                conn.execute(
                    "INSERT OR IGNORE INTO rooms (room_id, display_name) VALUES (?, ?)",
                    (room_id, display_name),
                )
                conn.execute(
                    "UPDATE rooms SET display_name = ? WHERE room_id = ?",
                    (display_name, room_id),
                )
        log.debug(f"RoomManager: {len(rooms)} Räume synchronisiert")

    def get_rooms(self) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT room_id, display_name FROM rooms ORDER BY display_name"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Gruppen

    def get_groups(self) -> list[dict]:
        """Alle Gruppen mit ihren Räumen."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            groups = conn.execute(
                "SELECT group_id, display_name FROM groups ORDER BY display_name"
            ).fetchall()
            result = []
            for g in groups:
                room_rows = conn.execute(
                    """SELECT r.room_id, r.display_name
                       FROM group_rooms gr
                       JOIN rooms r ON r.room_id = gr.room_id
                       WHERE gr.group_id = ?
                       ORDER BY r.display_name""",
                    (g["group_id"],),
                ).fetchall()
                result.append({
                    "group_id": g["group_id"],
                    "display_name": g["display_name"],
                    "rooms": [dict(r) for r in room_rows],
                })
        return result

    def get_group(self, group_id: str) -> Optional[dict]:
        groups = self.get_groups()
        return next((g for g in groups if g["group_id"] == group_id), None)

    def create_group(self, group_id: str, display_name: str) -> bool:
        """Legt eine neue Gruppe an. Gibt False zurück wenn die ID bereits existiert."""
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO groups (group_id, display_name) VALUES (?, ?)",
                    (group_id, display_name),
                )
            log.info(f"RoomManager: Gruppe '{group_id}' angelegt")
            return True
        except sqlite3.IntegrityError:
            return False

    def update_group(self, group_id: str, display_name: str) -> bool:
        with self._lock, self._connect() as conn:
            c = conn.execute(
                "UPDATE groups SET display_name = ? WHERE group_id = ?",
                (display_name, group_id),
            )
        return c.rowcount > 0

    def delete_group(self, group_id: str) -> bool:
        with self._lock, self._connect() as conn:
            c = conn.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
        log.info(f"RoomManager: Gruppe '{group_id}' gelöscht")
        return c.rowcount > 0

    def set_group_rooms(self, group_id: str, room_ids: list[str]) -> None:
        """Setzt die Räume einer Gruppe (ersetzt vorhandene Einträge komplett)."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM group_rooms WHERE group_id = ?", (group_id,))
            for room_id in room_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO group_rooms (group_id, room_id) VALUES (?, ?)",
                    (group_id, room_id),
                )
        log.debug(f"RoomManager: Gruppe '{group_id}' → {len(room_ids)} Räume gesetzt")

    def get_group_room_ids(self, group_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT room_id FROM group_rooms WHERE group_id = ?", (group_id,)
            ).fetchall()
        return [r[0] for r in rows]

    def resolve_group(self, group_id: str) -> list[str]:
        """Gibt alle room_ids einer Gruppe zurück."""
        return self.get_group_room_ids(group_id)

    def get_group_room_id_map(self) -> dict[str, list[str]]:
        """Gibt {group_id: [room_id, ...]} für alle Gruppen zurück (eine DB-Query)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT group_id, room_id FROM group_rooms ORDER BY group_id"
            ).fetchall()
        result: dict[str, list[str]] = {}
        for group_id, room_id in rows:
            result.setdefault(group_id, []).append(room_id)
        return result

    # ------------------------------------------------------------------
    # Satelliten

    def provision_satellite(self, seed: str, display_name: str, room_id: Optional[str]) -> bool:
        """Pre-registers a satellite before flash. seed is a one-time pairing token."""
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """INSERT INTO satellites (device_id, seed, display_name, room_id)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(device_id) DO UPDATE
                           SET seed=excluded.seed, display_name=excluded.display_name,
                               room_id=excluded.room_id""",
                    (seed, seed, display_name, room_id),
                )
            log.info("RoomManager: provisioned satellite seed=%s name=%s", seed[:8], display_name)
            return True
        except Exception as e:
            log.error("RoomManager: provision_satellite failed: %s", e)
            return False

    def pair_satellite(self, device_id: str, serial: str, seed: str) -> bool:
        """Links a hardware serial to a pre-provisioned seed entry.

        If the seed matches a pre-provisioned record, the serial is stored and
        the seed is cleared. The device_id is updated to the final identifier.
        Returns True if pairing succeeded, False if seed not found.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT device_id, display_name, room_id FROM satellites WHERE seed = ?",
                (seed,),
            ).fetchone()
            if row is None:
                return False
            old_device_id = row[0]
            if old_device_id != device_id:
                # Rename: update device_id to the one the proxy uses
                try:
                    conn.execute(
                        "UPDATE satellites SET device_id=?, serial=?, seed=NULL, paired_at=datetime('now') WHERE seed=?",
                        (device_id, serial, seed),
                    )
                except sqlite3.IntegrityError:
                    # device_id already exists under a different record; just update serial
                    conn.execute("DELETE FROM satellites WHERE seed = ?", (seed,))
                    conn.execute(
                        "UPDATE satellites SET serial=?, seed=NULL, paired_at=datetime('now') WHERE device_id=?",
                        (serial, device_id),
                    )
            else:
                conn.execute(
                    "UPDATE satellites SET serial=?, seed=NULL, paired_at=datetime('now') WHERE seed=?",
                    (serial, seed),
                )
        log.info("RoomManager: paired serial=%s → device_id=%s", serial, device_id)
        return True

    def get_satellite_by_serial(self, serial: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT device_id, serial, display_name, room_id FROM satellites WHERE serial = ?",
                (serial,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_satellite(self, device_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO satellites (device_id, last_seen)
                   VALUES (?, datetime('now'))
                   ON CONFLICT(device_id) DO UPDATE SET last_seen = datetime('now')""",
                (device_id,),
            )

    def set_satellite_room(self, device_id: str, room_id: Optional[str]) -> bool:
        with self._lock, self._connect() as conn:
            c = conn.execute(
                "UPDATE satellites SET room_id = ? WHERE device_id = ?",
                (room_id, device_id),
            )
        return c.rowcount > 0

    def set_satellite_display_name(self, device_id: str, display_name: str) -> bool:
        with self._lock, self._connect() as conn:
            c = conn.execute(
                "UPDATE satellites SET display_name = ? WHERE device_id = ?",
                (display_name, device_id),
            )
        return c.rowcount > 0

    def get_satellite_room_map(self) -> dict[str, str]:
        """Gibt {device_id: room_id, serial: room_id} für alle Satelliten mit DB-Raum-Zuweisung zurück.

        Sowohl device_id als auch serial (wenn vorhanden) werden als Keys eingetragen, damit
        _resolve_targets() mit beiden Routing-Keys (serials für gepaarte, device_ids für
        ungepaarte Satelliten) korrekt auflöst.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT device_id, serial, room_id FROM satellites WHERE room_id IS NOT NULL"
            ).fetchall()
        result: dict[str, str] = {}
        for device_id, serial, room_id in rows:
            result[device_id] = room_id
            if serial:
                result[serial] = room_id
        return result

    def get_satellite_room(self, device_id: str) -> Optional[str]:
        """Gibt die zugewiesene room_id zurück oder None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT room_id FROM satellites WHERE device_id = ?", (device_id,)
            ).fetchone()
        if row is None:
            return None
        return row[0]

    def get_satellites(self) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT s.device_id, s.display_name, s.room_id, s.last_seen,
                          r.display_name AS room_display_name
                   FROM satellites s
                   LEFT JOIN rooms r ON r.room_id = s.room_id
                   ORDER BY s.device_id"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
