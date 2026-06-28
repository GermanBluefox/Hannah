class TestLogin:
    def test_protected_route_redirects_to_login(self, client):
        resp = client.get("/rooms")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_success_redirects_to_index(self, client):
        resp = client.post("/login", data={"username": "claude", "password": "claude"})
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

    def test_login_failure_shows_error(self, client):
        resp = client.post("/login", data={"username": "claude", "password": "wrong"})
        assert resp.status_code == 200
        assert "Ungültige Zugangsdaten" in resp.get_data(as_text=True)


class TestRooms:
    def test_rooms_lists_seeded_rooms_and_group_badge(self, logged_in_client):
        resp = logged_in_client.get("/rooms")
        body = resp.get_data(as_text=True)
        assert "Küche" in body
        assert "Erdgeschoss" in body  # group badge on a room that belongs to it


class TestGroups:
    def test_create_group_then_visible(self, logged_in_client):
        logged_in_client.post("/groups/create", data={"display_name": "Obergeschoss"})
        resp = logged_in_client.get("/groups")
        assert "Obergeschoss" in resp.get_data(as_text=True)

    def test_edit_group_renames_and_sets_rooms(self, logged_in_client):
        logged_in_client.post(
            "/groups/erdgeschoss/edit",
            data={"display_name": "EG", "room_ids": "bad"},
        )
        resp = logged_in_client.get("/groups")
        body = resp.get_data(as_text=True)
        assert "EG" in body
        assert "Bad" in body

    def test_delete_group(self, logged_in_client):
        logged_in_client.post("/groups/erdgeschoss/delete")
        resp = logged_in_client.get("/groups")
        # erdgeschoss is the only seeded group, so its removal should hit the empty state.
        # "Erdgeschoss" itself isn't a safe needle here: the create-form placeholder uses it as an example.
        assert "Noch keine Gruppen angelegt" in resp.get_data(as_text=True)


class TestSatellites:
    def test_satellites_lists_seeded_satellite(self, logged_in_client):
        resp = logged_in_client.get("/satellites")
        body = resp.get_data(as_text=True)
        assert "kueche-esp" in body
        assert "Küche01" in body

    def test_set_satellite_room(self, logged_in_client, hannah):
        logged_in_client.post("/satellites/kueche-esp/room", data={"room_id": "bad"})
        assert hannah._satellites["kueche-esp"]["room_id"] == "bad"

    def test_set_satellite_display_name(self, logged_in_client, hannah):
        logged_in_client.post("/satellites/kueche-esp/name", data={"display_name": "NeuerName"})
        assert hannah._satellites["kueche-esp"]["display_name"] == "NeuerName"


class TestSettings:
    def test_settings_lists_seeded_category_and_value(self, logged_in_client):
        resp = logged_in_client.get("/settings")
        body = resp.get_data(as_text=True)
        assert "nlu" in body
        assert "turn_on_words" in body
        assert "einschalten" in body

    def test_update_setting(self, logged_in_client, hannah):
        logged_in_client.post("/settings/1/update", data={"value": '["an"]'})
        assert hannah._settings[1]["value"] == ["an"]

    def test_update_setting_invalid_json_is_rejected(self, logged_in_client, hannah):
        resp = logged_in_client.post(
            "/settings/1/update", data={"value": "not json"}, follow_redirects=True
        )
        assert "invalid JSON" in resp.get_data(as_text=True)
        assert hannah._settings[1]["value"] == ["an", "einschalten"]

    def test_create_setting_then_visible(self, logged_in_client):
        logged_in_client.post("/settings/1/create", data={"name": "query_words", "value": '["wie"]'})
        resp = logged_in_client.get("/settings")
        assert "query_words" in resp.get_data(as_text=True)

    def test_delete_setting(self, logged_in_client, hannah):
        logged_in_client.post("/settings/1/delete")
        assert 1 not in hannah._settings


class TestRoutines:
    def test_routines_lists_seeded_routine(self, logged_in_client):
        resp = logged_in_client.get("/routines")
        body = resp.get_data(as_text=True)
        assert "Gute Nacht" in body
        assert "schlafenszeit" in body
        assert "hannah/set/devices/Licht/EG/Flur/on" in body

    def test_new_routine_form_renders(self, logged_in_client):
        resp = logged_in_client.get("/routines/new")
        assert resp.status_code == 200

    def test_edit_routine_form_prefills_existing_data(self, logged_in_client):
        resp = logged_in_client.get("/routines/1/edit")
        body = resp.get_data(as_text=True)
        assert "Gute Nacht" in body
        assert "schlafenszeit" in body

    def test_create_routine_with_topic_action(self, logged_in_client, hannah):
        logged_in_client.post("/routines/create", data={
            "name": "Nachtlicht",
            "triggers": "nachtlicht\nnacht licht",
            "reply": "Nachtlicht aktiviert.",
            "action_type": "topic",
            "action_topic": "hannah/set/devices/Licht/Bett/Nachtlicht",
            "action_value": "true",
            "action_say": "",
            "action_room": "",
        })
        created = next(r for r in hannah._routines.values() if r["name"] == "Nachtlicht")
        assert created["triggers"] == ["nachtlicht", "nacht licht"]
        assert created["actions"] == [{"topic": "hannah/set/devices/Licht/Bett/Nachtlicht", "value": "true"}]

    def test_create_routine_with_say_action(self, logged_in_client, hannah):
        logged_in_client.post("/routines/create", data={
            "name": "Ansage-Test",
            "triggers": "ansage test",
            "reply": "",
            "action_type": "say",
            "action_topic": "",
            "action_value": "",
            "action_say": "Hallo Welt",
            "action_room": "Küche",
        })
        created = next(r for r in hannah._routines.values() if r["name"] == "Ansage-Test")
        assert created["actions"] == [{"say": "Hallo Welt", "room": "Küche"}]

    def test_update_routine(self, logged_in_client, hannah):
        logged_in_client.post("/routines/1/edit", data={
            "name": "Gute Nacht",
            "triggers": "gute nacht",
            "reply": "Schlaf gut.",
            "action_type": "topic",
            "action_topic": "hannah/set/devices/Licht/EG/Flur/on",
            "action_value": "false",
            "action_say": "",
            "action_room": "",
        })
        assert hannah._routines[1]["reply"] == "Schlaf gut."
        assert hannah._routines[1]["triggers"] == ["gute nacht"]

    def test_delete_routine(self, logged_in_client, hannah):
        logged_in_client.post("/routines/1/delete")
        assert 1 not in hannah._routines


class TestTriggers:
    """#101 Teil 2 — No-Code-Trigger-Editor, mirror der TestRoutines-Tests."""

    def test_triggers_lists_seeded_trigger(self, logged_in_client):
        resp = logged_in_client.get("/triggers")
        body = resp.get_data(as_text=True)
        assert "aussentuer_abend" in body
        assert "23:00" in body

    def test_new_trigger_form_renders(self, logged_in_client):
        resp = logged_in_client.get("/triggers/new")
        assert resp.status_code == 200

    def test_edit_trigger_form_prefills_time_condition(self, logged_in_client):
        resp = logged_in_client.get("/triggers/aussentuer_abend/edit")
        body = resp.get_data(as_text=True)
        assert 'value="23:00"' in body
        assert "mon,tue,wed,thu,fri" in body

    def _create_payload(self, **overrides):
        payload = {
            "id": "Fenster Kalt",
            "when_type": ["state"], "when_state": ["fenster.wz.open"], "when_cmp": ["value"],
            "when_value": ["true"], "when_time": [""], "when_days": [""],
            "also_op": "and", "also_state": [], "also_cmp": [], "also_value": [],
            "unless_state": [], "unless_cmp": [], "unless_value": [],
            "action_type": ["say"], "action_say": ["Fenster offen."], "action_room": ["all"],
            "action_state_id": [""], "action_state_value": [""],
            "room": "all", "cooldown": "3600", "delay": "", "ask": "", "on_response_json": "",
        }
        payload.update(overrides)
        return payload

    def test_create_trigger_with_or_when_and_also_and_unless(self, logged_in_client, hannah):
        logged_in_client.post("/triggers/create", data=self._create_payload(
            when_type=["state", "state"], when_state=["fenster.wz.open", "fenster.kueche.open"],
            when_cmp=["value", "value"], when_value=["true", "true"], when_time=["", ""], when_days=["", ""],
            also_op="or", also_state=["a", "b"], also_cmp=["value", "value"], also_value=["true", "true"],
            unless_state=["abwesend"], unless_cmp=["value"], unless_value=["true"],
        ))
        created = hannah._triggers["fenster-kalt"]
        assert len(created["when"]) == 2
        assert created["when"][0]["also"] == {"op": "or", "conditions": [
            {"state": "a", "value": "true"}, {"state": "b", "value": "true"},
        ]}
        assert created["when"][0]["unless"] == [{"state": "abwesend", "value": "true"}]
        assert created["when"][1]["also"] == created["when"][0]["also"]
        assert created["actions"] == [{"say": "Fenster offen.", "room": "all"}]

    def test_create_trigger_with_time_condition_and_state_action(self, logged_in_client, hannah):
        logged_in_client.post("/triggers/create", data=self._create_payload(
            id="zeit-trigger",
            when_type=["time"], when_state=[""], when_cmp=["value"], when_value=[""],
            when_time=["07:00"], when_days=["mon,tue"],
            action_type=["state"], action_say=[""], action_room=[""],
            action_state_id=["javascript.0.virtualDevice.Licht.test"], action_state_value=["true"],
        ))
        created = hannah._triggers["zeit-trigger"]
        assert created["when"] == [{"time": "07:00", "days": ["mon", "tue"]}]
        assert created["actions"] == [{"set_state": {"id": "javascript.0.virtualDevice.Licht.test", "value": "true"}}]

    def test_update_trigger(self, logged_in_client, hannah):
        logged_in_client.post("/triggers/aussentuer_abend/edit", data=self._create_payload(
            when_type=["time"], when_state=[""], when_cmp=["value"], when_value=[""],
            when_time=["22:00"], when_days=[""], room="flur",
        ))
        updated = hannah._triggers["aussentuer_abend"]
        assert updated["when"] == [{"time": "22:00"}]
        assert updated["room"] == "flur"

    def test_delete_trigger(self, logged_in_client, hannah):
        logged_in_client.post("/triggers/aussentuer_abend/delete")
        assert "aussentuer_abend" not in hannah._triggers


class TestUsers:
    def test_users_lists_seeded_user(self, logged_in_client):
        resp = logged_in_client.get("/users")
        body = resp.get_data(as_text=True)
        assert "Leonie" in body
        assert "leonie" in body

    def test_create_user_then_visible(self, logged_in_client):
        logged_in_client.post("/users/create", data={
            "username": "hannah", "password": "secret", "email": "hannah@example.com",
            "display_name": "Hannah", "type": "roomie",
        })
        resp = logged_in_client.get("/users")
        assert "Hannah" in resp.get_data(as_text=True)

    def test_create_user_missing_fields_is_rejected(self, logged_in_client, hannah):
        before = len(hannah._user_records)
        resp = logged_in_client.post(
            "/users/create", data={"username": "", "password": "", "email": ""}, follow_redirects=True
        )
        assert "Pflicht" in resp.get_data(as_text=True)
        assert len(hannah._user_records) == before

    def test_edit_user_updates_fields(self, logged_in_client, hannah):
        logged_in_client.post("/users/1/edit", data={
            "display_name": "Leonie G.", "email": "leonie@neu.example.com", "type": "roomie",
            "is_active": "on", "trust_level": "9", "system_messages": "on", "password": "",
        })
        assert hannah._user_records[1]["display_name"] == "Leonie G."
        assert hannah._user_records[1]["trust_level"] == 9
        assert hannah._user_records[1]["system_messages"] is True

    def test_delete_user(self, logged_in_client, hannah):
        logged_in_client.post("/users/1/delete")
        assert 1 not in hannah._user_records

    def test_link_resident(self, logged_in_client, hannah):
        logged_in_client.post("/users/1/link-resident", data={"resident_id": "leonie_roomie"})
        assert hannah._user_records[1]["linked_accounts"]["residents"] == "leonie_roomie"

    def test_unlink_resident(self, logged_in_client, hannah):
        hannah._user_records[1]["linked_accounts"]["residents"] = "leonie_roomie"
        logged_in_client.post("/users/1/unlink-resident")
        assert "residents" not in hannah._user_records[1]["linked_accounts"]
