#!/usr/bin/env python3
"""
hannah — Voice-Assistant Middleware
Empfängt Audio via UDP oder gRPC-Proxy, transkribiert mit Whisper,
erkennt Intents anhand ioBroker-Räumen/Functions
und steuert Geräte via ioBroker REST-API.
"""
import argparse
import datetime
import json
import time
import uuid
import logging
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
import wave
from typing import Optional

import numpy as np

from hannah import audio as audio_mod
from hannah import config as config_mod
from hannah.car_tracker import CarManager, CarTracker
from hannah.routines import RoutineManager
from hannah.grpc_server import GrpcServer, HannahServicer, make_car_parked_event, make_firmware_event, make_resident_event, make_system_notification_event
from hannah.iobroker import IoBrokerClient
from hannah.mqtt_handler import MQTTHandler
from hannah.nlu import NLU, Intent, build_clarification_question, resolve_clarification_answer
from hannah.residents import ResidentsClient
from hannah.stt import STT
from hannah.tts import TTS
from hannah.udp_server import UDPServer
from hannah.conversation import ConversationContext
from hannah.llm import load as load_llm, prepare_prompt
from hannah.tool_agent import ToolAgent
from hannah.memory import LongTermMemory
from hannah.user_registry import UserRegistry
from hannah.weather import WeatherCache
from hannah.trigger_engine import TriggerEngine
from hannah.ble_location import BleLocationEngine
from hannah.timers import AlarmManager, HannahTimerStore, format_duration, next_alarm_dt
from hannah.__version__ import VERSION as HANNAH_VERSION


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="hannah Voice Middleware")
    parser.add_argument("-c", "--config", default="config.yaml", help="Pfad zur config.yaml")
    parser.add_argument("-l", "--log-level", default="INFO", help="Log-Level (DEBUG|INFO|WARNING)")
    args = parser.parse_args()

    setup_logging(args.log_level)
    log = logging.getLogger("hannah.main")
    log.info(f"Hannah Core {HANNAH_VERSION}")

    try:
        cfg = config_mod.load(args.config)
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)

    # Statische Raum-Zuordnung aus Config (Fallback für MQTT-Satelliten ohne Registrierung)
    device_rooms: dict[str, str] = cfg.get("device_rooms", {})

    # Asset-Manifest (einmalig beim Start abrufen — enthält u.a. duration_s für Jingles)
    def _load_asset_manifest() -> dict:
        import urllib.request as _urlreq
        asset_cfg = cfg.get("asset_server", {})
        url   = asset_cfg.get("url", "").rstrip("/")
        token = asset_cfg.get("token", "")
        if not url or not token:
            return {}
        try:
            req = _urlreq.Request(
                f"{url}/manifest",
                headers={"Authorization": f"Bearer {token}"},
            )
            with _urlreq.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("assets", {})
        except Exception as exc:
            log.warning(f"[asset] Manifest nicht abrufbar: {exc}")
        return {}

    _asset_manifest: dict = _load_asset_manifest()

    # ioBroker
    iobroker = IoBrokerClient(cfg.get("iobroker", {}))

    if not iobroker.rooms:
        log.warning("Keine Räume aus ioBroker geladen — NLU arbeitet ohne Raum-Erkennung.")

    # User Registry
    residents_cfg = cfg.get("residents", {})
    registry = UserRegistry(
        cfg.get("user_registry", {}),
        hannah_roomie=residents_cfg.get("hannah_roomie", "hannah"),
    )

    # STT + NLU + TTS
    stt = STT(cfg.get("stt", {}))
    _group_pseudo_rooms = {k: k.capitalize() for k in cfg.get("groups", {})}
    nlu = NLU(cfg.get("nlu", {}), {**iobroker.rooms, **_group_pseudo_rooms}, iobroker.devices)
    tts = TTS(cfg.get("tts", {}))

    llm = load_llm(cfg.get("llm", {}))
    llm_system_prompt: str = cfg.get("llm", {}).get("system_prompt", "")
    tool_agent = ToolAgent(llm, iobroker)

    mem_cfg = cfg.get("memory", {})
    memory = LongTermMemory(
        db_path=mem_cfg.get("db", "memory.db"),
        recent_limit=int(mem_cfg.get("recent_limit", 10)),
    )

    _SUMMARY_PROMPT = (
        "Fasse das folgende Gespräch in einem einzigen, natürlichen deutschen Satz zusammen. "
        "Konzentriere dich auf das Wesentliche: worüber wurde gesprochen, was hat die Person "
        "erwähnt oder gefragt. Antworte nur mit dem Satz, ohne Einleitung."
    )
    _ANON_SOURCES = {"anon", "grpc-voice"}

    def _on_conversation_end(source: str, history: list):
        if source in _ANON_SOURCES or not history:
            return
        try:
            history_text = "\n".join(
                f"{'Nutzer' if m['role'] == 'user' else 'Hannah'}: {m['content']}"
                for m in history
            )
            summary = llm.chat(history_text, system_prompt=_SUMMARY_PROMPT)
            if summary and summary.strip():
                memory.add(source, summary.strip())
        except Exception as e:
            log.warning(f"[memory] Zusammenfassung fehlgeschlagen für {source!r}: {e}")

    llm_cfg = cfg.get("llm", {})
    conv_ctx = ConversationContext(
        ttl=float(llm_cfg.get("context_ttl", 120.0)),
        max_history_turns=int(llm_cfg.get("history_turns", 3)),
        on_conversation_end=_on_conversation_end,
    )

    weather_cfg = cfg.get("weather", {})
    weather = WeatherCache(
        topic_prefix=weather_cfg.get("topic_prefix", "openweathermap/0/forecast")
    )

    # Auto-Tracker (cars: Liste; car: alter Einzeleintrag — Backward-Compat)
    _car_cfgs = cfg.get("cars") or ([cfg["car"]] if cfg.get("car") else [{}])
    car_manager = CarManager([CarTracker(c) for c in _car_cfgs])

    routine_manager = RoutineManager(cfg.get("routines_file", "routines.yaml"))

    audio_cfg = cfg.get("audio", {})

    # ------------------------------------------------------------------
    # Kern-Pipeline: numpy-Array → Intent → Gerät schalten (Sprach-Pfad)

    def pipeline(device: str, audio_array, publish_error, publish_answer):
        # STT
        try:
            text, no_speech_prob = stt.transcribe(audio_array)
        except Exception as e:
            log.error(f"[{device}] STT fehlgeschlagen: {e}")
            publish_error(f"STT: {e}")
            return

        if not text:
            log.debug(f"[{device}] Keine Sprache erkannt (no_speech={no_speech_prob:.2f})")
            return

        log.info(f"[{device}] Text: '{text}'")

        # Routine-Check vor NLU
        routine = routine_manager.match(text)
        if routine:
            for action in routine.actions:
                if action.say:
                    process_announcement(action.room, action.say)
                else:
                    mqtt_handler.publish_raw(action.topic, action.value)
            if routine.reply:
                _handle_feedback(device, True, routine.reply)
            return

        # Offene Rückfrage auflösen
        if conv_ctx.has_clarification(device):
            clarification = conv_ctx.get_clarification(device)
            resolved = resolve_clarification_answer(text, clarification["candidates"])
            if resolved:
                conv_ctx.clear_clarification(device)
                orig: Intent = clarification["intent"]
                orig.room    = resolved[1]
                orig.room_id = resolved[0]
                count = iobroker.execute(orig, satellite_device=device)
                conv_ctx.update_from_intent(device, orig)
                if count == 0:
                    _handle_feedback(device, False, "Tut mir leid, ich weiß nicht was du meinst.")
                return
            # Keine Übereinstimmung → Rückfrage verwerfen, normal weiterverarbeiten
            conv_ctx.clear_clarification(device)

        # NLU
        intent = nlu.parse(text)

        # Gesprächskontext: fehlende Felder ergänzen + Aktion erben
        conv_ctx.fill_intent(device, intent)
        conv_ctx.inherit_action(device, intent)

        # Raum-Fallback: UDP-Registrierung → Config → nichts
        # Bei Query-Intents nur anwenden wenn der Raum explizit im Text genannt wurde —
        # ohne Raum soll die globale Abfrage greifen.
        if intent.room is None and intent.name not in ("Query", "CarQuery"):
            room = udp_server.get_registered_room(device) or device_rooms.get(device)
            if room:
                intent.room    = room
                intent.room_id = room.lower()
                log.debug(f"[{device}] Raum-Fallback: '{room}'")

        log.info(
            f"[{device}] Intent: {intent.name} | "
            f"Raum: {intent.room} | Gerät: {intent.device} | Wert: {intent.value}"
        )

        # Mehrdeutiger Raum → Rückfrage stellen
        if intent.candidates:
            question = build_clarification_question(intent.candidates)
            conv_ctx.set_clarification(device, intent, intent.candidates)
            _handle_feedback(device, True, question)
            return

        if intent.name == "CarQuery":
            answer = car_manager.answer_for_roomie(scope=intent.value or "all")
            publish_answer(answer)
        elif intent.name == "WeatherQuery":
            publish_answer(weather.build_answer(scope=intent.value or "today"))
        elif intent.name == "SetPresence":
            if intent.value == "away":
                log.info(f"[{device}] SetPresence away — Sprecher unbekannt, Status nicht gesetzt.")
                _handle_feedback(device, True, "Tschüss! Bis bald.")
            else:
                log.info(f"[{device}] SetPresence home — Sprecher unbekannt, Status nicht gesetzt.")
                _handle_feedback(device, True, "Willkommen zuhause!")
        elif intent.name in ("StopIntent", "PauseIntent", "ResumeIntent"):
            cmd_type = {"StopIntent": "stop", "PauseIntent": "pause", "ResumeIntent": "resume"}[intent.name]
            targets = _resolve_targets(intent.room_id or device)
            for t in targets:
                udp_server.send_command(t, {"type": cmd_type})
        elif intent.name == "SetTimer":
            seconds = int(intent.value)
            label = intent.label or format_duration(seconds)
            timer_id = str(uuid.uuid4())
            fire_at = int(time.time()) + seconds
            room_id = intent.room_id or "all"
            timer_store.set(timer_id, label, fire_at, room_id)
            grpc_servicer.timer_create(timer_id, label, fire_at, room_id)
            reply = f"Timer für {format_duration(seconds)} gesetzt."
            if intent.label:
                reply = f"Timer für {format_duration(seconds)} gesetzt: {intent.label}."
            _handle_feedback(device, True, reply)
        elif intent.name == "SetAlarm":
            alarm_cfg = cfg.get("alarm", {})
            target = alarm_cfg.get("satellite") or device
            alarm_manager.set(target, intent.value, set_by=device)
            dt = next_alarm_dt(intent.value)
            label = f"morgen um {dt.strftime('%H:%M')} Uhr" if dt.date() > datetime.datetime.now().date() else f"um {dt.strftime('%H:%M')} Uhr"
            _handle_feedback(device, True, f"Wecker gestellt {label}.")
        elif intent.name == "SetDND":
            active = intent.value == "on"
            _apply_global_dnd(active)
            _handle_feedback(device, True, "Nicht stören aktiv." if active else "Nicht stören deaktiviert.")
        elif intent.name == "SetMute":
            active = intent.value == "on"
            _apply_global_mute(active)
            _handle_feedback(device, True, "Mikrofone stumm." if active else "Mikrofone wieder aktiv.")
        elif intent.name == "Smalltalk":
            history = conv_ctx.get_llm_history(device)
            answer = llm.chat(text, system_prompt=prepare_prompt(llm_system_prompt, iobroker), history=history)
            conv_ctx.add_llm_exchange(device, text, answer)
            _handle_feedback(device, True, answer)
        elif intent.name == "Query":
            answer = iobroker.answer_query(intent)
            if answer:
                conv_ctx.update_from_intent(device, intent)
                publish_answer(answer)
            else:
                log.warning(f"[{device}] Keine Antwort auf Query möglich.")
        else:
            count = iobroker.execute(intent, satellite_device=device)
            conv_ctx.update_from_intent(device, intent)
            if intent.name == "Unknown":
                _handle_feedback(device, False, "Tut mir leid, ich habe dich nicht verstanden.")
            elif count == 0:
                log.warning(f"[{device}] Keine States gesetzt — Intent nicht auflösbar.")
                _handle_feedback(device, False, "Tut mir leid, ich weiß nicht was du meinst.")

    # ------------------------------------------------------------------
    def _speaker_context(speaker_roomie_id: str) -> str:
        """Gibt einen Zusatz-Abschnitt für den System-Prompt zurück der Sprecher-Info enthält."""
        if not speaker_roomie_id:
            return ""
        user = registry.get_by_roomie(speaker_roomie_id)
        if not user:
            return f"\n\nDie Person die gerade mit dir spricht heißt {speaker_roomie_id}."
        name        = user["display_name"]
        trust_level = user.get("trust_level", 5)
        # relationship_level: noch nicht implementiert, Platzhalter für spätere Erweiterung
        mem = memory.format_for_prompt(speaker_roomie_id)
        return (
            f"\n\nDie Person die gerade mit dir spricht heißt {name}."
            f" Vertrauenslevel: {trust_level}/10."
            f"{mem}"
        )

    def _handle_text(text: str, speaker_roomie_id: str = "", source: str = "") -> tuple[str, str]:
        """
        Verarbeitet einen Text-Befehl durch NLU und gibt (Antwort, Intent-Name) zurück.
        Kein TTS — reines Text-in/Text-out.
        Wird vom gRPC-Server (Telegram/Satelliten/ioBroker-Adapter) genutzt.

        speaker_roomie_id: optionale Roomie-ID aus Voice-ID-Erkennung.
        source: Kontext-Schlüssel (Gerät, Roomie-ID, Kanal). Leer = speaker_roomie_id oder "anon".
        """
        _source = source or speaker_roomie_id or "anon"

        routine = routine_manager.match(text)
        if routine:
            for action in routine.actions:
                if action.say:
                    process_announcement(action.room, action.say)
                else:
                    mqtt_handler.publish_raw(action.topic, action.value)
            return routine.reply or "Routine ausgeführt.", "Routine"

        # Smalltalk-Modus: LLM-Classifier vor NLU schalten
        if conv_ctx.is_smalltalk_active(_source):
            if not llm.classify(text):
                log.debug(f"[{_source}] Classifier → SMALLTALK (Modus aktiv)")
                sp = prepare_prompt(llm_system_prompt, iobroker) + _speaker_context(speaker_roomie_id)
                history = conv_ctx.get_llm_history(_source)
                answer = llm.chat(text, system_prompt=sp, history=history)
                conv_ctx.add_llm_exchange(_source, text, answer)
                return answer, "Smalltalk"
            log.debug(f"[{_source}] Classifier → COMMAND (Modus aktiv, weiter mit NLU)")

        if conv_ctx.has_clarification(_source):
            clarification = conv_ctx.get_clarification(_source)
            resolved = resolve_clarification_answer(text, clarification["candidates"])
            if resolved:
                conv_ctx.clear_clarification(_source)
                orig: Intent = clarification["intent"]
                orig.room    = resolved[1]
                orig.room_id = resolved[0]
                count = iobroker.execute(orig)
                conv_ctx.update_from_intent(_source, orig)
                return ("OK." if count > 0 else "Keine Geräte gefunden."), "Routine"
            conv_ctx.clear_clarification(_source)

        intent = nlu.parse(text)

        # Gesprächskontext: fehlende Felder ergänzen + Aktion erben
        conv_ctx.fill_intent(_source, intent)
        conv_ctx.inherit_action(_source, intent)

        log.info(
            f"[textcmd] Text: '{text}' → Intent: {intent.name} | "
            f"Raum: {intent.room} | Gerät: {intent.device} | Wert: {intent.value} | SpeakerRoomie: {speaker_roomie_id}"
        )

        if intent.candidates:
            question = build_clarification_question(intent.candidates)
            conv_ctx.set_clarification(_source, intent, intent.candidates)
            return question, "Clarification"

        if intent.name == "CarQuery":
            answer = car_manager.answer_for_roomie(scope=intent.value or "all", roomie_id=speaker_roomie_id)
        elif intent.name == "WeatherQuery":
            answer = weather.build_answer(scope=intent.value or "today")
        elif intent.name == "SetPresence":
            if intent.value == "away":
                if speaker_roomie_id:
                    residents.set_user_away(speaker_roomie_id)
                else:
                    log.info("SetPresence away — Sprecher anonym, Status nicht gesetzt.")
                answer = "Tschüss!"
            else:
                if speaker_roomie_id:
                    residents.set_user_home(speaker_roomie_id)
                else:
                    log.info("SetPresence home — Sprecher anonym, Status nicht gesetzt.")
                answer = "Willkommen zuhause!"
        elif intent.name in ("StopIntent", "PauseIntent", "ResumeIntent"):
            cmd_type = {"StopIntent": "stop", "PauseIntent": "pause", "ResumeIntent": "resume"}[intent.name]
            source_device = source if source in {**udp_server.registered_devices(), **grpc_servicer.proxy_satellites()} else None
            targets = _resolve_targets(intent.room_id or source_device or "all")
            for t in targets:
                udp_server.send_command(t, {"type": cmd_type})
            answer = ""
        elif intent.name == "SetDND":
            active = intent.value == "on"
            _apply_global_dnd(active)
            answer = "Nicht stören aktiv." if active else "Nicht stören deaktiviert."
        elif intent.name == "SetMute":
            active = intent.value == "on"
            _apply_global_mute(active)
            answer = "Mikrofone stumm." if active else "Mikrofone wieder aktiv."
        elif intent.name == "SetTimer":
            seconds = int(intent.value)
            label = intent.label or format_duration(seconds)
            timer_id = str(uuid.uuid4())
            fire_at = int(time.time()) + seconds
            room_id = intent.room_id or "all"
            timer_store.set(timer_id, label, fire_at, room_id)
            grpc_servicer.timer_create(timer_id, label, fire_at, room_id)
            answer = f"Timer für {format_duration(seconds)} gesetzt."
            if intent.label:
                answer = f"Timer für {format_duration(seconds)} gesetzt: {intent.label}."
        elif intent.name == "SetAlarm":
            alarm_cfg = cfg.get("alarm", {})
            target = alarm_cfg.get("satellite") or _source
            alarm_manager.set(target, intent.value, set_by=_source)
            dt = next_alarm_dt(intent.value)
            label = f"morgen um {dt.strftime('%H:%M')} Uhr" if dt.date() > datetime.datetime.now().date() else f"um {dt.strftime('%H:%M')} Uhr"
            answer = f"Wecker gestellt {label}."
        elif intent.name == "Smalltalk":
            sp = prepare_prompt(llm_system_prompt, iobroker) + _speaker_context(speaker_roomie_id)
            history = conv_ctx.get_llm_history(_source)
            answer = tool_agent.run(text, system_prompt=sp, history=history)
            if answer:
                conv_ctx.add_llm_exchange(_source, text, answer)
                conv_ctx.set_smalltalk_active(_source, True)
            else:
                answer = "Das habe ich leider nicht verstanden."
        elif intent.name == "Query":
            answer = iobroker.answer_query(intent) or "Keine Antwort verfügbar."
            conv_ctx.update_from_intent(_source, intent)
        elif intent.name == "Unknown":
            sp = prepare_prompt(llm_system_prompt, iobroker) + _speaker_context(speaker_roomie_id)
            history = conv_ctx.get_llm_history(_source)
            answer = tool_agent.run(text, system_prompt=sp, history=history)
            if answer:
                conv_ctx.add_llm_exchange(_source, text, answer)
            else:
                answer = "Das habe ich leider nicht verstanden."
        else:
            count = iobroker.execute(intent)
            if count > 0:
                conv_ctx.set_smalltalk_active(_source, False)
            answer = "Keine Geräte gefunden." if count == 0 else f"OK, {count} Gerät(e) geschaltet."
            conv_ctx.update_from_intent(_source, intent)

        return answer, intent.name

    # ── Satellit-Steuerung: Volume / Mute / DND ───────────────────────────────
    _global_volume: int = 80          # 0-100
    _device_volume: dict[str, int] = {}
    _device_mute:   dict[str, bool] = {}
    _device_dnd:    dict[str, bool] = {}

    def _send_audio(target: str, pcm: bytes, rate: int, label: str = ""):
        """Sendet PCM an einen Satelliten."""
        if grpc_servicer.has_proxy():
            grpc_servicer.push_audio_to_proxy(target, pcm, rate)
            log.info(f"{label}Announcement → {target} (via Proxy)")
        else:
            udp_server.send_tts(target, pcm, sample_rate=rate)
            log.info(f"{label}Announcement → {target} (via UDP)")

    def _resolve_targets(device: str, label: str = "") -> list[str]:
        """Löst device/room/group/'all' auf eine Liste von Ziel-Geräten auf."""
        all_devices = {**udp_server.registered_devices(), **grpc_servicer.proxy_satellites()}
        if device == "all":
            return list(all_devices.keys())
        if device in all_devices:
            return [device]
        room_lower = device.lower()
        targets = [d for d, r in all_devices.items() if r.lower() == room_lower]
        if not targets:
            groups = cfg.get("groups", {})
            for group_key, rooms in groups.items():
                if group_key.lower() == room_lower:
                    for room in rooms:
                        targets += [d for d, r in all_devices.items() if r.lower() == room.lower()]
                    break
        if not targets:
            log.warning(f"{label}kein Satellit in Raum/Gruppe '{device}' — ignoriert.")
        return targets

    # ── Volume/Mute/DND Callbacks ─────────────────────────────────────────────

    def _on_volume(device: Optional[str], level: int):
        nonlocal _global_volume
        if device:
            _device_volume[device] = level
            log.info(f"Lautstärke {device}: {level}%")
            all_devices = {**udp_server.registered_devices(), **grpc_servicer.proxy_satellites()}
            room = all_devices.get(device, "")
            grpc_servicer.agent_satellite_update(device, room, "", True, volume=level)
        else:
            _global_volume = level
            for d in _resolve_targets("all"):
                _device_volume[d] = level
                mqtt_handler.publish_volume_set(d, level)
            log.info(f"Lautstärke global: {level}%")

    def _on_mute(device: str, muted: bool):
        if _device_mute.get(device) == muted:
            return
        _device_mute[device] = muted
        log.info(f"Mute {device}: {muted}")
        all_devices = {**udp_server.registered_devices(), **grpc_servicer.proxy_satellites()}
        room = all_devices.get(device, "")
        grpc_servicer.agent_satellite_update(device, room, "", True, mute=muted)
        if room:
            for sibling, sibling_room in all_devices.items():
                if sibling != device and sibling_room.lower() == room.lower():
                    mqtt_handler.publish_mute_set(sibling, muted)
                    _device_mute[sibling] = muted

    def _on_dnd(device: str, active: bool):
        _device_dnd[device] = active
        mqtt_handler.publish_dnd_state(device, active)
        log.info(f"DND {device}: {active}")

    def _apply_global_dnd(active: bool):
        """Setzt DND auf allen bekannten Satelliten und publiziert den globalen State."""
        for device in _resolve_targets("all"):
            _device_dnd[device] = active
            mqtt_handler.publish_dnd_state(device, active)
        log.info(f"Globales DND: {active}")

    def _apply_global_mute(active: bool):
        """Setzt Mute auf allen bekannten Satelliten."""
        for device in _resolve_targets("all"):
            _device_mute[device] = active
            mqtt_handler.publish_mute_set(device, active)
        log.info(f"Globales Mute: {active}")

    # ── Announcements ─────────────────────────────────────────────────────────

    def process_announcement(device: str, text: str, *, ssml: bool = False):
        """Synthetisiert Text/SSML per TTS und sendet ihn an einen oder alle Satelliten."""
        if not tts.enabled:
            log.warning("Announcement ignoriert — TTS ist nicht konfiguriert.")
            return
        result = tts.synthesize_ssml(text) if ssml else tts.synthesize(text)
        if not result:
            return
        pcm, rate = _resample_to_16k(*result)
        targets = _resolve_targets(device)
        for target in targets:
            if _device_dnd.get(target):
                log.info(f"Announcement → {target} unterdrückt (DND aktiv).")
                continue
            _send_audio(target, pcm, rate)

    def process_room_announce(room: str, text: str):
        process_announcement(room, text)

    def process_ssml_announcement(room: str, ssml: str):
        process_announcement(room, ssml, ssml=True)

    mqtt_handler = MQTTHandler(cfg.get("mqtt", {}), audio_cfg)
    mqtt_handler.set_announcement_handler(process_announcement)
    mqtt_handler.set_room_announce_handler(process_room_announce)
    mqtt_handler.set_room_announce_ssml_handler(process_ssml_announcement)
    mqtt_handler.set_volume_handler(_on_volume)
    mqtt_handler.set_mute_handler(_on_mute)
    mqtt_handler.set_dnd_handler(_on_dnd)

    # BLE-Lokalisierung
    ble_cfg = cfg.get("ble", {})

    def _get_satellite_room(device: str) -> Optional[str]:
        all_devices = {**udp_server.registered_devices(), **grpc_servicer.proxy_satellites()}
        return all_devices.get(device)

    ble_engine = BleLocationEngine(ble_cfg, _get_satellite_room)
    alarm_manager = AlarmManager(
        persist_path=cfg.get("alarm", {}).get("persist", "alarms.json"),
        on_fire=lambda alarm_id, target: _handle_feedback(target, True, "Wecker! Guten Morgen!"),
    )
    timer_store = HannahTimerStore(
        db_path=cfg.get("timers", {}).get("db", "timers.db"),
    )

    def _on_ble_location_change(tag, room, satellite, rssi):
        room_str = room or ""
        sat_str = satellite or ""
        payload = json.dumps({"label": tag.label, "mac": tag.mac, "room": room_str,
                              "satellite": sat_str, "rssi": rssi}, ensure_ascii=False)
        mqtt_handler.publish_raw(f"hannah/ble/{tag.label}/location", payload)
        grpc_servicer.agent_ble_update(tag.label, tag.mac, room_str, sat_str, rssi)

    ble_engine.set_location_change_handler(_on_ble_location_change)
    mqtt_handler.set_ble_report_handler(ble_engine.on_report)

    # Connect-Sound: einmalig beim Start laden
    _connect_pcm: Optional[bytes] = None
    _connect_rate: int = 0
    _connect_sound_path = pathlib.Path(__file__).parent / "sounds" / "satellite_connected.wav"
    if _connect_sound_path.exists():
        try:
            with wave.open(str(_connect_sound_path), "rb") as _wf:
                _connect_pcm = _wf.readframes(_wf.getnframes())
                _connect_rate = _wf.getframerate()
            log.info(f"Connect-Sound geladen: {_connect_sound_path.name} ({_connect_rate} Hz)")
        except Exception as _exc:
            log.warning(f"Connect-Sound konnte nicht geladen werden: {_exc}")

    # Satellite-Online-Tracking: diff berechnen und per-device online/offline publishen
    _known_satellites: set[str] = set()
    _prev_satellite_map: dict[str, str] = {}

    def _on_satellite_change(satellite_map: dict[str, str]):
        nonlocal _known_satellites, _prev_satellite_map
        current = set(satellite_map.keys())
        ble_macs = ble_engine.get_all_macs()
        for device in current - _known_satellites:
            grpc_servicer.agent_satellite_update(device, satellite_map[device], "", True)
            if ble_macs:
                mqtt_handler.publish_ble_watchlist(device, ble_macs)
            if _connect_pcm:
                threading.Thread(
                    target=_send_audio,
                    args=(device, _connect_pcm, _connect_rate),
                    daemon=True,
                ).start()
        for device in _known_satellites - current:
            grpc_servicer.agent_satellite_update(device, _prev_satellite_map.get(device, ""), "", False)
        _known_satellites = current
        _prev_satellite_map = dict(satellite_map)
    def _rephrase_text(text: str) -> str:
        """Lässt Hannah (LLM) einen Announcement-Text frei umformulieren.
        Gibt den Originaltext zurück wenn kein LLM verfügbar oder ein Fehler auftritt."""
        if llm is None:
            return text
        try:
            prompt = (
                "Du bist Hannah, eine 24-jährige Mitbewohnerin. "
                "Formuliere den folgenden Satz kurz und natürlich um — "
                "du redest mit deiner Mitbewohnerin, nicht mit einem Kunden. "
                "Behalte alle konkreten Details bei. "
                "Antworte nur mit dem umformulierten Satz, ohne Erklärung."
            )
            result = llm.chat(text, system_prompt=prompt)
            return result.strip() if result and result.strip() else text
        except Exception as e:
            log.warning(f"LLM-Rephrase fehlgeschlagen, nutze Original: {e}")
            return text

    trigger_engine = TriggerEngine(
        path=cfg.get("triggers_file", "triggers.yaml"),
        announce_fn=process_announcement,
        rephrase_fn=_rephrase_text,
    )

    def _on_state_update(state_id: str, raw: str) -> None:
        iobroker.handle_state_update(state_id, raw)
        trigger_engine.on_state_update(state_id, raw)

    def _json_to_raw(json_value: str) -> str:
        """Decode a JSON-encoded gRPC state value to a plain string for legacy handlers."""
        import json as _json
        try:
            parsed = _json.loads(json_value)
            if isinstance(parsed, bool):
                return "true" if parsed else "false"
            return str(parsed)
        except (ValueError, TypeError):
            return json_value

    # ------------------------------------------------------------------
    # Voice-Pipeline für gRPC: OGG/Opus → STT → NLU → TTS → OGG/Opus
    # Wird von SubmitVoice (Telegram, zukünftige Services) genutzt.

    def _handle_voice(audio_ogg: bytes, speaker_roomie_id: str = "") -> tuple[str, str, str, bytes]:
        """OGG/Opus bytes → (transcript, answer, intent_name, audio_ogg_out)"""
        # OGG → raw PCM (16kHz, mono, s16le) via ffmpeg
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_ogg)
            ogg_path = f.name
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", ogg_path,
                 "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                capture_output=True,
            )
        finally:
            os.unlink(ogg_path)

        if proc.returncode != 0 or not proc.stdout:
            log.error(f"[grpc/voice] ffmpeg OGG→PCM fehlgeschlagen: {proc.stderr.decode()}")
            return "", "Ich konnte die Sprachnachricht nicht verarbeiten.", "Unknown", b""

        audio_array = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0

        try:
            transcript, _ = stt.transcribe(audio_array)
        except Exception as e:
            log.error(f"[grpc/voice] STT fehlgeschlagen: {e}")
            return "", "Ich konnte dich leider nicht verstehen.", "Unknown", b""

        if not transcript:
            return "", "Ich konnte dich leider nicht verstehen.", "Unknown", b""

        log.info(f"[grpc/voice] Transkript: {transcript!r}")
        answer, intent_name = _handle_text(transcript, speaker_roomie_id, source=speaker_roomie_id or "grpc-voice")

        # TTS → PCM → OGG/Opus via ffmpeg
        audio_ogg_out = b""
        if tts.enabled:
            result = tts.synthesize(answer)
            if result:
                pcm, sample_rate = result
                ff = subprocess.run(
                    ["ffmpeg", "-y",
                     "-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "-i", "pipe:0",
                     "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
                    input=pcm, capture_output=True,
                )
                if ff.returncode == 0:
                    audio_ogg_out = ff.stdout
                else:
                    log.warning(f"[grpc/voice] ffmpeg PCM→OGG fehlgeschlagen: {ff.stderr.decode()}")

        return transcript, answer, intent_name, audio_ogg_out

    def _resample_to_16k(pcm: bytes, rate: int) -> tuple[bytes, int]:
        if rate == 16000:
            return pcm, rate
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        new_len = int(len(samples) * 16000 / rate)
        resampled = np.interp(
            np.linspace(0, len(samples) - 1, new_len),
            np.arange(len(samples)),
            samples,
        ).astype(np.int16)
        return resampled.tobytes(), 16000

    def _handle_satellite_audio(device: str, pcm_bytes: bytes, speaker_roomie_id: str = "") -> tuple[str, str, str, bytes, int]:
        """
        Verarbeitet eine vollständige Satellit-Aufnahme via Go-Proxy:
        Raw PCM → STT → NLU → TTS → (transcript, answer, intent_name, tts_pcm, sample_rate)

        speaker_roomie_id: vom Proxy per Voice-ID identifizierter Sprecher (leer = anonym).
        """
        try:
            audio_array = audio_mod.from_raw_pcm(pcm_bytes, audio_cfg)
        except Exception as e:
            log.error(f"[{device}] Satellit-Audio-Konvertierung fehlgeschlagen: {e}")
            return "", "Fehler bei der Audio-Verarbeitung.", "Unknown", b"", 0

        try:
            transcript, _ = stt.transcribe(audio_array)
        except Exception as e:
            log.error(f"[{device}] STT fehlgeschlagen: {e}")
            return "", "Ich konnte dich leider nicht verstehen.", "Unknown", b"", 0

        if not transcript:
            return "", "Ich konnte dich leider nicht verstehen.", "Unknown", b"", 0

        log.info(f"[{device}] Satellit-Transkript: {transcript!r}"
                 + (f" (Sprecher: {speaker_roomie_id})" if speaker_roomie_id else ""))
        answer, intent_name = _handle_text(transcript, speaker_roomie_id=speaker_roomie_id, source=device)

        tts_pcm = b""
        sample_rate = 0
        if tts.enabled:
            result = tts.synthesize(answer)
            if result:
                tts_pcm, sample_rate = result
                tts_pcm, sample_rate = _resample_to_16k(tts_pcm, sample_rate)
                log.info(f"[{device}] TTS: {len(tts_pcm)} Bytes @ {sample_rate} Hz")
            else:
                log.warning(f"[{device}] TTS: synthesize() lieferte kein Ergebnis für Antwort: {answer!r}")
        else:
            log.debug(f"[{device}] TTS deaktiviert — keine Audio-Antwort")

        return transcript, answer, intent_name, tts_pcm, sample_rate

    udp_cfg = cfg.get("udp", {})
    _discovery_topic   = udp_cfg.get("discovery_topic", "hannah/server")
    _own_advertise_host = udp_cfg.get("advertise_host", "")
    _own_udp_port      = int(udp_cfg.get("port", 7775))

    def _on_proxy_discovery(host, port: int):
        """
        Wird vom RegisterProxy-Handler aufgerufen:
        - Proxy verbunden:  host/port sind die UDP-Adresse des Proxys → an Satelliten publizieren
        - Proxy getrennt:   host=None → eigene UDP-Adresse wiederherstellen
        """
        if host:
            log.info(f"Discovery: Proxy-Adresse publizieren → {host}:{port}")
            mqtt_handler.publish_discovery(udp_host=host, udp_port=port, topic=_discovery_topic)
        else:
            log.info("Discovery: eigene Hannah-Adresse wiederherstellen")
            mqtt_handler.publish_discovery(udp_host=_own_advertise_host, udp_port=_own_udp_port, topic=_discovery_topic)

    # ── ioBroker-Adapter gRPC-Callbacks ──────────────────────────────────────

    def _on_agent_state(state_id: str, value: str, *_):
        _on_state_update(state_id, value)
        # Route to handlers that expect slash-notation topics and plain string values
        topic = state_id.replace(".", "/")
        raw = _json_to_raw(value)
        if topic.startswith(weather.topic_prefix):
            weather.update(topic, raw)
        for _ct in car_manager:
            if topic.startswith(_ct.topic_prefix):
                _ct.update(topic, raw)

    def _on_agent_resident(roomie_id: str, presence_state: int, is_guest: bool):
        # Residents-Update via gRPC in bestehendes Update-System einleiten.
        # residents ist per late-binding sichtbar (wird kurz nach grpc_servicer gesetzt).
        if is_guest:
            topic = f"{residents.guest_topic_prefix}/{roomie_id}/{residents._state_key}"
        else:
            topic = f"{residents.topic_prefix_read}/{roomie_id}/{residents._state_key}"
        residents.update(topic, str(presence_state))

    def _on_agent_text_command(text: str) -> tuple[str, str]:
        return _handle_text(text, source="iobroker")

    def _on_agent_set_resident(resident_id: str, presence_state: int, _is_guest: bool):
        residents.set_presence(resident_id, presence_state)

    def _on_agent_satellite_control(room: str, key: str, value: object, device_id: str = ""):
        all_devices = {**udp_server.registered_devices(), **grpc_servicer.proxy_satellites()}
        if device_id:
            targets = [device_id] if device_id in all_devices else []
        else:
            targets = [d for d, r in all_devices.items() if room == "all" or r.lower() == room.lower()]
        if key == "mute":
            for d in targets:
                _device_mute[d] = bool(value)
                mqtt_handler.publish_mute_set(d, bool(value))
        elif key == "dnd":
            for d in targets:
                mqtt_handler.publish_dnd_state(d, bool(value))
        elif key == "volume":
            for d in targets:
                _device_volume[d] = int(value)
                mqtt_handler.publish_volume_set(d, int(value))
        elif key in ("announcement", "announcement_ssml", "announcement_rephrase"):
            if tts.enabled:
                text = str(value)
                if key == "announcement_rephrase":
                    text = _rephrase_text(text)
                result = (tts.synthesize_ssml(text) if key == "announcement_ssml"
                          else tts.synthesize(text))
                if result:
                    pcm, rate = _resample_to_16k(*result)
                    for d in targets:
                        _send_audio(d, pcm, rate, label="[satellite_control] ")
        log.info(f"[satellite_control] room={room!r} {key}={value!r} → {len(targets)} Satelliten")

    _iobroker_ready: bool = False

    def _on_timer_fired(timer_id: str, label: str):
        entry = timer_store.get(timer_id)
        if not entry:
            log.warning(f"[timer] TimerFired für unbekannte ID {timer_id!r} ({label!r}) — ignoriert.")
            return
        room = entry.get("room", "all")
        announce_label = entry.get("label") or label
        timer_store.remove(timer_id)
        targets = [d for d in _resolve_targets(room) if not _device_dnd.get(d)]

        # TTS vorab synthetisieren damit Jingle + TTS nahtlos aufeinanderfolgen
        tts_pcm: Optional[tuple] = None
        if tts.enabled:
            result = tts.synthesize(f"Dein Timer ist abgelaufen: {announce_label}.")
            if result:
                tts_pcm = _resample_to_16k(*result)

        jingle_duration = _asset_manifest.get("timer_jingle", {}).get("meta", {}).get("duration_s", 1.0)
        for device in targets:
            mqtt_handler.publish_play_asset(device, "timer_jingle")
        time.sleep(jingle_duration + 0.1)

        if tts_pcm:
            pcm, rate = tts_pcm
            for device in targets:
                _send_audio(device, pcm, rate)

    def _on_timer_connected():
        if _iobroker_ready:
            grpc_servicer.timer_send_ready()

    def _on_set_capture(device_id: str, enabled: bool, sample_type: str = "noise"):
        _device_dnd[device_id] = enabled
        mqtt_handler.publish_sampling_mode(device_id, enabled, sample_type)
        log.info(f"[capture] Satellit '{device_id}' Capture-Modus: {'an' if enabled else 'aus'} type={sample_type} (DND={'an' if enabled else 'aus'})")

    def _on_trigger_plink(device_id: str, record_duration: float):
        import time
        from hannah.plink import get_plink_pcm
        plink_wav = cfg.get("plink_wav_path", "")
        pcm, plink_duration = get_plink_pcm(plink_wav)
        _send_audio(device_id, pcm, 16000, label="[plink] ")
        time.sleep(plink_duration + 0.1)
        mqtt_handler.publish_virtual_ptt(device_id, True)
        log.info(f"[plink] Virtual PTT AN für {record_duration}s → {device_id}")
        time.sleep(record_duration)
        mqtt_handler.publish_virtual_ptt(device_id, False)
        log.info(f"[plink] Virtual PTT AUS → {device_id}")

    def _on_agent_device_snapshot(devices):
        nonlocal _iobroker_ready
        iobroker.handle_device_snapshot(devices)
        nlu._rooms = {**iobroker.rooms, **_group_pseudo_rooms}
        nlu._devices = iobroker.devices
        _iobroker_ready = True
        grpc_servicer.timer_send_ready()

    def _on_agent_connect():
        state_ids = trigger_engine.get_referenced_state_ids()
        if state_ids:
            log.info(f"[grpc] ioBroker-Adapter connected — WatchMore: {len(state_ids)} trigger states")
            grpc_servicer.agent_watch_more(list(state_ids))
        for tag, room, satellite, rssi in ble_engine.get_current_locations():
            grpc_servicer.agent_ble_update(tag.label, tag.mac, room or "", satellite or "", rssi)

    # gRPC-Servicer wird hier erstellt damit _on_arrival/_on_departure Events pushen können.
    # get_satellites und get_car_state sind Lambdas (late binding) — udp_server ist
    # zum Zeitpunkt des Aufrufs bereits gesetzt.
    grpc_servicer = HannahServicer(
        registry=registry,
        handle_text=_handle_text,
        handle_voice=_handle_voice,
        announce=process_announcement,
        notificate=lambda text, severity: process_notification(text, severity),
        get_satellites=lambda: {
            **udp_server.registered_devices_full(),
            **{dev: {"room": info["room"], "addr": info["addr"]} for dev, info in grpc_servicer.proxy_satellites_full().items()},
        },
        get_car_state=lambda: car_manager.first_state,
        get_all_cars=lambda: [(t.state, t.home_address) for t in car_manager],
        handle_satellite_audio=_handle_satellite_audio,
        disable_udp=lambda: udp_server.stop(),
        enable_udp=lambda: udp_server.start(),
        on_proxy_discovery=_on_proxy_discovery,
        on_satellite_change=_on_satellite_change,
        get_devices=lambda: iobroker.get_devices_snapshot(),
        control_device=lambda device_id, state, value: iobroker.control_direct(device_id, state, value),
        on_agent_state=_on_agent_state,
        on_agent_resident=_on_agent_resident,
        on_agent_text_command=_on_agent_text_command,
        on_agent_connect=_on_agent_connect,
        on_agent_set_resident=_on_agent_set_resident,
        on_agent_satellite_control=_on_agent_satellite_control,
        on_agent_device_snapshot=_on_agent_device_snapshot,
        on_agent_send_residents=registry.sync,
        on_trigger_firmware_update=lambda device: mqtt_handler.publish_ota_ok(device),
        on_timer_fired=_on_timer_fired,
        on_timer_connected=_on_timer_connected,
        on_set_capture=_on_set_capture,
        on_trigger_plink=_on_trigger_plink,
    )

    iobroker.set_setter(grpc_servicer.agent_set_state)

    # ------------------------------------------------------------------
    # Residents + Callbacks (referenzieren grpc_servicer für Event-Push)
    # Presence-Updates kommen via gRPC (_on_agent_resident); MQTT wird nur noch
    # für das Zurückschreiben von Presence-States in den Residents-Adapter genutzt.

    residents = ResidentsClient(cfg.get("residents", {}))
    residents.set_setter(grpc_servicer.agent_set_resident)

    def _on_arrival(name: str):
        process_announcement("all", "Willkommen zuhause!")
        user = registry.get_by_roomie(name)
        display = user["display_name"] if user else name
        grpc_servicer.publish_event(make_resident_event(name, display, "arrived"))

    _satellite_firmware: dict[str, str] = {}

    def _on_firmware_version(device: str, version: str):
        _satellite_firmware[device] = version
        log.info(f"Firmware-Version: {device} = {version}")
        grpc_servicer.publish_event(make_firmware_event(device, version))
        grpc_servicer.agent_firmware_event(device, version)

    _ota_pending: set[str] = set()

    def _release_ota_updates():
        for device in list(_ota_pending):
            mqtt_handler.publish_ota_ok(device)
            _ota_pending.discard(device)

    def _on_ota_pending(device: str, version: str):
        log.info(f"OTA-Pending: {device} meldet Version {version}.")
        grpc_servicer.agent_firmware_event(device, version, update_available=True)
        if not residents.is_home():
            mqtt_handler.publish_ota_ok(device)
        else:
            log.info(f"OTA-Pending: jemand zuhause — {device} wartet auf Freigabe.")
            _ota_pending.add(device)

    def _on_departure(name: str):
        log.info(f"Residents: {name} hat das Haus verlassen.")
        user = registry.get_by_roomie(name)
        display = user["display_name"] if user else name
        grpc_servicer.publish_event(make_resident_event(name, display, "departed"))
        if not residents.is_home() and _ota_pending:
            log.info("Alle weg — OTA-Updates freigeben.")
            _release_ota_updates()

    def _on_guest_arrival(name: str):
        process_announcement("all", "Es ist Besuch angekommen!")
        grpc_servicer.publish_event(make_resident_event(f"guest:{name}", name, "arrived"))

    def _on_guest_departure(name: str):
        log.info(f"Residents: Gast '{name}' ist gegangen.")
        grpc_servicer.publish_event(make_resident_event(f"guest:{name}", name, "departed"))

    def _on_sensor(device: str, temperature: float, pressure: float,
                   humidity: float, gas_resistance: float):
        grpc_servicer.agent_sensor_update(device, temperature, pressure, humidity, gas_resistance)

    mqtt_handler.set_ota_pending_handler(_on_ota_pending)
    mqtt_handler.set_firmware_handler(_on_firmware_version)
    mqtt_handler.set_sensor_handler(_on_sensor)
    residents.on_arrival(_on_arrival)
    residents.on_departure(_on_departure)
    residents.on_guest_arrival(_on_guest_arrival)
    residents.on_guest_departure(_on_guest_departure)

    # Auto-Einpark-Event → gRPC-Stream (pro Tracker, damit home_address bekannt ist)
    for _ct in car_manager:
        def _make_parked_cb(tracker=_ct):
            def _cb(state):
                grpc_servicer.publish_event(make_car_parked_event(state, tracker.home_address))
            return _cb
        _ct.on_parked(_make_parked_cb())

    # ------------------------------------------------------------------
    # System-Notification Pipeline (hannah/notification)

    def process_notification(raw_text: str, severity: str = "notify"):
        """
        Empfängt rohen Notification-Text aus ioBroker, formuliert ihn per LLM um,
        spielt ihn auf DND-freien Satelliten ab und pusht ihn per gRPC an Telegram-Nutzer
        mit system_messages=True.

        severity="direct": LLM wird übersprungen, Text wird unverändert weitergeleitet.
        """
        # Direct-Modus: kein LLM, aber TTS + Telegram wie normale Notification
        if severity == "direct":
            log.info(f"Direct-Notification: {raw_text!r}")
            if tts.enabled:
                result = tts.synthesize(raw_text)
                if result:
                    pcm, rate = _resample_to_16k(*result)
                    for target in _resolve_targets("all"):
                        if not _device_dnd.get(target):
                            _send_audio(target, pcm, rate)
            grpc_servicer.publish_event(make_system_notification_event(raw_text))
            return

        # LLM-Reformulierung (optional — wenn kein LLM verfügbar: rohen Text nutzen)
        text = raw_text
        if llm is not None:
            try:
                _tone = {
                    "alert":  "Drücke dich dabei klar und direkt aus, zeig dass es wichtig ist.",
                    "notify": "Drücke dich locker und direkt aus, wie eine Mitbewohnerin die kurz Bescheid gibt.",
                    "info":   "Drücke dich beiläufig aus, als würdest du es nebenbei erwähnen.",
                }.get(severity, "Drücke dich locker und direkt aus.")
                notification_prompt = (
                    "Du bist Hannah, eine 24-jährige Mitbewohnerin. "
                    "Formuliere die folgende Systemmeldung kurz und natürlich um — "
                    "du redest mit deiner Mitbewohnerin, nicht mit einem Kunden. "
                    "Behalte dabei alle konkreten Details wie Adapter-Namen und Versionsnummern bei. "
                    "Datumsangaben im Format M/D/YYYY oder M/D/YYYY, H:MM:SS AM/PM sind Zeitstempel — "
                    "nenne sie als Datum oder Uhrzeit, nicht als Versionsnummer. "
                    "Technische Präfixe wie 'system.host.XYZ: adapter.0:' sind Herkunftsangaben und "
                    "müssen nicht wörtlich übernommen werden. "
                    "Leere Felder wie 'onedrive: {}' bedeuten keine Fehler dort — erwähne sie nur "
                    "wenn es relevant ist. "
                    f"{_tone} "
                    "Antworte nur mit dem umformulierten Satz, ohne Erklärung."
                )
                reformulated = llm.chat(raw_text, system_prompt=notification_prompt)
                if reformulated and reformulated.strip():
                    text = reformulated.strip()
            except Exception as e:
                log.warning(f"LLM-Reformulierung fehlgeschlagen, verwende Originaltext: {e}")

        log.info(f"System-Notification: {text!r}")

        # TTS auf DND-freien Satelliten
        if tts.enabled:
            result = tts.synthesize(text)
            if result:
                pcm, rate = _resample_to_16k(*result)
                for target in _resolve_targets("all"):
                    if not _device_dnd.get(target):
                        _send_audio(target, pcm, rate)

        # gRPC-Event → Telegram
        grpc_servicer.publish_event(make_system_notification_event(text))

    mqtt_handler.set_notification_handler(process_notification)

    mqtt_handler.connect()

    # ------------------------------------------------------------------
    # UDP-Pfad

    def process_audio_udp(device: str, raw_pcm: bytes):
        try:
            audio_array = audio_mod.from_raw_pcm(raw_pcm, audio_cfg)
        except Exception as e:
            log.error(f"[{device}] UDP Audio-Konvertierung fehlgeschlagen: {e}")
            return

        if len(audio_array) == 0:
            return

        pipeline(
            device,
            audio_array,
            publish_error   = lambda m: log.error(f"[{device}] {m}"),
            publish_answer  = lambda a: _handle_udp_answer(device, a),
        )

    def _handle_udp_answer(device: str, answer: str):
        if tts.enabled:
            result = tts.synthesize(answer)
            if result:
                pcm, rate = result
                udp_server.send_tts(device, pcm, sample_rate=rate)

    def _handle_feedback(satellite_device: str, is_success: bool, text: str):
        """
        Feedback-Handler für erfolgreiche Steuerung und Fehler:
        - is_success=True + text: Smalltalk (Text sprechen)
        - is_success=True + kein text: Erfolgreiche Steuerung (Confirmation-Ton)
        - is_success=False + text: Fehler (Text sprechen)
        """
        log.info(f"[{satellite_device}] Feedback: {'✓' if is_success else '✗'} — {text}")

        if is_success and not text:
            # Erfolgreiche Steuerung: Confirmation-Ton
            if tts.enabled:
                pcm, rate = tts.confirmation_tone()
                udp_server.send_tts(satellite_device, pcm, sample_rate=rate)
        elif text and tts.enabled:
            # Smalltalk oder Fehler: Text sprechen
            result = tts.synthesize(text)
            if result:
                pcm, rate = result
                udp_server.send_tts(satellite_device, pcm, sample_rate=rate)

    feedback_timeout = cfg.get("iobroker", {}).get("feedback_timeout", 3.0)
    iobroker.set_feedback_handler(_handle_feedback, timeout=feedback_timeout)

    tts.warm_cache(cfg.get("tts", {}).get("warm_phrases", []))

    udp_server = UDPServer(
        cfg.get("udp", {}),
        process_audio_udp,
        on_satellite_change=_on_satellite_change,
    )
    udp_server.start()

    # Discovery: eigene UDP-Adresse als retained MQTT-Message publizieren.
    # Wenn später ein Proxy verbindet, überschreibt _on_proxy_discovery diesen Wert.
    mqtt_handler.publish_discovery(
        udp_host=_own_advertise_host,
        udp_port=_own_udp_port,
        topic=_discovery_topic,
    )
    log.info(f"Satelliten finden Hannah über MQTT-Topic: {_discovery_topic}")

    residents.announce_online()
    log.info(f"Residents: Hannah online ({residents.topic_prefix_read}/{residents.hannah_name}/state)")

    # ------------------------------------------------------------------
    # gRPC-Server starten

    grpc_srv = GrpcServer(cfg.get("grpc", {}), grpc_servicer)
    grpc_srv.start()

    # ------------------------------------------------------------------
    # Graceful Shutdown

    stop = threading.Event()

    def on_signal(sig, frame):
        log.info("Shutdown ...")
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    log.info("hannah läuft. CTRL+C zum Beenden.")
    stop.wait()

    residents.announce_offline()
    grpc_srv.stop()
    udp_server.stop()
    mqtt_handler.disconnect()
    log.info("Beendet.")


if __name__ == "__main__":
    main()
