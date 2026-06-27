"""
Hannah Settings Manager

Verwaltet, über hannah.models, Persistenz für konfigurierbare Werte, die aus
config.yaml in die DB gewandert sind (ble.tags, cars, nlu.*, llm.system_prompt,
iobroker.state_names). Zwei Tabellen:
  - settings_category: hierarchisch (self-referencing parent), name = voller
    Punkt-Pfad (z.B. "ble.tags")
  - settings: Wert als JSON-Text, gehört zu genau einer Kategorie
"""
import sqlite3
from typing import Callable, Optional

from hannah.models.settings_category import SettingsCategory
from hannah.models.setting import Setting


class SettingsManager:
    def __init__(self, db: Callable):
        self._db = db

    def get_categories(self) -> list[dict]:
        return [c.to_dict() for c in SettingsCategory.select(self._db()).all()]

    def get_settings(self) -> list[dict]:
        return [s.to_dict() for s in Setting.select(self._db()).all()]

    def get_category_id(self, path: str) -> Optional[int]:
        cat = SettingsCategory.get(self._db(), name=path)
        return cat.id if cat else None

    def ensure_category(self, path: str) -> int:
        """Get-or-create für eine Kategorie; legt fehlende Ahnen-Kategorien entlang
        des Punkt-Pfads an (z.B. "ble.tags" legt zuerst "ble" an, falls nötig)."""
        db = self._db()
        existing = SettingsCategory.get(db, name=path)
        if existing:
            return existing.id
        parent_id = None
        if "." in path:
            parent_id = self.ensure_category(path.rsplit(".", 1)[0])
        return SettingsCategory.create(db, name=path, parent=parent_id).id

    def create_setting(self, category_id: int, name: str, value) -> Optional[dict]:
        """Legt ein neues Setting an. Gibt None zurück wenn der Name in dieser
        Kategorie bereits existiert."""
        try:
            s = Setting.create(self._db(), category=category_id, name=name, value=value)
        except sqlite3.IntegrityError:
            return None
        return s.to_dict()

    def update_setting_value(self, setting_id: int, value) -> bool:
        s = Setting.get(self._db(), id=setting_id)
        if not s:
            return False
        s.update(value=value)
        return True

    def delete_setting(self, setting_id: int) -> bool:
        s = Setting.get(self._db(), id=setting_id)
        if not s:
            return False
        s.delete()
        return True

    def get_settings_dict(self, category_path: str) -> dict:
        """Rekonstruiert {setting_name: value} für eine Kategorie — für main.py's
        Adapter-Funktionen, die die Legacy-cfg-Shape für NLU/CarTracker/etc. bauen."""
        cat_id = self.get_category_id(category_path)
        if cat_id is None:
            return {}
        return {s["name"]: s["value"] for s in self.get_settings() if s["category"] == cat_id}
