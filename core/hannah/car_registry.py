"""
Hannah Car Registry

Verwaltet konfigurierte Autos (topic_prefix/home_address + Owner-Liste) als eigenes
DB-Modell + n:n-Pivot-Tabelle "user_to_car" statt als JSON-Blob im generischen
Settings-System (#115). CRUD fürs Admin-UI.

car_tracker.py (Live-MQTT-Tracking) bleibt unverändert und kennt weiterhin nur
Roomie-IDs (NLU/Residents-Welt), keine Hannah-User-IDs — get_tracker_configs()
übersetzt die hier gespeicherten Owner-User-IDs beim Start dafür via
resolve_roomie_id (siehe main.py's _resolve_roomie_id).
"""
import sqlite3
from typing import Callable, Optional

from hannah.models.car import Car as CarModel


class CarRegistry:
    def __init__(self, db: Callable):
        self._db = db

    def _owner_ids(self, db, car_id: int) -> list[int]:
        rows = db.execute(
            "SELECT user_id FROM user_to_car WHERE car_id = ? ORDER BY user_id", (car_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def _set_owners(self, db, car_id: int, owner_user_ids: list[int]) -> None:
        db.execute("DELETE FROM user_to_car WHERE car_id = ?", (car_id,))
        for uid in owner_user_ids:
            db.execute("INSERT OR IGNORE INTO user_to_car (user_id, car_id) VALUES (?, ?)", (uid, car_id))

    def get_car_records(self) -> list[dict]:
        db = self._db()
        records = []
        for c in CarModel.select(db).all():
            d = c.to_dict()
            d["owner_user_ids"] = self._owner_ids(db, c.id)
            records.append(d)
        return records

    def create_car(self, car_name: str, topic_prefix: str, home_address: str, owner_user_ids: list[int]) -> Optional[dict]:
        """Legt ein neues Auto an. Gibt None zurück wenn topic_prefix bereits existiert."""
        db = self._db()
        try:
            c = CarModel.create(db, name=car_name, topic_prefix=topic_prefix, home_address=home_address)
        except sqlite3.IntegrityError:
            return None
        self._set_owners(db, c.id, owner_user_ids)
        db.commit()
        d = c.to_dict()
        d["owner_user_ids"] = owner_user_ids
        return d

    def update_car(self, id: int, car_name: str, topic_prefix: str, home_address: str, owner_user_ids: list[int]) -> bool:
        db = self._db()
        c = CarModel.get(db, id=id)
        if not c:
            return False
        c.update(name=car_name, topic_prefix=topic_prefix, home_address=home_address)
        self._set_owners(db, id, owner_user_ids)
        db.commit()
        return True

    def delete_car(self, id: int) -> bool:
        c = CarModel.get(self._db(), id=id)
        if not c:
            return False
        c.delete()  # ON DELETE CASCADE räumt user_to_car mit auf
        return True

    def get_tracker_configs(self, resolve_roomie_id: Callable[[int], str]) -> list[dict]:
        """Baut die cfg-Dicts, die CarTracker erwartet (topic_prefix/home_address/owner_roomies).
        Leere Liste wenn keine Autos angelegt sind — main.py fällt dann auf cfg.get("cars")/
        cfg["car"] zurück (Installationen, die noch nie migriert wurden)."""
        records = self.get_car_records()
        configs = []
        for r in records:
            owner_roomies = [rid for uid in r["owner_user_ids"] if (rid := resolve_roomie_id(uid))]
            configs.append({
                "topic_prefix": r["topic_prefix"],
                "home_address": r.get("home_address") or "",
                "owner_roomies": owner_roomies,
            })
        return configs
