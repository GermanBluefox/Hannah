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
from werkzeug.security import generate_password_hash

from hannah.room_manager import RoomManager

_USER_TYPES = ("roomie", "guest", "pet")

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
    notify_satellite_deleted: Callable[[str, str], bool],
    user_manager=None,
    get_residents: Callable[[], list] = lambda: [],
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
        room_display_names = {r["room_id"]: r["display_name"] for r in room_manager.get_rooms()}
        # Aktuell verbundene Satelliten die noch nicht in der DB sind eintragen
        for device_id in connected:
            if device_id not in db_satellites:
                room_manager.upsert_satellite(device_id)
        # Kombinierten Status aufbauen
        all_sats = []
        seen = set()
        for device_id, sat in db_satellites.items():
            seen.add(device_id)
            connected_room_id = connected.get(device_id)
            all_sats.append({
                **sat,
                "connected": device_id in connected,
                # Anzeigename der live gemeldeten Raum-ID, fürs Anzeigen — der eigentliche
                # Mismatch-Check vergleicht unten IDs, nicht Anzeigenamen (room_id und
                # display_name sind unterschiedliche Strings, sobald ein Raum nicht 1:1
                # gleich benannt ist wie seine ID, z.B. "leonie_schlafzimmer" vs.
                # "Leonie Schlafzimmer" — das ist kein Mismatch, nur eine andere Schreibweise)
                "connected_room": room_display_names.get(connected_room_id, connected_room_id or ""),
                "room_mismatch": device_id in connected and connected_room_id != sat.get("room_id"),
            })
        for device_id, room_id in connected.items():
            if device_id not in seen:
                all_sats.append({
                    "device_id": device_id,
                    "display_name": None,
                    "room_id": None,
                    "room_display_name": None,
                    "last_seen": None,
                    "connected": True,
                    "connected_room": room_display_names.get(room_id, room_id),
                    "room_mismatch": True,
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

    @app.route("/satellites/<device_id>/delete", methods=["POST"])
    def delete_satellite(device_id: str):
        room_id = room_manager.get_satellite_room(device_id) or ""
        room_manager.delete_satellite(device_id)
        notify_satellite_deleted(device_id, room_id)
        return redirect(url_for("satellites"))

    # ── User ───────────────────────────────────────────────────────────────────

    @app.route("/users")
    def users():
        users_view = []
        for u in user_manager.users(include_inactive=True):
            la = u.get_linked_account("residents")
            users_view.append({"user": u, "resident_link": la.provider_payload if la else None})
        return render_template("users.html", users=users_view, residents=get_residents())

    @app.route("/users/create", methods=["GET", "POST"])
    def create_user():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            email = request.form.get("email", "").strip()
            display_name = request.form.get("display_name", "").strip()
            user_type = request.form.get("type", "roomie")
            if username and password and email:
                try:
                    user_manager.create_user(
                        username, generate_password_hash(password),
                        email=email, display_name=display_name or None, type=user_type,
                    )
                    return redirect(url_for("users"))
                except ValueError as e:
                    return render_template("user_create.html", error=str(e), types=_USER_TYPES)
            return render_template("user_create.html", error="Username, Passwort und E-Mail sind Pflicht.", types=_USER_TYPES)
        return render_template("user_create.html", error=None, types=_USER_TYPES)

    @app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
    def edit_user(user_id: int):
        user = user_manager.get_user_by_id(user_id)
        if user is None:
            return redirect(url_for("users"))
        if request.method == "POST":
            user.display_name = request.form.get("display_name", "").strip() or user.username
            user.email = request.form.get("email", "").strip() or user.email
            user.type = request.form.get("type", user.type)
            user.trust_level = int(request.form.get("trust_level") or user.trust_level)
            user.is_active = 1 if request.form.get("is_active") else 0
            user.system_messages = 1 if request.form.get("system_messages") else 0
            new_password = request.form.get("password", "").strip()
            if new_password:
                user.password_hash = generate_password_hash(new_password)
            user.save()
            return redirect(url_for("users"))
        return render_template("user_edit.html", user=user, types=_USER_TYPES)

    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    def delete_user(user_id: int):
        user_manager.delete_user(user_id)
        return redirect(url_for("users"))

    @app.route("/users/<int:user_id>/link-resident", methods=["POST"])
    def link_resident(user_id: int):
        resident_id = request.form.get("resident_id", "")
        user = user_manager.get_user_by_id(user_id)
        if user and resident_id:
            roomie_id, _, resident_type = resident_id.rpartition("_")
            user.link_account(
                "residents", resident_id,
                provider_payload={"resident_type": resident_type, "roomie_id": roomie_id},
            )
        return redirect(url_for("users"))

    @app.route("/users/<int:user_id>/unlink-resident", methods=["POST"])
    def unlink_resident(user_id: int):
        user = user_manager.get_user_by_id(user_id)
        if user:
            user.unlink_account("residents")
        return redirect(url_for("users"))

    return app
