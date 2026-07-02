"""
Hannah BLE-Tag Registry

Verwaltet BLE-Tags (mac_address/label/optionaler User-Owner) als eigenes DB-Modell
statt als JSON-Blob im generischen Settings-System (#115). CRUD fürs Admin-UI;
main.py baut daraus beim Start die Tag-Liste für BleLocationEngine.
"""
import sqlite3
from typing import Callable, Optional

from hannah.models.ble_tag import BleTag as BleTagModel


class BleTagManager:
    def __init__(self, db: Callable):
        self._db = db

    def get_tag_records(self) -> list[dict]:
        return [t.to_dict() for t in BleTagModel.select(self._db()).all()]

    def create_tag(self, mac_address: str, label: str, user_id: Optional[int] = None) -> Optional[dict]:
        """Legt einen neuen BLE-Tag an. Gibt None zurück wenn die MAC bereits existiert."""
        try:
            t = BleTagModel.create(
                self._db(), mac_address=mac_address.lower(), label=label, user_id=user_id or None
            )
        except sqlite3.IntegrityError:
            return None
        return t.to_dict()

    def update_tag(self, id: int, mac_address: str, label: str, user_id: Optional[int]) -> bool:
        t = BleTagModel.get(self._db(), id=id)
        if not t:
            return False
        t.update(mac_address=mac_address.lower(), label=label, user_id=user_id or None)
        return True

    def delete_tag(self, id: int) -> bool:
        t = BleTagModel.get(self._db(), id=id)
        if not t:
            return False
        t.delete()
        return True
