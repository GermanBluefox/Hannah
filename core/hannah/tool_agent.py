"""LLM Tool Agent — wertet komplexe Anfragen per Tool-Use-Loop aus.

Das NLU delegiert an den ToolAgent wenn kein Intent erkannt wurde.
Der Agent hat Zugriff auf Hannah-interne Daten (Gerätecache, Setter)
und gibt niemals direkt an ioBroker weiter — alles läuft über Hannah.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLMClient
    from .iobroker import IoBrokerClient

log = logging.getLogger(__name__)

_MAX_ITERATIONS = 3

_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_all_devices",
            "description": (
                "Gibt alle bekannten Smart-Home-Geräte mit Metadaten zurück "
                "(ID, Name, Raum, Etage, Kategorie, verfügbare State-Suffixe). "
                "Rufe das auf bevor du States setzt, um gültige IDs zu kennen. "
                "Aktuelle Zustandswerte sind nicht enthalten — dafür get_device_state verwenden."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device_state",
            "description": "Gibt den aktuellen Zustand (alle State-Werte) eines Geräts zurück.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Die Geräte-ID aus get_all_devices",
                    }
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_device_state",
            "description": (
                "Setzt einen State eines Geräts. "
                "Die state_id ergibt sich aus device_id + '.' + State-Suffix "
                "(z.B. 'javascript.0.virtualDevice.Licht.EG.Wohnzimmer.Decke.on')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state_id": {
                        "type": "string",
                        "description": "Vollständige State-ID (Device-ID + Punkt + State-Suffix)",
                    },
                    "value": {
                        "description": "Wert: true/false für on, 0–100 für level, Hex-String für color",
                    },
                },
                "required": ["state_id", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "speak",
            "description": (
                "Lässt Hannah einen Text sprechen (TTS). "
                "Nutze das für Rückmeldungen an den Nutzer — "
                "z.B. um zu berichten was getan wurde oder eine Frage zu stellen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Der Text den Hannah sprechen soll",
                    }
                },
                "required": ["text"],
            },
        },
    },
]


class ToolAgent:
    """
    Führt einen Tool-Use-Loop gegen ein LLMClient-Backend durch.

    Hannah-interne Tools werden direkt dispatcht; das LLM kennt ioBroker nicht.
    """

    def __init__(self, llm: "LLMClient", iobroker: "IoBrokerClient") -> None:
        self._llm = llm
        self._iobroker = iobroker

    def run(
        self,
        text: str,
        system_prompt: str = "",
        history: list[dict] | None = None,
    ) -> str:
        """
        Startet den Tool-Loop für `text`.
        Gibt den endgültigen Antworttext zurück (wird vom Aufrufer per TTS gesprochen).
        """
        spoken: list[str] = []

        _TOOL_RULES = (
            "\n\nRegeln für Tool-Nutzung:"
            "\n- Nutze das speak-Tool um deine Antwort auszugeben."
            "\n- Rufe nie dasselbe Tool zweimal hintereinander auf."
            "\n- Nach dem Sammeln aller nötigen Informationen: speak aufrufen und danach stoppen."
        )

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt + _TOOL_RULES})
        else:
            messages.append({"role": "system", "content": _TOOL_RULES.lstrip()})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": text})

        for i in range(_MAX_ITERATIONS):
            log.info("[tool_agent] Iteration %d/%d", i + 1, _MAX_ITERATIONS)
            response = self._llm.chat_with_tools(messages, _TOOLS)
            log.info("[tool_agent] finish_reason=%s tool_calls=%d", response.get("finish_reason"), len(response.get("tool_calls") or []))
            tool_calls: list[dict] = response.get("tool_calls") or []

            if not tool_calls:
                final = response.get("content", "")
                return "\n".join(spoken) if spoken else final

            # Assistent-Nachricht mit tool_calls in History aufnehmen
            messages.append(
                {
                    "role": "assistant",
                    "content": response.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )

            for call in tool_calls:
                call_id: str = call.get("id", "")
                func_name: str = call.get("function", {}).get("name", "")
                try:
                    args: dict = json.loads(call.get("function", {}).get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                result = self._dispatch(func_name, args, spoken)
                log.debug("[tool_agent] %s(%s) → %s", func_name, args, result)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        log.warning("[tool_agent] Max Iterationen (%d) erreicht ohne finale Antwort", _MAX_ITERATIONS)
        return "\n".join(spoken) if spoken else ""

    # ------------------------------------------------------------------
    # Tool-Dispatch

    def _dispatch(self, name: str, args: dict, spoken: list[str]) -> object:
        if name == "get_all_devices":
            return self._get_all_devices()
        if name == "get_device_state":
            return self._get_device_state(args.get("device_id", ""))
        if name == "set_device_state":
            return self._set_device_state(args.get("state_id", ""), args.get("value"))
        if name == "speak":
            text = str(args.get("text", ""))
            spoken.append(text)
            return {"ok": True}
        return {"error": f"Unbekanntes Tool: {name}"}

    def _get_all_devices(self) -> list[dict]:
        result: list[dict] = []
        for room_key, devs in self._iobroker.devices.items():
            room_name = self._iobroker.rooms.get(room_key, room_key)
            for dev in devs.values():
                result.append(
                    {
                        "id": dev.id,
                        "name": dev.name,
                        "room": room_name,
                        "floor": dev.floor,
                        "category": dev.category,
                        "state_keys": list(dev.states.keys()),
                    }
                )
        return result

    def _get_device_state(self, device_id: str) -> dict:
        dev = self._iobroker._devices_by_id.get(device_id)
        if not dev:
            return {"error": f"Gerät '{device_id}' nicht gefunden"}
        return {
            "id": dev.id,
            "name": dev.name,
            "room": dev.room,
            "current": dev.current,
        }

    def _set_device_state(self, state_id: str, value: object) -> dict:
        ok = self._iobroker.set_state(state_id, value)
        return {"ok": ok}
