"""
Hannah Room Manager

Verwaltet, über hannah.models, Persistenz für:
  - Räume (sync aus ioBroker)
  - Gruppen von Räumen (n:n über group_rooms — kein eigenes Model, per Join-Query)

Satelliten-Verwaltung liegt in satellite_manager.py (SatelliteManager) — sync_rooms()
greift hier weiterhin direkt auf das Satellite-Model zu, um beim Löschen eines Raums
verwaiste Satelliten auf room_id=NULL zu setzen (Querschnitts-Stelle, siehe #108).
"""
import logging
import sqlite3
import threading
from typing import Callable, Optional

from hannah.models.room import Room
from hannah.models.group import Group
from hannah.models.satellite import Satellite

log = logging.getLogger(__name__)


class RoomManager:
    def __init__(self, db: Callable):
        self._db = db
        self._lock = threading.Lock()

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
