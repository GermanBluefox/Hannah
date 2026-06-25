#!/usr/bin/env python3
"""One-time migration for Issue #77: copy rooms/groups/group_rooms/satellites
from the old standalone rooms.db into hannah.db (which now owns this schema
too, see hannah.utils.db.SCHEMA). Safe to re-run — uses INSERT OR IGNORE.

Usage:
    python migrate_rooms_db.py [--rooms-db rooms.db] [--hannah-db hannah.db]
"""
import argparse
import sqlite3

TABLES = {
    "rooms": ("room_id", "display_name", "created_at"),
    "groups": ("group_id", "display_name", "created_at"),
    "group_rooms": ("group_id", "room_id"),
    "satellites": ("device_id", "seed", "display_name", "room_id", "last_seen", "paired_at", "created_at"),
}


def migrate(rooms_db_path: str, hannah_db_path: str) -> None:
    src = sqlite3.connect(rooms_db_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(hannah_db_path)
    dst.execute("PRAGMA foreign_keys=ON")

    # Reihenfolge wichtig: rooms/groups vor group_rooms/satellites (FK-Abhängigkeiten)
    for table, columns in TABLES.items():
        rows = src.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
        placeholders = ", ".join(["?"] * len(columns))
        for row in rows:
            dst.execute(
                f"INSERT OR IGNORE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[c] for c in columns),
            )
        dst.commit()
        print(f"{table}: {len(rows)} Zeile(n) übernommen")

    src.close()
    dst.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rooms-db", default="rooms.db")
    parser.add_argument("--hannah-db", default="hannah.db")
    args = parser.parse_args()
    migrate(args.rooms_db, args.hannah_db)
