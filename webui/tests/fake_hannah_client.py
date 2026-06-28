"""In-memory stand-in for grpc_client.HannahClient — same method surface, no network,
no real Hannah Core needed. Built from real hannah_pb2 messages so route/template code
is exercised against the exact wire types Core actually sends."""
import json

from hannah_webui.proto import hannah_pb2


class FakeHannahClient:
    def __init__(self):
        self._rooms = {
            "kueche": "Küche",
            "wohnzimmer": "Wohnzimmer",
            "bad": "Bad",
        }
        self._groups = {
            "erdgeschoss": {"display_name": "Erdgeschoss", "room_ids": ["kueche", "wohnzimmer"]},
        }
        self._satellites = {
            "kueche-esp": {
                "display_name": "Küche01",
                "room_id": "kueche",
                "live_room": "kueche",
                "last_seen": "2026-06-27 12:00:00",
                "connected": True,
            },
        }
        self._users = {"claude": "claude"}
        self._user_records = {
            1: {
                "user_name": "leonie", "display_name": "Leonie", "email": "leonie@example.com",
                "trust_level": 8, "active": True, "system_messages": True, "type": "roomie",
                "linked_accounts": {},
            },
        }
        self._next_user_id = 2
        self._residents = {
            "leonie_roomie": {"roomie_id": "leonie", "display_name": "Leonie", "type": "roomie", "home": True},
        }
        self._categories = {1: "nlu"}
        self._settings = {
            1: {"category_id": 1, "name": "turn_on_words", "value": ["an", "einschalten"]},
        }
        self._next_setting_id = 2
        self._routines = {
            1: {
                "name": "Gute Nacht",
                "triggers": ["gute nacht", "schlafenszeit"],
                "actions": [{"topic": "hannah/set/devices/Licht/EG/Flur/on", "value": "false"}],
                "reply": "Gute Nacht.",
            },
        }
        self._next_routine_id = 2
        self._triggers = {
            "aussentuer_abend": {
                "when": {"time": "23:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
                "cancel_when": None, "on_response": [], "actions": [],
                "say": "Leonie, denk an die Außentüren.", "ask": "", "rephrase": True,
                "room": "all", "cooldown": 3600, "delay": "",
            },
        }

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def login(self, username, password):
        if self._users.get(username) == password:
            user = hannah_pb2.User(id=1, user_name=username, display_name=username, trust_level=7, active=True)
            return True, user
        return False, None

    def get_rooms(self):
        return [hannah_pb2.Room(room_id=rid, display_name=name) for rid, name in self._rooms.items()]

    def get_groups(self):
        result = []
        for group_id, g in self._groups.items():
            rooms = [
                hannah_pb2.Room(room_id=rid, display_name=self._rooms[rid])
                for rid in g["room_ids"] if rid in self._rooms
            ]
            result.append(hannah_pb2.Group(group_id=group_id, display_name=g["display_name"], rooms=rooms))
        return result

    def get_group(self, group_id):
        return next((g for g in self.get_groups() if g.group_id == group_id), None)

    def create_group(self, group_id, display_name):
        if group_id in self._groups:
            return False
        self._groups[group_id] = {"display_name": display_name, "room_ids": []}
        return True

    def update_group(self, group_id, display_name):
        if group_id not in self._groups:
            return False
        self._groups[group_id]["display_name"] = display_name
        return True

    def delete_group(self, group_id):
        return self._groups.pop(group_id, None) is not None

    def set_group_rooms(self, group_id, room_ids):
        if group_id not in self._groups:
            return False
        self._groups[group_id]["room_ids"] = list(room_ids)
        return True

    def get_satellites(self):
        result = []
        for device_id, sat in self._satellites.items():
            room_id = sat.get("room_id") or ""
            live_room = sat.get("live_room", "")
            result.append(hannah_pb2.Satellite(
                device_id=device_id,
                room=live_room,
                display_name=sat.get("display_name") or "",
                room_id=room_id,
                room_display_name=self._rooms.get(room_id, ""),
                last_seen=sat.get("last_seen") or "",
                connected=sat.get("connected", False),
                room_mismatch=sat.get("connected", False) and live_room != room_id,
            ))
        return result

    def set_satellite_room(self, device_id, room_id):
        if device_id not in self._satellites:
            return False
        self._satellites[device_id]["room_id"] = room_id or ""
        return True

    def set_satellite_display_name(self, device_id, display_name):
        if device_id not in self._satellites:
            return False
        self._satellites[device_id]["display_name"] = display_name
        return True

    def get_settings(self):
        categories = [hannah_pb2.Category(id=cid, name=name) for cid, name in self._categories.items()]
        settings = [
            hannah_pb2.Setting(id=sid, category_id=s["category_id"], name=s["name"], value=json.dumps(s["value"]))
            for sid, s in self._settings.items()
        ]
        return categories, settings

    def update_setting(self, setting_id, value_json):
        if setting_id not in self._settings:
            return False, "setting not found"
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError as e:
            return False, f"invalid JSON for setting {setting_id}: {e}"
        self._settings[setting_id]["value"] = value
        return True, "updated"

    def create_setting(self, category_id, name, value_json):
        try:
            value = json.loads(value_json) if value_json else None
        except json.JSONDecodeError as e:
            return False, f"invalid JSON: {e}"
        if any(s["category_id"] == category_id and s["name"] == name for s in self._settings.values()):
            return False, "name existiert bereits in dieser Kategorie"
        setting_id = self._next_setting_id
        self._next_setting_id += 1
        self._settings[setting_id] = {"category_id": category_id, "name": name, "value": value}
        return True, "created"

    def delete_setting(self, setting_id):
        return self._settings.pop(setting_id, None) is not None

    def get_users(self, include_inactive=True):
        users = []
        for uid, u in self._user_records.items():
            if not include_inactive and not u["active"]:
                continue
            users.append(hannah_pb2.User(
                id=uid, user_name=u["user_name"], display_name=u["display_name"],
                trust_level=u["trust_level"], active=u["active"], system_messages=u["system_messages"],
                email=u["email"], type=u["type"], linked_accounts=u["linked_accounts"],
            ))
        return users

    def get_residents(self):
        return [
            hannah_pb2.Resident(id=rid, roomie_id=r["roomie_id"], display_name=r["display_name"], type=r["type"], home=r["home"])
            for rid, r in self._residents.items()
        ]

    def create_user(self, username, password, email, display_name, user_type):
        if any(u["user_name"] == username for u in self._user_records.values()):
            return False, "username oder email existiert bereits"
        user_id = self._next_user_id
        self._next_user_id += 1
        self._user_records[user_id] = {
            "user_name": username, "display_name": display_name or username, "email": email,
            "trust_level": 5, "active": True, "system_messages": False, "type": user_type or "roomie",
            "linked_accounts": {},
        }
        return True, "created"

    def update_user(self, user_id, display_name, email, user_type, is_active, password=""):
        if user_id not in self._user_records:
            return False, "User nicht gefunden."
        u = self._user_records[user_id]
        u["display_name"] = display_name.strip() or u["user_name"]
        u["email"] = email.strip() or u["email"]
        u["type"] = user_type or u["type"]
        u["active"] = bool(is_active)
        return True, "updated"

    def delete_user(self, user_id):
        return self._user_records.pop(user_id, None) is not None

    def set_trust_level(self, user_id, level):
        if user_id not in self._user_records:
            return False
        self._user_records[user_id]["trust_level"] = level
        return True

    def set_system_messages(self, user_id, enabled):
        if user_id not in self._user_records:
            return False
        self._user_records[user_id]["system_messages"] = bool(enabled)
        return True

    def link_account(self, user_id, service, account_id, provider_payload=""):
        if user_id not in self._user_records:
            return False
        self._user_records[user_id]["linked_accounts"][service] = account_id
        return True

    def unlink_account(self, user_id, service):
        if user_id not in self._user_records:
            return False
        self._user_records[user_id]["linked_accounts"].pop(service, None)
        return True

    def get_routines(self):
        return [
            hannah_pb2.Routine(
                id=rid, name=r["name"], triggers=r["triggers"],
                actions_json=json.dumps(r["actions"]), reply=r["reply"],
            )
            for rid, r in self._routines.items()
        ]

    def create_routine(self, name, triggers, actions, reply):
        if any(r["name"] == name for r in self._routines.values()):
            return False, "name existiert bereits"
        routine_id = self._next_routine_id
        self._next_routine_id += 1
        self._routines[routine_id] = {"name": name, "triggers": triggers, "actions": actions, "reply": reply}
        return True, "created"

    def update_routine(self, routine_id, name, triggers, actions, reply):
        if routine_id not in self._routines:
            return False, "not found"
        self._routines[routine_id] = {"name": name, "triggers": triggers, "actions": actions, "reply": reply}
        return True, "updated"

    def delete_routine(self, routine_id):
        return self._routines.pop(routine_id, None) is not None

    def get_triggers(self):
        return [
            hannah_pb2.Trigger(
                id=tid, when_json=json.dumps(t["when"]),
                cancel_when_json=json.dumps(t["cancel_when"]) if t["cancel_when"] else "",
                on_response_json=json.dumps(t["on_response"]), actions_json=json.dumps(t["actions"]),
                say=t["say"], ask=t["ask"], rephrase=t["rephrase"], room=t["room"],
                cooldown=t["cooldown"], delay=t["delay"],
            )
            for tid, t in self._triggers.items()
        ]

    def create_trigger(self, trigger_id, when, cancel_when, on_response, actions, say, ask, rephrase, room, cooldown, delay):
        if trigger_id in self._triggers:
            return False, "id existiert bereits"
        self._triggers[trigger_id] = {
            "when": when, "cancel_when": cancel_when, "on_response": on_response, "actions": actions,
            "say": say, "ask": ask, "rephrase": rephrase, "room": room, "cooldown": cooldown, "delay": delay,
        }
        return True, "created"

    def update_trigger(self, trigger_id, when, cancel_when, on_response, actions, say, ask, rephrase, room, cooldown, delay):
        if trigger_id not in self._triggers:
            return False, "not found"
        self._triggers[trigger_id] = {
            "when": when, "cancel_when": cancel_when, "on_response": on_response, "actions": actions,
            "say": say, "ask": ask, "rephrase": rephrase, "room": room, "cooldown": cooldown, "delay": delay,
        }
        return True, "updated"

    def delete_trigger(self, trigger_id):
        return self._triggers.pop(trigger_id, None) is not None
