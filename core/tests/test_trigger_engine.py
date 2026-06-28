import datetime as datetime_module
import os

import pytest

import hannah.utils.db as db_module
from hannah import trigger_engine as trigger_engine_module
from hannah.trigger_engine import TriggerEngine


@pytest.fixture
def engine(tmp_path):
    """Echte (nicht gemockte) TriggerEngine gegen eine Wegwerf-SQLite-DB — gleiches
    Muster wie tests/test_room_manager.py."""
    db_module.DB_PATH = os.path.join(str(tmp_path), "h.db")
    db_module.init_db()
    eng = TriggerEngine(
        db_module.get_db,
        announce_fn=lambda room, text: eng.announced.append((room, text)),
        set_state_fn=lambda state_id, value: eng.states_set.append((state_id, value)),
    )
    eng.announced = []
    eng.states_set = []
    return eng


def _create(engine, id, when, *, actions=None, say="", unless=None, cooldown=0):
    if unless is not None:
        when = dict(when)
        when["unless"] = unless
    ok = engine.create_trigger(id, when, None, [], actions or [], say, "", False, "all", cooldown, "")
    assert ok
    return ok


class _FixedDatetime:
    """Ersetzt trigger_engine.datetime für _check_time_triggers()-Tests."""

    def __init__(self, year, month, day, hour, minute):
        self._fixed = datetime_module.datetime(year, month, day, hour, minute)

    def now(self):
        return self._fixed


class TestWhenAltFormatRegression:
    """Einzelnes when-Dict (Alt-Format) muss sich exakt wie vorher verhalten."""

    def test_single_state_condition_fires(self, engine):
        _create(engine, "t1", {"state": "s1", "value": True}, say="Hallo")

        engine.on_state_update("s1", "true")

        assert engine.announced == [("all", "Hallo")]

    def test_single_time_condition_fires(self, engine, monkeypatch):
        _create(engine, "t1", {"time": "23:00"}, say="Gute Nacht")
        monkeypatch.setattr(trigger_engine_module, "datetime", _FixedDatetime(2026, 6, 28, 23, 0))

        engine._check_time_triggers()

        assert engine.announced == [("all", "Gute Nacht")]

    def test_also_plain_list_is_and(self, engine):
        _create(engine, "t1", {
            "state": "s1", "value": True,
            "also": [{"state": "a1", "value": True}, {"state": "a2", "value": True}],
        }, say="Beide")

        engine.on_state_update("a1", "true")
        engine.on_state_update("s1", "true")
        assert engine.announced == []  # a2 fehlt noch

        engine.on_state_update("a2", "true")
        engine.on_state_update("s1", "false")
        engine.on_state_update("s1", "true")
        assert engine.announced == [("all", "Beide")]

    def test_bare_say_without_actions(self, engine):
        _create(engine, "t1", {"state": "s1", "value": True}, say="Nur Say")

        engine.on_state_update("s1", "true")

        assert engine.announced == [("all", "Nur Say")]


class TestWhenOrList:
    def test_fires_on_either_condition(self, engine):
        _create(engine, "t1", [{"state": "s1", "value": True}, {"state": "s2", "value": True}], say="Fire")

        engine.on_state_update("s1", "true")
        engine.on_state_update("s2", "true")

        assert engine.announced == [("all", "Fire"), ("all", "Fire")]

    def test_time_or_list_fires_on_either(self, engine, monkeypatch):
        _create(engine, "t1", [{"time": "07:00"}, {"time": "23:00"}], say="Zeit")
        monkeypatch.setattr(trigger_engine_module, "datetime", _FixedDatetime(2026, 6, 28, 23, 0))

        engine._check_time_triggers()

        assert engine.announced == [("all", "Zeit")]


class TestAlsoOpFormat:
    def test_op_or_fires_if_any_matches(self, engine):
        _create(engine, "t1", {
            "state": "s1", "value": True,
            "also": {"op": "or", "conditions": [{"state": "a1", "value": True}, {"state": "a2", "value": True}]},
        }, say="Or-Match")

        engine.on_state_update("a1", "true")
        engine.on_state_update("s1", "true")

        assert engine.announced == [("all", "Or-Match")]

    def test_op_and_requires_all(self, engine):
        _create(engine, "t1", {
            "state": "s1", "value": True,
            "also": {"op": "and", "conditions": [{"state": "a1", "value": True}, {"state": "a2", "value": True}]},
        }, say="And-Match")

        engine.on_state_update("a1", "true")
        engine.on_state_update("s1", "true")
        assert engine.announced == []  # a2 fehlt noch

        engine.on_state_update("a2", "true")
        engine.on_state_update("s1", "false")
        engine.on_state_update("s1", "true")
        assert engine.announced == [("all", "And-Match")]


class TestActionsList:
    def test_multiple_actions_executed_in_order(self, engine):
        _create(engine, "t1", {"state": "s1", "value": True}, say="Sollte ignoriert werden", actions=[
            {"say": "Eins"},
            {"set_state": {"id": "x.y", "value": False}},
            {"say": "Zwei", "room": "kueche"},
        ])

        engine.on_state_update("s1", "true")

        assert engine.announced == [("all", "Eins"), ("kueche", "Zwei")]
        assert engine.states_set == [("x.y", False)]

    def test_empty_actions_falls_back_to_say(self, engine):
        _create(engine, "t1", {"state": "s1", "value": True}, say="Legacy", actions=[])

        engine.on_state_update("s1", "true")

        assert engine.announced == [("all", "Legacy")]


class TestUnlessUnchanged:
    def test_unless_blocks_firing(self, engine):
        _create(engine, "t1", {"state": "s1", "value": True}, say="Bedingt",
                unless={"state": "u1", "value": True})

        engine.on_state_update("u1", "true")
        engine.on_state_update("s1", "true")
        assert engine.announced == []

        engine.on_state_update("u1", "false")
        engine.on_state_update("s1", "false")
        engine.on_state_update("s1", "true")
        assert engine.announced == [("all", "Bedingt")]
