"""
Hannah Web UI

Einfache Flask-App für Raum- und Gruppen-Verwaltung.
Wird als Daemon-Thread in main.py gestartet.
"""
import logging
import os
import re
from typing import Callable

from flask import Flask, redirect, render_template, request, url_for

from hannah.room_manager import RoomManager

log = logging.getLogger(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_TEMPLATES = os.path.join(os.path.dirname(__file__), "webui_templates")


def _slugify(s: str) -> str:
    """Einfacher Slug: Kleinbuchstaben, Leerzeichen → Bindestrich, Sonderzeichen entfernen."""
    s = s.lower().strip()
    s = re.sub(r"[äöü]", lambda m: {"ä": "ae", "ö": "oe", "ü": "ue"}[m.group()], s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def create_app(
    room_manager: RoomManager,
    get_connected_satellites: Callable[[], dict[str, str]],
) -> Flask:
    app = Flask(__name__, template_folder=_TEMPLATES)
    app.secret_key = os.urandom(24)

    @app.route("/")
    def index():
        return redirect(url_for("rooms"))

    # ── Räume ──────────────────────────────────────────────────────────────────

    @app.route("/rooms")
    def rooms():
        all_rooms = room_manager.get_rooms()
        all_groups = room_manager.get_groups()
        room_groups: dict[str, list[str]] = {r["room_id"]: [] for r in all_rooms}
        for g in all_groups:
            for r in g["rooms"]:
                if r["room_id"] in room_groups:
                    room_groups[r["room_id"]].append(g["display_name"])
        return render_template("rooms.html", rooms=all_rooms, room_groups=room_groups)

    # ── Gruppen ────────────────────────────────────────────────────────────────

    @app.route("/groups")
    def groups():
        return render_template(
            "groups.html",
            groups=room_manager.get_groups(),
            rooms=room_manager.get_rooms(),
        )

    @app.route("/groups/create", methods=["POST"])
    def create_group():
        display_name = request.form.get("display_name", "").strip()
        if display_name:
            group_id = _slugify(display_name)
            if not room_manager.create_group(group_id, display_name):
                log.warning(f"Gruppe '{group_id}' existiert bereits")
        return redirect(url_for("groups"))

    @app.route("/groups/<group_id>/edit")
    def edit_group(group_id: str):
        group = room_manager.get_group(group_id)
        if group is None:
            return redirect(url_for("groups"))
        return render_template(
            "group_edit.html",
            group=group,
            rooms=room_manager.get_rooms(),
            selected_room_ids=room_manager.get_group_room_ids(group_id),
        )

    @app.route("/groups/<group_id>/edit", methods=["POST"])
    def save_group(group_id: str):
        display_name = request.form.get("display_name", "").strip()
        room_ids = request.form.getlist("room_ids")
        if display_name:
            room_manager.update_group(group_id, display_name)
        room_manager.set_group_rooms(group_id, room_ids)
        return redirect(url_for("groups"))

    @app.route("/groups/<group_id>/delete", methods=["POST"])
    def delete_group(group_id: str):
        room_manager.delete_group(group_id)
        return redirect(url_for("groups"))

    # ── Satelliten ─────────────────────────────────────────────────────────────

    @app.route("/satellites")
    def satellites():
        connected = get_connected_satellites()
        db_satellites = {s["device_id"]: s for s in room_manager.get_satellites()}
        # Aktuell verbundene Satelliten die noch nicht in der DB sind eintragen
        for device_id in connected:
            if device_id not in db_satellites:
                room_manager.upsert_satellite(device_id)
        # Kombinierten Status aufbauen
        all_sats = []
        seen = set()
        for device_id, sat in db_satellites.items():
            seen.add(device_id)
            all_sats.append({**sat, "connected": device_id in connected,
                             "connected_room": connected.get(device_id, "")})
        for device_id, room in connected.items():
            if device_id not in seen:
                all_sats.append({
                    "device_id": device_id,
                    "display_name": None,
                    "room_id": None,
                    "room_display_name": None,
                    "last_seen": None,
                    "connected": True,
                    "connected_room": room,
                })
        all_sats.sort(key=lambda s: s["device_id"])
        return render_template(
            "satellites.html",
            satellites=all_sats,
            rooms=room_manager.get_rooms(),
        )

    @app.route("/satellites/<device_id>/room", methods=["POST"])
    def set_satellite_room(device_id: str):
        room_id = request.form.get("room_id") or None
        room_manager.upsert_satellite(device_id)
        room_manager.set_satellite_room(device_id, room_id)
        return redirect(url_for("satellites"))

    @app.route("/satellites/<device_id>/name", methods=["POST"])
    def set_satellite_name(device_id: str):
        display_name = request.form.get("display_name", "").strip()
        room_manager.upsert_satellite(device_id)
        if display_name:
            room_manager.set_satellite_display_name(device_id, display_name)
        return redirect(url_for("satellites"))

    return app
