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
import time
from typing import Optional

log = logging.getLogger(__name__)


class RoomManager:
    _CLEANUP_INTERVAL_S = 3600  # Prüfintervall für veraltete unpaired Seeds

    def __init__(self, cfg: dict):
        self._db_path = cfg.get("db_path", "rooms.db")
        self._seed_ttl_days = int(cfg.get("seed_ttl_days", 7))
        self._lock = threading.Lock()
        self._init_db()
        threading.Thread(
            target=self._cleanup_loop, daemon=True, name="hannah-roommanager-cleanup"
        ).start()

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
            ("seed",      "TEXT"),
            ("paired_at", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE satellites ADD COLUMN {col} {definition}")

    # ------------------------------------------------------------------
    # Räume

    def sync_rooms(self, rooms: dict[str, str]) -> list[tuple[str, str]]:
        """
        Übernimmt den Raum-Katalog aus ioBroker.
        rooms = {room_key: display_name}  (z.B. {"wohnzimmer": "Wohnzimmer"})
        Räume, die nicht mehr in rooms enthalten sind, werden gelöscht; Satelliten,
        die noch auf einen solchen Raum zeigten, werden auf room_id=NULL gesetzt
        (sie existieren weiter in der DB, sind aber logisch ohne Raum — siehe
        execute()/agent_satellite_update: Satelliten ohne room_id werden nicht
        an den Adapter weitergeleitet).
        Gibt [(device_id, room_id), ...] der davon betroffenen Satelliten zurück,
        damit der Aufrufer den Adapter per agent_satellite_deleted() informieren kann.
        """
        if not rooms:
            return []
        orphaned: list[tuple[str, str]] = []
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
            existing_room_ids = {row[0] for row in conn.execute("SELECT room_id FROM rooms")}
            vanished = existing_room_ids - set(rooms.keys())
            for room_id in vanished:
                rows = conn.execute(
                    "SELECT device_id FROM satellites WHERE room_id = ?", (room_id,)
                ).fetchall()
                orphaned.extend((device_id, room_id) for (device_id,) in rows)
                conn.execute("UPDATE satellites SET room_id = NULL WHERE room_id = ?", (room_id,))
                conn.execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))
        log.debug(f"RoomManager: {len(rooms)} Räume synchronisiert")
        if vanished:
            log.info(f"RoomManager: {len(vanished)} Raum/Räume entfernt, {len(orphaned)} Satellit(en) verwaist: {orphaned}")
        return orphaned

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

    def pair_satellite(self, device_id: str, seed: str) -> bool:
        """Links a device_id (eFuse MAC) to a pre-provisioned seed entry.

        Looks up the seed, renames the record's device_id to the hardware device_id,
        and clears the seed. Returns True if pairing succeeded, False if seed not found.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT device_id FROM satellites WHERE seed = ?",
                (seed,),
            ).fetchone()
            if row is None:
                return False
            old_device_id = row[0]
            if old_device_id != device_id:
                try:
                    conn.execute(
                        "UPDATE satellites SET device_id=?, seed=NULL, paired_at=datetime('now') WHERE seed=?",
                        (device_id, seed),
                    )
                except sqlite3.IntegrityError:
                    conn.execute("DELETE FROM satellites WHERE seed = ?", (seed,))
                    conn.execute(
                        "UPDATE satellites SET seed=NULL, paired_at=datetime('now') WHERE device_id=?",
                        (device_id,),
                    )
            else:
                conn.execute(
                    "UPDATE satellites SET seed=NULL, paired_at=datetime('now') WHERE seed=?",
                    (seed,),
                )
        log.info("RoomManager: paired device_id=%s", device_id)
        return True

    def resolve_satellite_name(self, device_id: str) -> Optional[str]:
        """Return the provisioned display_name for a satellite, or None if not set."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT display_name FROM satellites WHERE device_id = ?", (device_id,)
            ).fetchone()
        return row["display_name"] if row and row["display_name"] else None

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
        """Gibt {device_id: room_id} für alle Satelliten mit DB-Raum-Zuweisung zurück."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT device_id, room_id FROM satellites WHERE room_id IS NOT NULL"
            ).fetchall()
        return {device_id: room_id for device_id, room_id in rows}

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

    def get_satellite(self, device_id: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT device_id, display_name, room_id FROM satellites WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_satellite(self, device_id: str) -> bool:
        with self._lock, self._connect() as conn:
            c = conn.execute("DELETE FROM satellites WHERE device_id = ?", (device_id,))
        log.info(f"RoomManager: Satellit '{device_id}' gelöscht")
        return c.rowcount > 0

    def cleanup_stale_seeds(self) -> int:
        """Löscht provisionierte, aber nie gepairte Satelliten (seed gesetzt) älter als seed_ttl_days."""
        with self._lock, self._connect() as conn:
            c = conn.execute(
                "DELETE FROM satellites WHERE seed IS NOT NULL AND created_at < datetime('now', ?)",
                (f"-{self._seed_ttl_days} days",),
            )
        if c.rowcount:
            log.info(
                "RoomManager: %d veraltete unpaired Seed(s) gelöscht (>%dd)",
                c.rowcount, self._seed_ttl_days,
            )
        return c.rowcount

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(self._CLEANUP_INTERVAL_S)
            try:
                self.cleanup_stale_seeds()
            except Exception as e:
                log.error("RoomManager: cleanup_stale_seeds fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
