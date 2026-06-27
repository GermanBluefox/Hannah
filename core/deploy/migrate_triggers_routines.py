#!/usr/bin/env python3
"""One-time migration for Issue #27 follow-up (#87-adjacent): copy routines/triggers
from the old routines.yaml/triggers.yaml files into hannah.db (Routine/Trigger models,
see hannah.utils.db.SCHEMA). Safe to re-run — uses INSERT OR IGNORE (matched by
routines.name / triggers.id).

Assumes hannah.db already has the "routines"/"triggers" tables (i.e. init_db() has
run at least once — they're created by Hannah Core's normal startup).

Usage:
    python migrate_triggers_routines.py [--routines-yaml routines.yaml] [--triggers-yaml triggers.yaml] [--hannah-db hannah.db]
"""
import argparse
import json
import sqlite3

import yaml


def _normalize_action(a: dict) -> dict:
    if "say" in a:
        return {"say": a["say"], "room": a.get("room", "all")}
    return {"topic": a["topic"], "value": str(a.get("value", "true"))}


def migrate_routines(path: str, db: sqlite3.Connection) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return 0

    count = 0
    for r in data.get("routines", []):
        actions = [_normalize_action(a) for a in r.get("actions", [])]
        db.execute(
            "INSERT OR IGNORE INTO routines (name, triggers, actions, reply) VALUES (?, ?, ?, ?)",
            (r["name"], json.dumps(r.get("triggers", [])), json.dumps(actions), r.get("reply", "")),
        )
        count += 1
    db.commit()
    return count


def migrate_triggers(path: str, db: sqlite3.Connection) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return 0

    count = 0
    for t in data.get("triggers", []):
        db.execute(
            'INSERT OR IGNORE INTO triggers '
            '(id, "when", cancel_when, on_response, say, ask, rephrase, room, cooldown, delay) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                t["id"],
                json.dumps(t.get("when", {})),
                json.dumps(t["cancel_when"]) if t.get("cancel_when") else None,
                json.dumps(t["on_response"]) if t.get("on_response") else None,
                t.get("say"),
                t.get("ask"),
                int(bool(t.get("rephrase", False))),
                t.get("room", "all"),
                int(t.get("cooldown", 3600)),
                str(t["for"]) if t.get("for") else None,
            ),
        )
        count += 1
    db.commit()
    return count


def migrate(routines_path: str, triggers_path: str, hannah_db_path: str) -> None:
    db = sqlite3.connect(hannah_db_path)
    db.execute("PRAGMA foreign_keys=ON")

    n = migrate_routines(routines_path, db)
    print(f"routines: {n} Zeile(n) übernommen")

    n = migrate_triggers(triggers_path, db)
    print(f"triggers: {n} Zeile(n) übernommen")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routines-yaml", default="routines.yaml")
    parser.add_argument("--triggers-yaml", default="triggers.yaml")
    parser.add_argument("--hannah-db", default="hannah.db")
    args = parser.parse_args()
    migrate(args.routines_yaml, args.triggers_yaml, args.hannah_db)
