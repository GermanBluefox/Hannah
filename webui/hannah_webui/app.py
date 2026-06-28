"""
Hannah WebUI

Flask app, talks to Hannah Core exclusively via gRPC (no direct DB/file access —
Core stays the sole owner of all data, see #27).
"""
import json
import logging
import os
import re
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for

from hannah_webui.grpc_client import HannahClient

log = logging.getLogger(__name__)

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")


def _slugify(s: str) -> str:
    """Einfacher Slug: Kleinbuchstaben, Leerzeichen -> Bindestrich, Sonderzeichen entfernen."""
    s = s.lower().strip()
    s = re.sub(r"[äöü]", lambda m: {"ä": "ae", "ö": "oe", "ü": "ue"}[m.group()], s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


_ROUTINE_NEW_ACTION_ROWS = 3
_USER_TYPES = ("roomie", "guest", "pet")


def _parse_action_rows(form) -> list[dict]:
    """No-Code-Eingabe: pro Zeile entweder ein Gerät-Topic+Wert oder ein Ansage-Text+Raum.
    Welche Hälfte zählt, entscheidet die "Typ"-Auswahl der Zeile — die jeweils andere
    Hälfte wird ignoriert, auch wenn versehentlich befüllt."""
    types = form.getlist("action_type")
    topics = form.getlist("action_topic")
    values = form.getlist("action_value")
    says = form.getlist("action_say")
    rooms = form.getlist("action_room")
    actions = []
    for i, action_type in enumerate(types):
        if action_type == "say":
            say = says[i].strip() if i < len(says) else ""
            if say:
                room = rooms[i].strip() if i < len(rooms) else ""
                actions.append({"say": say, "room": room or "all"})
        else:
            topic = topics[i].strip() if i < len(topics) else ""
            if topic:
                value = values[i].strip() if i < len(values) else ""
                actions.append({"topic": topic, "value": value or "true"})
    return actions


_TRIGGER_NEW_WHEN_ROWS = 2
_TRIGGER_NEW_ALSO_ROWS = 2
_TRIGGER_NEW_ACTION_ROWS = 2
_CMP_KEYS = ("value", "above", "below")


def _as_or_list(when) -> list[dict]:
    """Normalisiert 'when' auf eine Liste von Bedingungs-Dicts — Pendant zu
    TriggerEngine._as_or_list() (core/hannah/trigger_engine.py), hier ohne Core-Import
    nachgebaut, da webui/ ausschließlich über gRPC mit Core spricht (#101)."""
    if isinstance(when, list):
        return when
    return [when] if when else []


def _as_condition_list(also_or_unless) -> tuple[list[dict], str]:
    """Liest 'also'/'unless' (Dict, Liste, oder {"op",  "conditions"}) auf eine
    einheitliche (Bedingungsliste, op)-Form zurück, fürs Vorausfüllen des Formulars."""
    if not also_or_unless:
        return [], "and"
    if isinstance(also_or_unless, dict) and "conditions" in also_or_unless:
        return list(also_or_unless.get("conditions") or []), also_or_unless.get("op", "and")
    if isinstance(also_or_unless, list):
        return also_or_unless, "and"
    return [also_or_unless], "and"


def _blank_when_row() -> dict:
    return {"type": "state", "state": "", "cmp": "value", "value": "", "time": "", "days": ""}


def _blank_state_row() -> dict:
    return {"state": "", "cmp": "value", "value": ""}


def _blank_action_row() -> dict:
    return {"type": "say", "say": "", "room": "", "state_id": "", "state_value": ""}


def _condition_to_row(cond: dict) -> dict:
    if "time" in cond:
        return {"type": "time", "state": "", "cmp": "value", "value": "",
                "time": cond.get("time", ""), "days": ",".join(cond.get("days") or [])}
    cmp = next((k for k in _CMP_KEYS if k in cond), "value")
    return {"type": "state", "state": cond.get("state", ""), "cmp": cmp,
            "value": str(cond.get(cmp, "")), "time": "", "days": ""}


def _state_condition_to_row(cond: dict) -> dict:
    cmp = next((k for k in _CMP_KEYS if k in cond), "value")
    return {"state": cond.get("state", ""), "cmp": cmp, "value": str(cond.get(cmp, ""))}


def _action_to_row(action: dict) -> dict:
    if "set_state" in action:
        set_state = action.get("set_state") or {}
        return {"type": "state", "say": "", "room": "", "state_id": set_state.get("id", ""),
                "state_value": str(set_state.get("value", ""))}
    return {"type": "say", "say": action.get("say", ""), "room": action.get("room", ""),
            "state_id": "", "state_value": ""}


def _extract_also_unless(conditions: list[dict]) -> tuple[list[dict], str, list[dict]]:
    """Liest aus den (ggf. auf jede Wenn-Bedingung dupliziert abgelegten) also/unless die
    gemeinsame 'und'/'außer wenn'-Konfiguration zurück — Inverse von _attach_also_unless(),
    fürs Vorausfüllen des Bearbeiten-Formulars. Nimmt die erste Bedingung, die jeweils
    etwas trägt (sie sind laut _attach_also_unless ohnehin identisch)."""
    also_conditions, also_op, unless_conditions = [], "and", []
    for cond in conditions:
        if not also_conditions and cond.get("also"):
            also_conditions, also_op = _as_condition_list(cond["also"])
        if not unless_conditions and cond.get("unless"):
            unless_conditions, _ = _as_condition_list(cond["unless"])
    return also_conditions, also_op, unless_conditions


def _parse_when_rows(form) -> list[dict]:
    """No-Code 'Wenn'-Zeilen (OR-verknüpft): pro Zeile per Typ-Auswahl entweder ein
    Zustand (State + Vergleich + Wert) oder eine Uhrzeit (HH:MM + optionale, kommagetrennte
    Wochentage). Genutzt für "wenn" (#101)."""
    types = form.getlist("when_type")
    states = form.getlist("when_state")
    cmps = form.getlist("when_cmp")
    values = form.getlist("when_value")
    times = form.getlist("when_time")
    days = form.getlist("when_days")
    conditions = []
    for i, row_type in enumerate(types):
        if row_type == "time":
            time_str = times[i].strip() if i < len(times) else ""
            if not time_str:
                continue
            cond = {"time": time_str}
            days_str = days[i].strip() if i < len(days) else ""
            if days_str:
                cond["days"] = [d.strip().lower() for d in days_str.split(",") if d.strip()]
            conditions.append(cond)
        else:
            state_id = states[i].strip() if i < len(states) else ""
            if not state_id:
                continue
            cmp = cmps[i].strip() if i < len(cmps) else "value"
            if cmp not in _CMP_KEYS:
                cmp = "value"
            value = values[i].strip() if i < len(values) else ""
            conditions.append({"state": state_id, cmp: value or "true"})
    return conditions


def _parse_state_condition_rows(form, prefix: str) -> list[dict]:
    """No-Code-Zustandsbedingungen (kein Uhrzeit-Typ) — gemeinsamer Zeilen-Builder für
    "und" und "außer wenn" (#101)."""
    states = form.getlist(f"{prefix}_state")
    cmps = form.getlist(f"{prefix}_cmp")
    values = form.getlist(f"{prefix}_value")
    conditions = []
    for i, raw_state in enumerate(states):
        state_id = raw_state.strip()
        if not state_id:
            continue
        cmp = cmps[i].strip() if i < len(cmps) else "value"
        if cmp not in _CMP_KEYS:
            cmp = "value"
        value = values[i].strip() if i < len(values) else ""
        conditions.append({"state": state_id, cmp: value or "true"})
    return conditions


def _parse_also(form) -> dict | list | None:
    conditions = _parse_state_condition_rows(form, "also")
    if not conditions:
        return None
    if form.get("also_op") == "or":
        return {"op": "or", "conditions": conditions}
    return conditions


def _attach_also_unless(conditions: list[dict], also, unless) -> list[dict]:
    """Hängt 'und'/'außer wenn' an jede Wenn-Bedingung — die Engine prüft sie pro
    OR-Branch (trigger_engine.py), die No-Code-UI bildet aber EINEN globalen 'und'/
    'außer wenn'-Block ab, der für alle 'wenn'-Zeilen gelten soll. 'und' gilt nur für
    Zustands-, nicht für Uhrzeit-Bedingungen (die Engine prüft 'also' nie bei
    Zeit-Triggern, siehe _check_time_triggers())."""
    result = []
    for cond in conditions:
        cond = dict(cond)
        if unless:
            cond["unless"] = unless
        if also and "state" in cond:
            cond["also"] = also
        result.append(cond)
    return result


def _parse_trigger_action_rows(form) -> list[dict]:
    """Wie _parse_action_rows, aber die Geräte-Variante setzt einen ioBroker-State direkt
    (set_state) statt ein MQTT-Topic zu publishen (#101)."""
    types = form.getlist("action_type")
    says = form.getlist("action_say")
    rooms = form.getlist("action_room")
    state_ids = form.getlist("action_state_id")
    state_values = form.getlist("action_state_value")
    actions = []
    for i, action_type in enumerate(types):
        if action_type == "say":
            say = says[i].strip() if i < len(says) else ""
            if say:
                room = rooms[i].strip() if i < len(rooms) else ""
                actions.append({"say": say, "room": room or "all"})
        else:
            state_id = state_ids[i].strip() if i < len(state_ids) else ""
            if state_id:
                value = state_values[i].strip() if i < len(state_values) else ""
                actions.append({"set_state": {"id": state_id, "value": value or "true"}})
    return actions


def create_app(hannah: HannahClient, secret_key: str = "") -> Flask:
    app = Flask(__name__, template_folder=_TEMPLATES)
    if not secret_key:
        log.warning(
            "No secret_key configured — falling back to a random one. Sessions won't "
            "survive a restart or work across multiple gunicorn workers."
        )
        secret_key = os.urandom(24)
    app.secret_key = secret_key

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            found, user = hannah.login(username, password)
            if found:
                session["user_id"] = user.id
                session["display_name"] = user.display_name or user.user_name
                return redirect(url_for("index"))
            error = "Ungültige Zugangsdaten."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        return render_template("index.html", display_name=session.get("display_name"))

    @app.route("/rooms")
    @login_required
    def rooms():
        all_rooms = hannah.get_rooms()
        all_groups = hannah.get_groups()
        room_groups: dict[str, list[str]] = {r.room_id: [] for r in all_rooms}
        for g in all_groups:
            for r in g.rooms:
                if r.room_id in room_groups:
                    room_groups[r.room_id].append(g.display_name)
        return render_template("rooms.html", rooms=all_rooms, room_groups=room_groups)

    @app.route("/groups")
    @login_required
    def groups():
        return render_template("groups.html", groups=hannah.get_groups(), rooms=hannah.get_rooms())

    @app.route("/groups/create", methods=["POST"])
    @login_required
    def create_group():
        display_name = request.form.get("display_name", "").strip()
        if display_name:
            hannah.create_group(_slugify(display_name), display_name)
        return redirect(url_for("groups"))

    @app.route("/groups/<group_id>/edit")
    @login_required
    def edit_group(group_id: str):
        group = hannah.get_group(group_id)
        if group is None:
            return redirect(url_for("groups"))
        selected_room_ids = {r.room_id for r in group.rooms}
        return render_template(
            "group_edit.html",
            group=group,
            rooms=hannah.get_rooms(),
            selected_room_ids=selected_room_ids,
        )

    @app.route("/groups/<group_id>/edit", methods=["POST"])
    @login_required
    def save_group(group_id: str):
        display_name = request.form.get("display_name", "").strip()
        room_ids = request.form.getlist("room_ids")
        if display_name:
            hannah.update_group(group_id, display_name)
        hannah.set_group_rooms(group_id, room_ids)
        return redirect(url_for("groups"))

    @app.route("/groups/<group_id>/delete", methods=["POST"])
    @login_required
    def delete_group(group_id: str):
        hannah.delete_group(group_id)
        return redirect(url_for("groups"))

    @app.route("/satellites")
    @login_required
    def satellites():
        rooms = hannah.get_rooms()
        room_display_names = {r.room_id: r.display_name for r in rooms}
        sats = hannah.get_satellites()
        sats_view = [{
            "sat": sat,
            "live_room_display": room_display_names.get(sat.room, sat.room),
        } for sat in sats]
        sats_view.sort(key=lambda v: v["sat"].device_id)
        return render_template("satellites.html", satellites=sats_view, rooms=rooms)

    @app.route("/satellites/<device_id>/room", methods=["POST"])
    @login_required
    def set_satellite_room(device_id: str):
        hannah.set_satellite_room(device_id, request.form.get("room_id", ""))
        return redirect(url_for("satellites"))

    @app.route("/satellites/<device_id>/name", methods=["POST"])
    @login_required
    def set_satellite_name(device_id: str):
        display_name = request.form.get("display_name", "").strip()
        if display_name:
            hannah.set_satellite_display_name(device_id, display_name)
        return redirect(url_for("satellites"))

    @app.route("/settings")
    @login_required
    def settings():
        categories, settings_list = hannah.get_settings()
        categories_sorted = sorted(categories, key=lambda c: c.name)
        settings_by_cat: dict[int, list] = {c.id: [] for c in categories}
        for s in settings_list:
            pretty_value = s.value
            try:
                pretty_value = json.dumps(json.loads(s.value), indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
            settings_by_cat.setdefault(s.category_id, []).append({"setting": s, "pretty_value": pretty_value})
        for items in settings_by_cat.values():
            items.sort(key=lambda v: v["setting"].name)
        return render_template("settings.html", categories=categories_sorted, settings_by_cat=settings_by_cat)

    @app.route("/settings/<int:setting_id>/update", methods=["POST"])
    @login_required
    def update_setting(setting_id: int):
        ok, message = hannah.update_setting(setting_id, request.form.get("value", ""))
        if not ok:
            flash(message, "danger")
        return redirect(url_for("settings"))

    @app.route("/settings/<int:category_id>/create", methods=["POST"])
    @login_required
    def create_setting(category_id: int):
        name = request.form.get("name", "").strip()
        value = request.form.get("value", "")
        if name:
            ok, message = hannah.create_setting(category_id, name, value)
            if not ok:
                flash(message, "danger")
        return redirect(url_for("settings"))

    @app.route("/settings/<int:setting_id>/delete", methods=["POST"])
    @login_required
    def delete_setting(setting_id: int):
        hannah.delete_setting(setting_id)
        return redirect(url_for("settings"))

    @app.route("/routines")
    @login_required
    def routines():
        routines_view = []
        for r in hannah.get_routines():
            try:
                actions = json.loads(r.actions_json) if r.actions_json else []
            except json.JSONDecodeError:
                actions = []
            routines_view.append({"routine": r, "actions": actions})
        return render_template("routines.html", routines=routines_view)

    @app.route("/routines/new")
    @login_required
    def new_routine():
        return render_template(
            "routine_edit.html", routine=None, actions=[], triggers_text="",
            action_rows=range(_ROUTINE_NEW_ACTION_ROWS),
        )

    @app.route("/routines/create", methods=["POST"])
    @login_required
    def create_routine():
        name = request.form.get("name", "").strip()
        if name:
            triggers = _parse_lines(request.form.get("triggers", ""))
            actions = _parse_action_rows(request.form)
            reply = request.form.get("reply", "").strip()
            ok, message = hannah.create_routine(name, triggers, actions, reply)
            if not ok:
                flash(message, "danger")
                return redirect(url_for("new_routine"))
        return redirect(url_for("routines"))

    @app.route("/routines/<int:routine_id>/edit")
    @login_required
    def edit_routine(routine_id: int):
        routine = next((r for r in hannah.get_routines() if r.id == routine_id), None)
        if routine is None:
            return redirect(url_for("routines"))
        try:
            actions = json.loads(routine.actions_json) if routine.actions_json else []
        except json.JSONDecodeError:
            actions = []
        action_rows = range(max(len(actions) + 2, _ROUTINE_NEW_ACTION_ROWS))
        return render_template(
            "routine_edit.html", routine=routine, actions=actions,
            triggers_text="\n".join(routine.triggers), action_rows=action_rows,
        )

    @app.route("/routines/<int:routine_id>/edit", methods=["POST"])
    @login_required
    def save_routine(routine_id: int):
        name = request.form.get("name", "").strip()
        triggers = _parse_lines(request.form.get("triggers", ""))
        actions = _parse_action_rows(request.form)
        reply = request.form.get("reply", "").strip()
        ok, message = hannah.update_routine(routine_id, name, triggers, actions, reply)
        if not ok:
            flash(message, "danger")
        return redirect(url_for("routines"))

    @app.route("/routines/<int:routine_id>/delete", methods=["POST"])
    @login_required
    def delete_routine(routine_id: int):
        hannah.delete_routine(routine_id)
        return redirect(url_for("routines"))

    @app.route("/triggers")
    @login_required
    def triggers():
        triggers_view = []
        for t in hannah.get_triggers():
            try:
                actions = json.loads(t.actions_json) if t.actions_json else []
            except json.JSONDecodeError:
                actions = []
            try:
                when = json.loads(t.when_json) if t.when_json else {}
            except json.JSONDecodeError:
                when = {}
            triggers_view.append({"trigger": t, "actions": actions, "when": _as_or_list(when)})
        return render_template("triggers.html", triggers=triggers_view)

    @app.route("/triggers/new")
    @login_required
    def new_trigger():
        return render_template(
            "trigger_edit.html", trigger=None,
            when_rows=[_blank_when_row() for _ in range(_TRIGGER_NEW_WHEN_ROWS)],
            also_rows=[_blank_state_row() for _ in range(_TRIGGER_NEW_ALSO_ROWS)], also_op="and",
            unless_rows=[_blank_state_row() for _ in range(_TRIGGER_NEW_ALSO_ROWS)],
            action_rows=[_blank_action_row() for _ in range(_TRIGGER_NEW_ACTION_ROWS)],
            on_response_text="",
        )

    @app.route("/triggers/create", methods=["POST"])
    @login_required
    def create_trigger():
        trigger_id = _slugify(request.form.get("id", ""))
        if trigger_id:
            also = _parse_also(request.form)
            unless = _parse_state_condition_rows(request.form, "unless") or None
            when = _attach_also_unless(_parse_when_rows(request.form), also, unless)
            actions = _parse_trigger_action_rows(request.form)
            ask = request.form.get("ask", "").strip()
            rephrase = request.form.get("rephrase") == "on"
            room = request.form.get("room", "").strip() or "all"
            cooldown = int(request.form.get("cooldown") or 3600)
            delay = request.form.get("delay", "").strip()
            on_response_text = request.form.get("on_response_json", "").strip()
            try:
                on_response = json.loads(on_response_text) if on_response_text else []
            except json.JSONDecodeError as e:
                flash(f"Ungültiges JSON in 'Erweitert: Antwortregeln': {e}", "danger")
                return redirect(url_for("new_trigger"))
            ok, message = hannah.create_trigger(
                trigger_id, when, None, on_response, actions, "", ask, rephrase, room, cooldown, delay,
            )
            if not ok:
                flash(message, "danger")
                return redirect(url_for("new_trigger"))
        return redirect(url_for("triggers"))

    @app.route("/triggers/<trigger_id>/edit")
    @login_required
    def edit_trigger(trigger_id: str):
        trigger = next((t for t in hannah.get_triggers() if t.id == trigger_id), None)
        if trigger is None:
            return redirect(url_for("triggers"))
        try:
            conditions = _as_or_list(json.loads(trigger.when_json) if trigger.when_json else {})
        except json.JSONDecodeError:
            conditions = []
        also_conditions, also_op, unless_conditions = _extract_also_unless(conditions)
        try:
            actions = json.loads(trigger.actions_json) if trigger.actions_json else []
        except json.JSONDecodeError:
            actions = []
        try:
            on_response = json.loads(trigger.on_response_json) if trigger.on_response_json else []
            on_response_text = json.dumps(on_response, indent=2, ensure_ascii=False) if on_response else ""
        except json.JSONDecodeError:
            on_response_text = trigger.on_response_json
        return render_template(
            "trigger_edit.html", trigger=trigger,
            when_rows=[_condition_to_row(c) for c in conditions]
            + [_blank_when_row() for _ in range(_TRIGGER_NEW_WHEN_ROWS)],
            also_rows=[_state_condition_to_row(c) for c in also_conditions]
            + [_blank_state_row() for _ in range(_TRIGGER_NEW_ALSO_ROWS)],
            also_op=also_op,
            unless_rows=[_state_condition_to_row(c) for c in unless_conditions]
            + [_blank_state_row() for _ in range(_TRIGGER_NEW_ALSO_ROWS)],
            action_rows=[_action_to_row(a) for a in actions]
            + [_blank_action_row() for _ in range(_TRIGGER_NEW_ACTION_ROWS)],
            on_response_text=on_response_text,
        )

    @app.route("/triggers/<trigger_id>/edit", methods=["POST"])
    @login_required
    def save_trigger(trigger_id: str):
        also = _parse_also(request.form)
        unless = _parse_state_condition_rows(request.form, "unless") or None
        when = _attach_also_unless(_parse_when_rows(request.form), also, unless)
        actions = _parse_trigger_action_rows(request.form)
        ask = request.form.get("ask", "").strip()
        rephrase = request.form.get("rephrase") == "on"
        room = request.form.get("room", "").strip() or "all"
        cooldown = int(request.form.get("cooldown") or 3600)
        delay = request.form.get("delay", "").strip()
        on_response_text = request.form.get("on_response_json", "").strip()
        try:
            on_response = json.loads(on_response_text) if on_response_text else []
        except json.JSONDecodeError as e:
            flash(f"Ungültiges JSON in 'Erweitert: Antwortregeln': {e}", "danger")
            return redirect(url_for("edit_trigger", trigger_id=trigger_id))
        ok, message = hannah.update_trigger(
            trigger_id, when, None, on_response, actions, "", ask, rephrase, room, cooldown, delay,
        )
        if not ok:
            flash(message, "danger")
        return redirect(url_for("triggers"))

    @app.route("/triggers/<trigger_id>/delete", methods=["POST"])
    @login_required
    def delete_trigger(trigger_id: str):
        hannah.delete_trigger(trigger_id)
        return redirect(url_for("triggers"))

    @app.route("/users")
    @login_required
    def users():
        residents_by_id = {r.id: r for r in hannah.get_residents()}
        users_view = [
            {"user": u, "resident": residents_by_id.get(u.linked_accounts.get("residents", ""))}
            for u in hannah.get_users()
        ]
        return render_template("users.html", users=users_view, residents=hannah.get_residents())

    @app.route("/users/create", methods=["GET", "POST"])
    @login_required
    def create_user():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            email = request.form.get("email", "").strip()
            display_name = request.form.get("display_name", "").strip()
            user_type = request.form.get("type", "roomie")
            if not (username and password and email):
                flash("Username, Passwort und E-Mail sind Pflicht.", "danger")
                return redirect(url_for("create_user"))
            ok, message = hannah.create_user(username, password, email, display_name, user_type)
            if not ok:
                flash(message, "danger")
                return redirect(url_for("create_user"))
            return redirect(url_for("users"))
        return render_template("user_create.html", types=_USER_TYPES)

    @app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_user(user_id: int):
        user = next((u for u in hannah.get_users() if u.id == user_id), None)
        if user is None:
            return redirect(url_for("users"))
        if request.method == "POST":
            display_name = request.form.get("display_name", "").strip()
            email = request.form.get("email", "").strip()
            user_type = request.form.get("type", user.type)
            is_active = bool(request.form.get("is_active"))
            password = request.form.get("password", "").strip()
            trust_level = int(request.form.get("trust_level") or user.trust_level)
            system_messages = bool(request.form.get("system_messages"))
            ok, message = hannah.update_user(user_id, display_name, email, user_type, is_active, password)
            if not ok:
                flash(message, "danger")
            hannah.set_trust_level(user_id, trust_level)
            hannah.set_system_messages(user_id, system_messages)
            return redirect(url_for("users"))
        return render_template("user_edit.html", user=user, types=_USER_TYPES)

    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    @login_required
    def delete_user(user_id: int):
        hannah.delete_user(user_id)
        return redirect(url_for("users"))

    @app.route("/users/<int:user_id>/link-resident", methods=["POST"])
    @login_required
    def link_resident(user_id: int):
        resident_id = request.form.get("resident_id", "")
        resident = next((r for r in hannah.get_residents() if r.id == resident_id), None)
        if resident:
            payload = json.dumps({"resident_type": resident.type, "roomie_id": resident.roomie_id})
            hannah.link_account(user_id, "residents", resident.id, payload)
        return redirect(url_for("users"))

    @app.route("/users/<int:user_id>/unlink-resident", methods=["POST"])
    @login_required
    def unlink_resident(user_id: int):
        hannah.unlink_account(user_id, "residents")
        return redirect(url_for("users"))

    return app
