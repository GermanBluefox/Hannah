#!/usr/bin/env python3
"""One-time migration for Issue #27 Phase 5: copy the config.yaml sections that move
into the new Settings module (ble.tags, cars, nlu.*, llm.system_prompt,
iobroker.state_names) into hannah.db (settings_category/settings tables, see
hannah.utils.db.SCHEMA). Safe to re-run - uses INSERT OR IGNORE (matched by
settings_category.name / settings.(category, name)).

Assumes hannah.db already has the "settings_category"/"settings" tables (i.e.
init_db() has run at least once - they're created by Hannah Core's normal startup).

Everything else in config.yaml (udp, web_ui, grpc, audio, mqtt/asset_server
connection data, stt/tts backend & credentials, ble.stale_timeout, iobroker.
virtual_device_prefix/feedback_timeout) stays static YAML config and is not touched.

Usage:
    python migrate_config_settings.py [--config config.yaml] [--hannah-db hannah.db]
"""
import argparse
import json
import sqlite3

import yaml


def _ensure_category(db: sqlite3.Connection, path: str) -> int:
    row = db.execute("SELECT id FROM settings_category WHERE name = ?", (path,)).fetchone()
    if row:
        return row[0]
    parent_id = _ensure_category(db, path.rsplit(".", 1)[0]) if "." in path else None
    cur = db.execute("INSERT INTO settings_category (name, parent) VALUES (?, ?)", (path, parent_id))
    db.commit()
    return cur.lastrowid


def _create_setting(db: sqlite3.Connection, category_id: int, name: str, value) -> bool:
    cur = db.execute(
        "INSERT OR IGNORE INTO settings (category, name, value) VALUES (?, ?, ?)",
        (category_id, name, json.dumps(value)),
    )
    db.commit()
    return cur.rowcount > 0


def migrate_ble_tags(cfg: dict, db: sqlite3.Connection) -> int:
    tags = cfg.get("ble", {}).get("tags", [])
    if not tags:
        return 0
    cat = _ensure_category(db, "ble.tags")
    count = 0
    for tag in tags:
        label = tag.get("label") or tag.get("mac", "")
        if not label:
            continue
        value = {"mac": tag.get("mac", ""), "username": tag.get("username")}
        if _create_setting(db, cat, label, value):
            count += 1
    return count


def migrate_cars(cfg: dict, db: sqlite3.Connection) -> int:
    cars = cfg.get("cars") or ([cfg["car"]] if cfg.get("car") else [])
    if not cars:
        return 0
    cat = _ensure_category(db, "cars")
    used_names: set[str] = set()
    count = 0
    for car in cars:
        topic_prefix = car.get("topic_prefix", "")
        base = topic_prefix.rsplit("/", 1)[-1] or "car"
        name = base
        suffix = 2
        while name in used_names:
            name = f"{base}_{suffix}"
            suffix += 1
        used_names.add(name)
        owner_roomies = car.get("owner_roomies", car.get("owner_roomie", ""))
        if not isinstance(owner_roomies, list):
            owner_roomies = [owner_roomies] if owner_roomies else []
        value = {
            "topic_prefix": topic_prefix,
            "home_address": car.get("home_address", ""),
            "owner_roomies": owner_roomies,
        }
        if _create_setting(db, cat, name, value):
            count += 1
    return count


def migrate_nlu(cfg: dict, db: sqlite3.Connection) -> int:
    nlu = cfg.get("nlu", {})
    if not nlu:
        return 0
    cat = _ensure_category(db, "nlu")
    count = 0
    for key, value in nlu.items():
        if _create_setting(db, cat, key, value):
            count += 1
    return count


def migrate_llm(cfg: dict, db: sqlite3.Connection) -> int:
    prompt = cfg.get("llm", {}).get("system_prompt")
    if not prompt:
        return 0
    cat = _ensure_category(db, "llm")
    return 1 if _create_setting(db, cat, "system_prompt", prompt) else 0


def migrate_iobroker_state_names(cfg: dict, db: sqlite3.Connection) -> int:
    state_names = cfg.get("iobroker", {}).get("state_names")
    if not state_names:
        return 0
    cat = _ensure_category(db, "iobroker")
    return 1 if _create_setting(db, cat, "state_names", state_names) else 0


def migrate(config_path: str, hannah_db_path: str) -> None:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    db = sqlite3.connect(hannah_db_path)
    db.execute("PRAGMA foreign_keys=ON")

    print(f"ble.tags: {migrate_ble_tags(cfg, db)} Zeile(n) übernommen")
    print(f"cars: {migrate_cars(cfg, db)} Zeile(n) übernommen")
    print(f"nlu: {migrate_nlu(cfg, db)} Zeile(n) übernommen")
    print(f"llm.system_prompt: {migrate_llm(cfg, db)} Zeile(n) übernommen")
    print(f"iobroker.state_names: {migrate_iobroker_state_names(cfg, db)} Zeile(n) übernommen")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--hannah-db", default="hannah.db")
    args = parser.parse_args()
    migrate(args.config, args.hannah_db)
