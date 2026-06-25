import os
import secrets
import sqlite3
import logging
from werkzeug.security import generate_password_hash

_log = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "hannah.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS "users" (
	"id"	INTEGER NOT NULL,
	"username"	TEXT NOT NULL,
	"display_name"	TEXT NOT NULL,
	"email"	TEXT NOT NULL,
	"password_hash"	TEXT NOT NULL,
	"trust_level"	NUMERIC NOT NULL DEFAULT 5,
	"mood_level"	NUMERIC NOT NULL DEFAULT 5,
	"system_messages"	INTEGER NOT NULL DEFAULT 0,
	"type"	TEXT NOT NULL,
	"is_active"	INTEGER NOT NULL DEFAULT 1,
	UNIQUE("email"),
	PRIMARY KEY("id" AUTOINCREMENT),
	UNIQUE("username")
);

CREATE TABLE IF NOT EXISTS "linked_accounts" (
	"id"	INTEGER,
	"user_id"	INTEGER,
	"provider"	TEXT NOT NULL,
	"external_id"	TEXT NOT NULL,
	"provider_payload"	TEXT,
	PRIMARY KEY("id" AUTOINCREMENT),
	UNIQUE("provider","external_id"),
	UNIQUE("user_id","provider"),
	FOREIGN KEY("user_id") REFERENCES "users"("id") ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "rooms" (
	"room_id"	TEXT NOT NULL,
	"display_name"	TEXT NOT NULL,
	"created_at"	TEXT NOT NULL DEFAULT (datetime('now')),
	PRIMARY KEY("room_id")
);

CREATE TABLE IF NOT EXISTS "groups" (
	"group_id"	TEXT NOT NULL,
	"display_name"	TEXT NOT NULL,
	"created_at"	TEXT NOT NULL DEFAULT (datetime('now')),
	PRIMARY KEY("group_id")
);

CREATE TABLE IF NOT EXISTS "group_rooms" (
	"group_id"	TEXT NOT NULL,
	"room_id"	TEXT NOT NULL,
	PRIMARY KEY("group_id","room_id"),
	FOREIGN KEY("group_id") REFERENCES "groups"("group_id") ON DELETE CASCADE,
	FOREIGN KEY("room_id") REFERENCES "rooms"("room_id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "satellites" (
	"device_id"	TEXT NOT NULL,
	"seed"	TEXT,
	"display_name"	TEXT,
	"room_id"	TEXT,
	"last_seen"	TEXT,
	"paired_at"	TEXT,
	"created_at"	TEXT NOT NULL DEFAULT (datetime('now')),
	PRIMARY KEY("device_id"),
	FOREIGN KEY("room_id") REFERENCES "rooms"("room_id")
);
"""


def get_db():
    """Frische Connection pro Aufruf — Hannah Core läuft nicht request-scoped wie Flask,
    sondern aus gRPC-Handlern/MQTT-Callbacks/Telegram, daher kein g-Caching."""
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _existing_tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _col_names(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def init_db():
    db = get_db()
    db.executescript(SCHEMA)

    # --- First-run: create admin account if no users exist ---
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        pw = secrets.token_urlsafe(16)
        db.execute(
            "INSERT INTO users (username, display_name, email, password_hash, trust_level, mood_level, system_messages, type, is_active) VALUES (?,?,?,?,?,?,?,?,?)",
            # TODO: get username from configfile
            ("hannah", "Hannah", "hannah@localhost", generate_password_hash(secrets.token_urlsafe(16)), 10, 10, 1, "roomie", 1)
        )
        db.execute(
            "INSERT INTO users (username, display_name, email, password_hash, trust_level, mood_level, system_messages, type, is_active) VALUES (?,?,?,?,?,?,?,?,?)",
            ("admin", "Admin", "admin@localhost", generate_password_hash(pw), 10, 10, 1, "roomie", 1)
        )
        db.commit()
        print(f"\n{'='*55}")
        print(f"  First-run: admin account created")
        print(f"  Username : admin")
        print(f"  Password : {pw}")
        print(f"  Please change the password after first login!")
        print(f"{'='*55}\n")
