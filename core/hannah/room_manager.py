"""
Hannah Room Manager

Verwaltet, über hannah.models, Persistenz für:
  - Räume (sync aus ioBroker)
  - Gruppen von Räumen (n:n über group_rooms — kein eigenes Model, per Join-Query)
  - Satelliten und ihre Raum-Zuweisung
"""
import datetime
import logging
import sqlite3
import threading
import time
from typing import Callable, Optional

from hannah.models.room import Room
from hannah.models.group import Group
from hannah.models.satellite import Satellite

log = logging.getLogger(__name__)


def _now_sql() -> str:
    """UTC-Zeitstempel im selben Format wie SQLite's datetime('now')."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class RoomManager:
    _CLEANUP_INTERVAL_S = 3600  # Prüfintervall für veraltete unpaired Seeds

    def __init__(self, db: Callable, cfg: dict):
        self._db = db
        self._seed_ttl_days = int(cfg.get("seed_ttl_days", 7))
        self._lock = threading.Lock()
        threading.Thread(
            target=self._cleanup_loop, daemon=True, name="hannah-roommanager-cleanup"
        ).start()

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
        with self._lock:
            db = self._db()
            for room_id, display_name in rooms.items():
                existing = Room.get(db, room_id=room_id)
                if existing:
                    existing.update(display_name=display_name)
                else:
                    Room.create(db, room_id=room_id, display_name=display_name)
            existing_room_ids = {r.room_id for r in Room.select(db).all()}
            vanished = existing_room_ids - set(rooms.keys())
            for room_id in vanished:
                sats = Satellite.select(db).where(room_id=room_id).all()
                orphaned.extend((s.device_id, room_id) for s in sats)
                for s in sats:
                    s.update(room_id=None)
                room = Room.get(db, room_id=room_id)
                if room:
                    room.delete()
        log.debug(f"RoomManager: {len(rooms)} Räume synchronisiert")
        if vanished:
            log.info(f"RoomManager: {len(vanished)} Raum/Räume entfernt, {len(orphaned)} Satellit(en) verwaist: {orphaned}")
        return orphaned

    def get_rooms(self) -> list[dict]:
        rows = Room.select(self._db()).order_by("display_name").all()
        return [{"room_id": r.room_id, "display_name": r.display_name} for r in rows]

    # ------------------------------------------------------------------
    # Gruppen

    def get_groups(self) -> list[dict]:
        """Alle Gruppen mit ihren Räumen."""
        db = self._db()
        groups = Group.select(db).order_by("display_name").all()
        result = []
        for g in groups:
            room_rows = Room.select(db).join(
                "group_rooms gr", on="gr.room_id = rooms.room_id"
            ).where("gr.group_id = ?", g.group_id).order_by("rooms.display_name").all()
            result.append({
                "group_id": g.group_id,
                "display_name": g.display_name,
                "rooms": [{"room_id": r.room_id, "display_name": r.display_name} for r in room_rows],
            })
        return result

    def get_group(self, group_id: str) -> Optional[dict]:
        groups = self.get_groups()
        return next((g for g in groups if g["group_id"] == group_id), None)

    def create_group(self, group_id: str, display_name: str) -> bool:
        """Legt eine neue Gruppe an. Gibt False zurück wenn die ID bereits existiert."""
        try:
            Group.create(self._db(), group_id=group_id, display_name=display_name)
            log.info(f"RoomManager: Gruppe '{group_id}' angelegt")
            return True
        except sqlite3.IntegrityError:
            return False

    def update_group(self, group_id: str, display_name: str) -> bool:
        group = Group.get(self._db(), group_id=group_id)
        if not group:
            return False
        group.update(display_name=display_name)
        return True

    def delete_group(self, group_id: str) -> bool:
        group = Group.get(self._db(), group_id=group_id)
        if not group:
            return False
        group.delete()
        log.info(f"RoomManager: Gruppe '{group_id}' gelöscht")
        return True

    def set_group_rooms(self, group_id: str, room_ids: list[str]) -> None:
        """Setzt die Räume einer Gruppe (ersetzt vorhandene Einträge komplett).
        group_rooms ist eine reine n:n-Pivot-Tabelle ohne eigenes Model."""
        db = self._db()
        with self._lock:
            db.execute("DELETE FROM group_rooms WHERE group_id = ?", (group_id,))
            for room_id in room_ids:
                db.execute(
                    "INSERT OR IGNORE INTO group_rooms (group_id, room_id) VALUES (?, ?)",
                    (group_id, room_id),
                )
            db.commit()
        log.debug(f"RoomManager: Gruppe '{group_id}' → {len(room_ids)} Räume gesetzt")

    def get_group_room_ids(self, group_id: str) -> list[str]:
        rows = self._db().execute(
            "SELECT room_id FROM group_rooms WHERE group_id = ?", (group_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def resolve_group(self, group_id: str) -> list[str]:
        """Gibt alle room_ids einer Gruppe zurück."""
        return self.get_group_room_ids(group_id)

    def get_group_room_id_map(self) -> dict[str, list[str]]:
        """Gibt {group_id: [room_id, ...]} für alle Gruppen zurück (eine DB-Query)."""
        rows = self._db().execute(
            "SELECT group_id, room_id FROM group_rooms ORDER BY group_id"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for group_id, room_id in rows:
            result.setdefault(group_id, []).append(room_id)
        return result

    # ------------------------------------------------------------------
    # Satelliten

    def provision_satellite(self, seed: str, display_name: str, room_id: Optional[str]) -> bool:
        """Pre-registers a satellite before flash. seed is a one-time pairing token,
        used as the device_id placeholder until pair_satellite() renames it."""
        try:
            db = self._db()
            existing = Satellite.get(db, device_id=seed)
            if existing:
                existing.update(seed=seed, display_name=display_name, room_id=room_id)
            else:
                Satellite.create(db, device_id=seed, seed=seed, display_name=display_name, room_id=room_id)
            log.info("RoomManager: provisioned satellite seed=%s name=%s", seed[:8], display_name)
            return True
        except Exception as e:
            log.error("RoomManager: provision_satellite failed: %s", e)
            return False

    def pair_satellite(self, device_id: str, seed: str) -> bool:
        """Links a device_id (eFuse MAC) to a pre-provisioned seed entry.

        Looks up the seed, renames the record's device_id to the hardware device_id,
        and clears the seed. Returns True if pairing succeeded, False if seed not found.

        device_id is the PRIMARY KEY here, which BaseModel.update() never touches
        (it always WHEREs on the current PK value) — the rename has to go through
        raw SQL rather than the model layer.
        """
        db = self._db()
        with self._lock:
            row = db.execute(
                "SELECT device_id FROM satellites WHERE seed = ?", (seed,)
            ).fetchone()
            if row is None:
                return False
            old_device_id = row[0]
            now = _now_sql()
            if old_device_id != device_id:
                try:
                    db.execute(
                        "UPDATE satellites SET device_id=?, seed=NULL, paired_at=? WHERE seed=?",
                        (device_id, now, seed),
                    )
                except sqlite3.IntegrityError:
                    db.execute("DELETE FROM satellites WHERE seed = ?", (seed,))
                    db.execute(
                        "UPDATE satellites SET seed=NULL, paired_at=? WHERE device_id=?",
                        (now, device_id),
                    )
            else:
                db.execute(
                    "UPDATE satellites SET seed=NULL, paired_at=? WHERE seed=?",
                    (now, seed),
                )
            db.commit()
        log.info("RoomManager: paired device_id=%s", device_id)
        return True

    def resolve_satellite_name(self, device_id: str) -> Optional[str]:
        """Return the provisioned display_name for a satellite, or None if not set."""
        sat = Satellite.get(self._db(), device_id=device_id)
        return sat.display_name if sat and sat.display_name else None

    def upsert_satellite(self, device_id: str) -> None:
        db = self._db()
        now = _now_sql()
        with self._lock:
            sat = Satellite.get(db, device_id=device_id)
            if sat:
                sat.update(last_seen=now)
            else:
                Satellite.create(db, device_id=device_id, last_seen=now)

    def set_satellite_room(self, device_id: str, room_id: Optional[str]) -> bool:
        sat = Satellite.get(self._db(), device_id=device_id)
        if not sat:
            return False
        sat.update(room_id=room_id)
        return True

    def set_satellite_display_name(self, device_id: str, display_name: str) -> bool:
        sat = Satellite.get(self._db(), device_id=device_id)
        if not sat:
            return False
        sat.update(display_name=display_name)
        return True

    def get_satellite_room_map(self) -> dict[str, str]:
        """Gibt {device_id: room_id} für alle Satelliten mit DB-Raum-Zuweisung zurück."""
        rows = Satellite.select(self._db()).where("room_id IS NOT NULL").all()
        return {s.device_id: s.room_id for s in rows}

    def get_satellite_room(self, device_id: str) -> Optional[str]:
        """Gibt die zugewiesene room_id zurück oder None."""
        sat = Satellite.get(self._db(), device_id=device_id)
        return sat.room_id if sat else None

    def get_satellites(self) -> list[dict]:
        db = self._db()
        sats = Satellite.select(db).order_by("device_id").all()
        room_names = {r.room_id: r.display_name for r in Room.select(db).all()}
        return [
            {
                "device_id": s.device_id,
                "display_name": s.display_name,
                "room_id": s.room_id,
                "last_seen": s.last_seen,
                "room_display_name": room_names.get(s.room_id),
            }
            for s in sats
        ]

    def get_satellite(self, device_id: str) -> Optional[dict]:
        sat = Satellite.get(self._db(), device_id=device_id)
        if not sat:
            return None
        return {"device_id": sat.device_id, "display_name": sat.display_name, "room_id": sat.room_id}

    def delete_satellite(self, device_id: str) -> bool:
        sat = Satellite.get(self._db(), device_id=device_id)
        if not sat:
            return False
        sat.delete()
        log.info(f"RoomManager: Satellit '{device_id}' gelöscht")
        return True

    def cleanup_stale_seeds(self) -> int:
        """Löscht provisionierte, aber nie gepairte Satelliten (seed gesetzt) älter als seed_ttl_days."""
        stale = Satellite.select(self._db()).where(
            "seed IS NOT NULL AND created_at < datetime('now', ?)",
            f"-{self._seed_ttl_days} days",
        ).all()
        with self._lock:
            for s in stale:
                s.delete()
        if stale:
            log.info(
                "RoomManager: %d veraltete unpaired Seed(s) gelöscht (>%dd)",
                len(stale), self._seed_ttl_days,
            )
        return len(stale)

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(self._CLEANUP_INTERVAL_S)
            try:
                self.cleanup_stale_seeds()
            except Exception as e:
                log.error("RoomManager: cleanup_stale_seeds fehlgeschlagen: %s", e)
