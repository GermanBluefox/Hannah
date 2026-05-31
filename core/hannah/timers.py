import datetime
import json
import logging
import sqlite3
import threading
import uuid as _uuid
from typing import Callable, Optional

log = logging.getLogger(__name__)


def format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} Stunde{'n' if h > 1 else ''}")
    if m:
        parts.append(f"{m} Minute{'n' if m > 1 else ''}")
    if s:
        parts.append(f"{s} Sekunde{'n' if s > 1 else ''}")
    return " und ".join(parts) if parts else "0 Sekunden"


class TimerManager:
    def __init__(self):
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def set(self, device: str, seconds: int, on_fire: Callable[[str], None]) -> None:
        with self._lock:
            existing = self._timers.pop(device, None)
            if existing:
                existing.cancel()
                log.info(f"[timer] Bestehender Timer für '{device}' ersetzt.")
            t = threading.Timer(seconds, self._fire, args=(device, on_fire))
            t.daemon = True
            t.start()
            self._timers[device] = t
        log.info(f"[timer] Timer für '{device}': {seconds}s ({format_duration(seconds)})")

    def cancel(self, device: str) -> bool:
        with self._lock:
            t = self._timers.pop(device, None)
            if t:
                t.cancel()
                log.info(f"[timer] Timer für '{device}' abgebrochen.")
                return True
            return False

    def active(self, device: str) -> bool:
        with self._lock:
            return device in self._timers

    def _fire(self, device: str, on_fire: Callable[[str], None]) -> None:
        with self._lock:
            self._timers.pop(device, None)
        log.info(f"[timer] Timer für '{device}' abgelaufen.")
        on_fire(device)


def next_alarm_dt(time_str: str) -> datetime.datetime:
    """Gibt das nächste datetime-Objekt für 'HH:MM' zurück (heute oder morgen)."""
    h, m = map(int, time_str.split(":"))
    now = datetime.datetime.now()
    dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if dt <= now:
        dt += datetime.timedelta(days=1)
    return dt


class AlarmManager:
    """Persistenter Wecker-Manager: feuert auf einem konfigurierten Satelliten."""

    def __init__(self, persist_path: str, on_fire: Callable[[str, str], None]):
        """
        persist_path: JSON-Datei für Persistenz über Neustarts.
        on_fire(alarm_id, target_device): Callback beim Auslösen.
        """
        self._path = persist_path
        self._on_fire = on_fire
        self._alarms: dict[str, dict] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._load()

    def set(self, target: str, time_str: str, set_by: str) -> str:
        """Setzt Wecker für nächste Uhrzeit 'HH:MM'. Gibt alarm_id zurück."""
        dt = next_alarm_dt(time_str)
        alarm_id = str(_uuid.uuid4())[:8]
        data = {"target": target, "trigger_time": dt.isoformat(), "set_by": set_by}
        with self._lock:
            self._alarms[alarm_id] = data
            self._save()
            self._schedule(alarm_id, dt)
        log.info(f"[alarm] Wecker '{alarm_id}' für '{target}' um {dt.strftime('%H:%M')} gesetzt.")
        return alarm_id

    def cancel(self, alarm_id: str) -> bool:
        with self._lock:
            t = self._timers.pop(alarm_id, None)
            if t:
                t.cancel()
            removed = self._alarms.pop(alarm_id, None)
            if removed:
                self._save()
                log.info(f"[alarm] Wecker '{alarm_id}' abgebrochen.")
                return True
        return False

    def _schedule(self, alarm_id: str, dt: datetime.datetime) -> None:
        delay = max(0.0, (dt - datetime.datetime.now()).total_seconds())
        t = threading.Timer(delay, self._fire, args=(alarm_id,))
        t.daemon = True
        t.start()
        self._timers[alarm_id] = t

    def _fire(self, alarm_id: str) -> None:
        with self._lock:
            data = self._alarms.pop(alarm_id, None)
            self._timers.pop(alarm_id, None)
            if data:
                self._save()
        if data:
            log.info(f"[alarm] Wecker '{alarm_id}' ausgelöst → '{data['target']}'")
            self._on_fire(alarm_id, data["target"])

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                stored: dict = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        now = datetime.datetime.now()
        for alarm_id, data in stored.items():
            try:
                dt = datetime.datetime.fromisoformat(data["trigger_time"])
            except (KeyError, ValueError):
                continue
            if dt <= now:
                log.info(f"[alarm] Wecker '{alarm_id}' übersprungen — liegt in der Vergangenheit.")
                continue
            self._alarms[alarm_id] = data
            self._schedule(alarm_id, dt)
            log.info(f"[alarm] Wecker '{alarm_id}' nach Neustart eingeplant: {dt.strftime('%H:%M')} → '{data['target']}'")

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._alarms, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"[alarm] Speichern fehlgeschlagen: {e}")


class HannahTimerStore:
    """SQLite-backed store for timers managed by the external Hannah Timer Service.

    Hannah owns the metadata (label, room, roomie_id); the Timer Service only
    stores timer_id + fire_at. On TimerFired, Hannah looks up by timer_id here.
    """

    def __init__(self, db_path: str = "timers.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS timers (
                    timer_id  TEXT PRIMARY KEY,
                    label     TEXT NOT NULL,
                    fire_at   INTEGER NOT NULL,
                    room      TEXT NOT NULL,
                    roomie_id TEXT
                )
            """)
            conn.commit()

    def set(self, timer_id: str, label: str, fire_at: int,
            room: str, roomie_id: Optional[str] = None) -> None:
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO timers"
                    " (timer_id, label, fire_at, room, roomie_id) VALUES (?, ?, ?, ?, ?)",
                    (timer_id, label, fire_at, room, roomie_id),
                )
                conn.commit()

    def get(self, timer_id: str) -> Optional[dict]:
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT timer_id, label, fire_at, room, roomie_id"
                    " FROM timers WHERE timer_id = ?",
                    (timer_id,),
                ).fetchone()
        if not row:
            return None
        return {"timer_id": row[0], "label": row[1], "fire_at": row[2],
                "room": row[3], "roomie_id": row[4]}

    def remove(self, timer_id: str) -> bool:
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute("DELETE FROM timers WHERE timer_id = ?", (timer_id,))
                conn.commit()
                return cur.rowcount > 0

    def get_all(self) -> list[dict]:
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT timer_id, label, fire_at, room, roomie_id"
                    " FROM timers ORDER BY fire_at"
                ).fetchall()
        return [{"timer_id": r[0], "label": r[1], "fire_at": r[2],
                 "room": r[3], "roomie_id": r[4]} for r in rows]
