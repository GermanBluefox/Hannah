#!/usr/bin/env python3
"""
Standalone launcher for the Hannah Core Web-UI (rooms/groups/satellites/users).

Builds hannah.webui.create_app() with its real RoomManager/UserManager wired
to a throwaway SQLite fixture (no MQTT/UDP/gRPC/STT/TTS/ioBroker needed — the
webui factory only depends on RoomManager + UserManager + two callables).
"""
import argparse
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CORE_DIR = os.path.join(REPO_ROOT, "core")
sys.path.insert(0, CORE_DIR)


def build_app(data_dir: str):
    os.environ["DB_PATH"] = os.path.join(data_dir, "hannah.db")
    from hannah.utils.db import init_db, get_db
    from hannah.room_manager import RoomManager
    from hannah.user_manager import UserManager
    from hannah.webui import create_app
    from hannah.residents import Roomie

    init_db()

    room_manager = RoomManager({"db_path": os.path.join(data_dir, "rooms.db")})
    room_manager.sync_rooms({"kueche": "Küche", "wohnzimmer": "Wohnzimmer", "bad": "Bad"})
    room_manager.create_group("erdgeschoss", "Erdgeschoss")
    room_manager.set_group_rooms("erdgeschoss", ["kueche", "wohnzimmer"])
    room_manager.upsert_satellite("kueche-esp")
    room_manager.set_satellite_room("kueche-esp", "kueche")
    room_manager.set_satellite_display_name("kueche-esp", "Küchen-Satellit")

    user_manager = UserManager(get_db)
    leonie = user_manager.create_user(
        "leonie", "fixture-hash", email="leonie@example.com", display_name="Leonie", type="roomie"
    )
    leonie.link_account(
        "residents", "leonie_roomie",
        provider_payload={"resident_type": "roomie", "roomie_id": "leonie"},
    )
    user_manager.create_user(
        "rene", "fixture-hash", email="rene@example.com", display_name="René", type="roomie"
    )

    fake_residents = [Roomie("leonie", "Leonie"), Roomie("rene", "René"), Roomie("gast1", "Gast")]

    return create_app(
        room_manager,
        get_connected_satellites=lambda: {"kueche-esp": "kueche"},
        notify_satellite_deleted=lambda device_id, room_id: True,
        user_manager=user_manager,
        get_residents=lambda: fake_residents,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5151)
    parser.add_argument("--data-dir", default=None, help="reuse an existing fixture dir instead of a fresh tmp one")
    args = parser.parse_args()

    data_dir = args.data_dir or tempfile.mkdtemp(prefix="hannah-webui-")
    os.makedirs(data_dir, exist_ok=True)
    app = build_app(data_dir)
    print(f"hannah webui: data-dir={data_dir} http://127.0.0.1:{args.port}/")
    app.run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
