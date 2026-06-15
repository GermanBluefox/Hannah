"""
Trigger-Engine — proaktive Ansagen und Fragen aus ioBroker-States und Zeitplänen.

Konfiguration in triggers.yaml:

    triggers:
      - id: aussentuer_abend
        when:
          time: "23:00"
        say: "Leonie, denk an die Außentüren."
        rephrase: true   # optional: LLM formuliert 'say' vor der Ausgabe um
        room: all

      - id: fenster_kalt
        when:
          state: "javascript.0.virtualDevice.Fenster.Wohnzimmer.open"
          value: true
          also:
            state: "javascript.0.virtualDevice.Temperaturen.Wohnzimmer.Raumtemperatur.current"
            below: 12
        say: "Das Fenster ist noch offen und es wird kalt draußen."
        cooldown: 3600   # Sekunden, Standard 3600

      - id: friteuse_lang_an
        when:
          state: "javascript.0.virtualDevice.Steckdosen.Friteuse.on_duration_h"
          above: 5
        ask: "Die Friteuse ist seit über 5 Stunden an. Soll ich sie ausschalten?"
        room: all
        on_response:
          - condition: 'llm_match("Zustimmung")'
            say: "Okay, ich schalte die Friteuse aus."
          - condition: 'llm_match("Verneinung")'
            say: "Alright, ich lasse sie an."
          - say: "Ich habe dich leider nicht verstanden."

Hot-Reload: Dateiänderung wird beim nächsten Tick/State-Update erkannt.
"""
import logging
import os
import re
import threading
import time
from datetime import date, datetime
from typing import Any, Callable, Optional

import yaml

log = logging.getLogger(__name__)


class TriggerEngine:
    def __init__(
        self,
        path: str,
        announce_fn: Callable[[str, str], None],
        rephrase_fn: Callable[[str], str] | None = None,
        ask_fn: Callable[[str, str, Callable[[str], None]], None] | None = None,
        match_fn: Callable[[str, str], bool] | None = None,
        set_state_fn: Callable[[str, Any], None] | None = None,
    ):
        """
        path:          Pfad zur triggers.yaml
        announce_fn:   fn(room, text) — ruft process_announcement() auf
        rephrase_fn:   fn(text) → text — LLM-Umformulierung; None = Feature deaktiviert
        ask_fn:        fn(room, question, callback) — stellt eine Frage per TTS und ruft
                       callback(answer_text) auf wenn der Nutzer antwortet
        match_fn:      fn(text, category) → bool — LLM-Klassifikation für on_response
        set_state_fn:  fn(state_id, value) — setzt einen ioBroker-State; für set_state in on_response
        """
        self._path = path
        self._announce = announce_fn
        self._rephrase_fn = rephrase_fn
        self._ask_fn = ask_fn
        self._match_fn = match_fn
        self._set_state_fn = set_state_fn
        self._triggers: list[dict] = []
        self._mtime: float = -1.0

        # State-Cache: {state_id: parsed_value} — wird von on_state_update befüllt
        self._state_cache: dict[str, object] = {}
        # Vorherige Werte für Transition-Erkennung: {state_id: value}
        self._prev_state: dict[str, object] = {}
        # Cooldown-Tracking: {trigger_id: last_fired_timestamp}
        self._last_fired: dict[str, float] = {}
        # Zeit-Trigger: {trigger_id: last_fired_date} — einmal pro Tag
        self._last_fired_date: dict[str, date] = {}

        self._lock = threading.Lock()
        self._load()

        t = threading.Thread(target=self._tick_loop, daemon=True, name="trigger-engine")
        t.start()
        log.info("TriggerEngine gestartet.")

    # ------------------------------------------------------------------
    # Öffentliche Schnittstelle

    def get_referenced_state_ids(self) -> set[str]:
        """Gibt alle in Triggern referenzierten ioBroker-State-IDs zurück.
        Wird vom gRPC-Agent genutzt um den Adapter per WatchMore zu informieren."""
        ids: set[str] = set()
        with self._lock:
            for t in self._triggers:
                when = t.get("when", {})
                if "state" in when:
                    ids.add(when["state"])
                self._collect_condition_state_ids(when.get("unless"), ids)
                self._collect_condition_state_ids(when.get("also"), ids)
        return ids

    @staticmethod
    def _collect_condition_state_ids(condition, ids: set[str]) -> None:
        if not condition:
            return
        if isinstance(condition, list):
            for c in condition:
                TriggerEngine._collect_condition_state_ids(c, ids)
        elif isinstance(condition, dict) and "state" in condition:
            ids.add(condition["state"])

    def on_state_update(self, state_id: str, raw: str) -> None:
        """Vom mqtt_handler aufgerufen wenn sich ein ioBroker-State ändert."""
        value = self._parse(raw)
        with self._lock:
            prev = self._prev_state.get(state_id)
            self._state_cache[state_id] = value
            self._prev_state[state_id] = value
            if prev == value:
                return  # kein Übergang, nichts prüfen
            triggers = list(self._triggers)

        for trigger in triggers:
            when = trigger.get("when", {})
            if "state" not in when:
                continue
            if when["state"] != state_id:
                continue
            if not self._state_condition_matches(when, value):
                continue
            if not self._also_condition_matches(when.get("also")):
                continue
            if not self._unless_condition_matches(when.get("unless")):
                continue
            self._fire(trigger)

    # ------------------------------------------------------------------
    # Tick-Loop für Zeit-Trigger

    def _tick_loop(self) -> None:
        while True:
            now = datetime.now()
            sleep_secs = 60 - now.second + 1
            time.sleep(sleep_secs)
            self._load()
            self._check_time_triggers()

    _DAYS_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

    def _check_time_triggers(self) -> None:
        now = datetime.now()
        now_str = now.strftime("%H:%M")
        today = now.date()
        today_wd = now.weekday()
        with self._lock:
            triggers = list(self._triggers)

        for trigger in triggers:
            when = trigger.get("when", {})
            if when.get("time") != now_str:
                continue
            allowed_days = when.get("days")
            if allowed_days is not None:
                allowed_wds = [self._DAYS_MAP.get(str(d).lower(), -1) for d in allowed_days]
                if today_wd not in allowed_wds:
                    continue
            if not self._unless_condition_matches(when.get("unless")):
                continue
            tid = trigger.get("id", "")
            with self._lock:
                if self._last_fired_date.get(tid) == today:
                    continue
                self._last_fired_date[tid] = today
            self._fire(trigger)

    # ------------------------------------------------------------------
    # Trigger auslösen

    def _fire(self, trigger: dict) -> None:
        tid = trigger.get("id", "?")
        cooldown = float(trigger.get("cooldown", 3600))
        now = time.monotonic()

        with self._lock:
            last = self._last_fired.get(tid, 0.0)
            if now - last < cooldown:
                log.debug(f"Trigger '{tid}' im Cooldown, übersprungen.")
                return
            self._last_fired[tid] = now

        room = trigger.get("room", "all")
        ask = trigger.get("ask", "").strip()
        say = trigger.get("say", "").strip()

        if ask:
            if not self._ask_fn:
                log.warning(f"Trigger '{tid}': 'ask' definiert aber ask_fn fehlt — Fallback auf say.")
                if say:
                    self._announce(room, say)
                return
            text = ask
            if trigger.get("rephrase") and self._rephrase_fn:
                try:
                    text = self._rephrase_fn(ask) or ask
                except Exception as e:
                    log.warning(f"Trigger '{tid}': LLM-Rephrase fehlgeschlagen, nutze Original: {e}")
            on_response = trigger.get("on_response", [])
            log.info(f"Trigger '{tid}' fragt → [{room}] \"{text}\"")
            try:
                self._ask_fn(room, text, lambda answer, _tid=tid, _room=room, _rules=on_response:
                             self._process_response(answer, _tid, _room, _rules))
            except Exception as e:
                log.error(f"Trigger '{tid}': ask_fn fehlgeschlagen: {e}")
            return

        if not say:
            log.warning(f"Trigger '{tid}': weder 'say' noch 'ask' definiert.")
            return

        text = say
        if trigger.get("rephrase") and self._rephrase_fn:
            try:
                text = self._rephrase_fn(say) or say
            except Exception as e:
                log.warning(f"Trigger '{tid}': LLM-Rephrase fehlgeschlagen, nutze Original: {e}")

        log.info(f"Trigger '{tid}' ausgelöst → [{room}] \"{text}\"")
        try:
            self._announce(room, text)
        except Exception as e:
            log.error(f"Trigger '{tid}': Announcement fehlgeschlagen: {e}")

    def _process_response(self, answer: str, tid: str, room: str, rules: list) -> None:
        """Wertet on_response-Regeln aus und führt die erste passende Aktion aus."""
        log.info(f"Trigger '{tid}' Antwort erhalten für Raum '{room}': {answer!r}")
        fallback: Optional[dict] = None
        for rule in rules:
            condition = rule.get("condition", "").strip()
            if not condition:
                if fallback is None:
                    fallback = rule  # letzte Regel ohne Condition = Fallback
                continue
            m = re.match(r"""llm_match\(['"](.+)['"]\)""", condition)
            if not m:
                log.warning(f"Trigger '{tid}': unbekannte Condition {condition!r} — übersprungen.")
                continue
            category = m.group(1)
            if self._match_fn:
                if not self._match_fn(answer, category):
                    continue
            else:
                log.warning(f"Trigger '{tid}': llm_match benötigt match_fn — übersprungen.")
                continue
            self._execute_response_action(rule, tid, room)
            return
        if fallback is not None:
            self._execute_response_action(fallback, tid, room)

    def _execute_response_action(self, rule: dict, tid: str, room: str) -> None:
        say = rule.get("say", "").strip()
        if say:
            log.info(f"Trigger '{tid}' on_response → [{room}] \"{say}\"")
            try:
                self._announce(room, say)
            except Exception as e:
                log.error(f"Trigger '{tid}': on_response Announcement fehlgeschlagen: {e}")

        set_state = rule.get("set_state")
        if set_state:
            if not self._set_state_fn:
                log.warning(f"Trigger '{tid}': set_state definiert aber set_state_fn fehlt — übersprungen.")
            elif isinstance(set_state, dict):
                state_id = set_state.get("id", "").strip()
                value = set_state.get("value")
                if state_id:
                    log.info(f"Trigger '{tid}' set_state → {state_id} = {value!r}")
                    try:
                        self._set_state_fn(state_id, value)
                    except Exception as e:
                        log.error(f"Trigger '{tid}': set_state fehlgeschlagen: {e}")

    # ------------------------------------------------------------------
    # Bedingungen prüfen

    def _state_condition_matches(self, when: dict, value: object) -> bool:
        if "value" in when:
            expected = self._parse(str(when["value"]))
            return value == expected
        if "above" in when:
            try:
                return float(value) > float(when["above"])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
        if "below" in when:
            try:
                return float(value) < float(when["below"])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
        # Kein Wert-Filter → jeder Wechsel reicht
        return True

    def _also_condition_matches(self, also: Optional[dict | list]) -> bool:
        if not also:
            return True
        if isinstance(also, list):
            return all(self._also_condition_matches(a) for a in also)
        state_id = also.get("state")
        if not state_id:
            return True
        with self._lock:
            current = self._state_cache.get(state_id)
        if current is None:
            return False
        return self._state_condition_matches(also, current)

    def _unless_condition_matches(self, unless: Optional[dict | list]) -> bool:
        """Gibt True zurück wenn der Trigger feuern darf (unless-Bedingung NICHT erfüllt)."""
        if not unless:
            return True
        if isinstance(unless, list):
            return all(self._unless_condition_matches(u) for u in unless)
        state_id = unless.get("state")
        if not state_id:
            return True
        with self._lock:
            current = self._state_cache.get(state_id)
        if current is None:
            return True  # State unbekannt → nicht blockieren
        return not self._state_condition_matches(unless, current)

    # ------------------------------------------------------------------
    # Laden

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        mtime = os.path.getmtime(self._path)
        with self._lock:
            if mtime == self._mtime:
                return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            triggers = data.get("triggers", [])
            with self._lock:
                self._triggers = triggers
                self._mtime = mtime
            log.info(f"TriggerEngine: {len(triggers)} Trigger geladen aus '{self._path}'")
        except Exception as e:
            log.error(f"TriggerEngine: Fehler beim Laden von '{self._path}': {e}")

    # ------------------------------------------------------------------
    # Helpers

    @staticmethod
    def _parse(raw: str) -> object:
        s = str(raw).strip()
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        return s
