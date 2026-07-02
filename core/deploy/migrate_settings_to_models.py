#!/usr/bin/env python3
"""One-time migration for Issue #115: move ble.tags/cars out of the generic Settings
system (settings_category/settings, populated via migrate_config_settings.py) into
their own tables (ble_tags, cars, user_to_car — see hannah.utils.db.SCHEMA).

ble.tags rows store {"mac": ..., "username": ...} — username is resolved to a Hannah
users.id (users table). cars rows store {"topic_prefix": ..., "home_address": ...,
"owner_roomies": [...]} — each roomie_id is resolved to a Hannah users.id via its
"residents" linked_account (external_id "<roomie_id>_roomie"), same lookup main.py's
_resolve_roomie_id does in reverse. Roomie IDs without a linked Hannah user are skipped
(logged) rather than failing the whole migration.

Safe to re-run — uses INSERT OR IGNORE (matched by ble_tags.mac_address /
cars.topic_prefix / user_to_car's composite PK). Migrated settings/settings_category
rows for "ble.tags"/"cars" are deleted afterwards since they're superseded; nlu/llm/
iobroker settings are untouched.

Usage:
    python migrate_settings_to_models.py [--hannah-db hannah.db]
"""
import argparse
import json
import sqlite3


def _category_id(db: sqlite3.Connection, name: str) -> int | None:
    row = db.execute("SELECT id FROM settings_category WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _settings_in_category(db: sqlite3.Connection, category_id: int) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT id, name, value FROM settings WHERE category = ?", (category_id,)
    ).fetchall()


def _user_id_by_username(db: sqlite3.Connection, username: str) -> int | None:
    row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return row[0] if row else None


def _user_id_by_roomie_id(db: sqlite3.Connection, roomie_id: str) -> int | None:
    row = db.execute(
        "SELECT user_id FROM linked_accounts WHERE provider = 'residents' AND external_id = ?",
        (f"{roomie_id}_roomie",),
    ).fetchone()
    return row[0] if row else None


def migrate_ble_tags(db: sqlite3.Connection) -> int:
    cat_id = _category_id(db, "ble.tags")
    if cat_id is None:
        return 0
    count = 0
    for row in _settings_in_category(db, cat_id):
        value = json.loads(row["value"])
        mac = (value.get("mac") or "").lower()
        if not mac:
            continue
        label = row["name"]
        username = value.get("username")
        user_id = _user_id_by_username(db, username) if username else None
        if username and user_id is None:
            print(f"  ble.tags: '{label}' verweist auf unbekannten User '{username}' — user_id bleibt leer")
        cur = db.execute(
            "INSERT OR IGNORE INTO ble_tags (mac_address, label, user_id) VALUES (?, ?, ?)",
            (mac, label, user_id),
        )
        count += cur.rowcount
    db.commit()
    _delete_category(db, "ble.tags")
    return count


def migrate_cars(db: sqlite3.Connection) -> int:
    cat_id = _category_id(db, "cars")
    if cat_id is None:
        return 0
    count = 0
    for row in _settings_in_category(db, cat_id):
        value = json.loads(row["value"])
        topic_prefix = value.get("topic_prefix", "")
        if not topic_prefix:
            continue
        cur = db.execute(
            "INSERT OR IGNORE INTO cars (topic_prefix, home_address) VALUES (?, ?)",
            (topic_prefix, value.get("home_address", "")),
        )
        if cur.rowcount == 0:
            continue
        count += 1
        car_id = cur.lastrowid
        for roomie_id in value.get("owner_roomies") or []:
            user_id = _user_id_by_roomie_id(db, roomie_id)
            if user_id is None:
                print(f"  cars: '{topic_prefix}' verweist auf unverlinkte Roomie-ID '{roomie_id}' — Owner wird übersprungen")
                continue
            db.execute(
                "INSERT OR IGNORE INTO user_to_car (user_id, car_id) VALUES (?, ?)", (user_id, car_id)
            )
    db.commit()
    _delete_category(db, "cars")
    return count


def _delete_category(db: sqlite3.Connection, name: str) -> None:
    """Löscht die migrierte Kategorie samt ihrer Settings (ON DELETE CASCADE)."""
    db.execute("DELETE FROM settings_category WHERE name = ?", (name,))
    db.commit()


def migrate(hannah_db_path: str) -> None:
    db = sqlite3.connect(hannah_db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    print(f"ble.tags → ble_tags: {migrate_ble_tags(db)} Zeile(n) übernommen")
    print(f"cars → cars/user_to_car: {migrate_cars(db)} Zeile(n) übernommen")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hannah-db", default="hannah.db")
    args = parser.parse_args()
    migrate(args.hannah_db)
