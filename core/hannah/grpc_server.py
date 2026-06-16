"""
Hannah gRPC Server

Exposes HannahService to external services (Telegram bot, web UI, …).
Runs in its own thread pool alongside the main event loop.
"""
import logging
import queue
import threading
from concurrent import futures
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

import grpc

from hannah.proto import hannah_pb2 as pb
from hannah.proto import hannah_pb2_grpc as pb_grpc
from hannah.user_registry import UserRegistry

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Event subscriber (one per connected SubscribeEvents call)

class _Subscriber:
    def __init__(self, event_types: list[str]):
        # Empty list = subscribe to all
        self._filter: Optional[set[str]] = set(event_types) if event_types else None
        self._queue: queue.Queue = queue.Queue()

    def put(self, event: pb.HannahEvent):
        if self._filter is None or event.event_type in self._filter:
            self._queue.put(event)

    def close(self):
        self._queue.put(None)  # sentinel — ends the generator

    def get(self, timeout: float = 1.0) -> Optional[pb.HannahEvent]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return queue.Empty  # sentinel-like, caller checks


# ------------------------------------------------------------------
# Servicer

class HannahServicer(pb_grpc.HannahServiceServicer):
    """
    gRPC service implementation.

    All heavy work is delegated to callbacks passed in from main.py so this
    class stays free of business logic and is easy to test in isolation.
    """

    def __init__(
        self,
        registry: UserRegistry,
        handle_text: Callable[[str], tuple[str, str]],
        handle_voice: Callable[[bytes], tuple[str, str, str, bytes]],
        announce: Callable[[str, str], None],
        notificate: Callable[[str, str], None],
        get_satellites: Callable[[], dict],
        get_car_state: Callable[[], Optional[object]],      # → CarState | None (erster Tracker)
        get_all_cars: Optional[Callable[[], list]] = None,  # → [(CarState, home_address)]
        handle_satellite_audio: Optional[Callable] = None,  # (device, room, pcm) → (transcript, answer, intent, pcm, rate)
        disable_udp: Optional[Callable[[], None]] = None,
        enable_udp: Optional[Callable[[], None]] = None,
        on_proxy_discovery: Optional[Callable[[str, int], None]] = None,  # (host, port) — None args = restore own address
        get_devices: Optional[Callable[[], list]] = None,           # → [{key,name,devices:[...]}]
        control_device: Optional[Callable[[str, str, str], bool]] = None,  # (device_id, state, value) → bool
        enroll_voiceprint: Optional[Callable[[str, bytes, int], tuple]] = None,  # (roomie_id, pcm, rate) → (ok, msg)
        on_satellite_change: Optional[Callable[[dict], None]] = None,           # ({device: room}) bei Register/Disconnect via Proxy
        on_agent_state: Optional[Callable[[str, str, bool, int], None]] = None,      # (state_id, value, ack, ts)
        on_agent_resident: Optional[Callable[[str, int, bool], None]] = None,        # (roomie_id, presence_state, is_guest)
        on_agent_text_command: Optional[Callable[[str], tuple[str, str]]] = None,    # (text) → (answer, intent)
        on_agent_connect: Optional[Callable[[], None]] = None,                       # called on each new adapter connection
        on_agent_set_resident: Optional[Callable[[str, int, bool], None]] = None,    # (resident_id, presence_state, is_guest)
        on_agent_satellite_control: Optional[Callable[[str, str, object], None]] = None,  # (room, key, value)
        on_agent_device_snapshot: Optional[Callable[[Iterable[pb.AgentDevice]], None]] = None,
        on_agent_send_residents: Optional[Callable[[Iterable[pb.AgentResident]], None]] = None,
        on_trigger_firmware_update: Optional[Callable[[str], None]] = None,  # (device)
        on_timer_fired: Optional[Callable[[str, str], None]] = None,          # (timer_id, label)
        on_timer_list: Optional[Callable[[list], None]] = None,               # (list[TimerInfo])
        on_timer_connected: Optional[Callable[[], None]] = None,
        on_set_capture: Optional[Callable[[str, bool, str], None]] = None,     # (device_id, enabled, sample_type) — set DND + satellite MQTT
        on_trigger_plink: Optional[Callable[[str, float], None]] = None,       # (device_id, record_duration_s)
        on_agent_ask_resident: Optional[Callable[[str, str, str], None]] = None,  # (correlation_id, room, question)
    ):
        self._registry              = registry
        self._handle_text           = handle_text
        self._handle_voice          = handle_voice
        self._announce              = announce
        self._notificate            = notificate
        self._get_satellites        = get_satellites
        self._get_car_state         = get_car_state
        self._get_all_cars          = get_all_cars or (lambda: [])
        self._handle_satellite_audio = handle_satellite_audio
        self._disable_udp           = disable_udp or (lambda: None)
        self._enable_udp            = enable_udp or (lambda: None)
        self._on_proxy_discovery    = on_proxy_discovery or (lambda *_: None)
        self._get_devices           = get_devices or (lambda: [])
        self._control_device        = control_device or (lambda *_: False)
        self._enroll_voiceprint     = enroll_voiceprint
        self._on_satellite_change   = on_satellite_change
        self._on_agent_state        = on_agent_state
        self._on_agent_resident     = on_agent_resident
        self._on_agent_text_command = on_agent_text_command
        self._on_agent_connect           = on_agent_connect
        self._on_agent_set_resident      = on_agent_set_resident
        self._on_agent_satellite_control = on_agent_satellite_control
        self._on_agent_device_snapshot    = on_agent_device_snapshot
        self._on_agent_send_residents     = on_agent_send_residents
        self._on_trigger_firmware_update  = on_trigger_firmware_update or (lambda _: None)
        self._on_timer_fired    = on_timer_fired
        self._on_timer_list     = on_timer_list
        self._on_timer_connected = on_timer_connected
        self._on_set_capture          = on_set_capture or (lambda *_: None)
        self._on_trigger_plink        = on_trigger_plink or (lambda *_: None)
        self._on_agent_ask_resident   = on_agent_ask_resident

        self._subscribers: list[_Subscriber] = []
        self._subs_lock = threading.Lock()


        # Satelliten die der Proxy gemeldet hat: {device: {"room": str, "addr": str}}
        self._proxy_satellites: dict[str, dict] = {}
        self._proxy_sat_lock = threading.Lock()

        # Per-connection command queues for active proxy streams
        self._proxy_queues: list[queue.Queue] = []
        self._proxy_lock = threading.Lock()

        # Per-connection command queues for active agent streams
        self._agent_queues: list[queue.Queue] = []
        self._agent_lock = threading.Lock()

        # Single queue for the connected Timer Service (at most one at a time)
        self._timer_queue: Optional[queue.Queue] = None
        self._timer_lock = threading.Lock()

        # Captured satellites: device_id → audio queue (SatelliteAudioChunk)
        self._captured_satellites: dict[str, queue.Queue] = {}
        self._capture_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public: proxy helpers (called from main.py)

    def has_proxy(self) -> bool:
        """True if at least one proxy stream is currently connected."""
        with self._proxy_lock:
            return len(self._proxy_queues) > 0

    def proxy_satellites(self) -> dict[str, str]:
        """Aktuell vom Proxy gemeldete Satelliten: {device: room}."""
        with self._proxy_sat_lock:
            return {dev: info["room"] for dev, info in self._proxy_satellites.items()}

    def proxy_satellites_full(self) -> dict[str, dict]:
        """Aktuell vom Proxy gemeldete Satelliten: {device: {"room": str, "addr": str}}."""
        with self._proxy_sat_lock:
            return dict(self._proxy_satellites)

    def push_audio_to_proxy(self, device_id: str, pcm: bytes, sample_rate: int):
        """Push a single PlayAudioCommand (full PCM, is_last=True) to all connected proxy streams."""
        cmd = pb.ProxyCommand(
            play_audio=pb.PlayAudioCommand(
                device_id=device_id,
                audio_pcm=pcm,
                sample_rate=sample_rate,
                is_last=True,
            )
        )
        with self._proxy_lock:
            for q in list(self._proxy_queues):
                q.put(cmd)

    def stream_audio_to_proxy(self, device_id: str, pcm: bytes, sample_rate: int,
                               chunk_size: int = 4800):
        """Slice PCM into chunks and push one PlayAudioCommand per chunk.

        Chunks arrive at the proxy in order; the proxy forwards each to the satellite
        immediately so playback can start before the full TTS response is sent.
        chunk_size=4800 ≈ 100ms @ 24kHz 16-bit mono.
        """
        if not pcm:
            return
        with self._proxy_lock:
            queues = list(self._proxy_queues)
        if not queues:
            return
        offset = 0
        total = len(pcm)
        while offset < total:
            end = min(offset + chunk_size, total)
            chunk = pcm[offset:end]
            is_last = end >= total
            cmd = pb.ProxyCommand(
                play_audio=pb.PlayAudioCommand(
                    device_id=device_id,
                    audio_pcm=chunk,
                    sample_rate=sample_rate,
                    is_last=is_last,
                )
            )
            for q in queues:
                q.put(cmd)
            offset = end

    # ------------------------------------------------------------------
    # Public: push an event to all matching subscribers

    def publish_event(self, event: pb.HannahEvent):
        """Called by Hannah core when something notable happens."""
        with self._subs_lock:
            for sub in list(self._subscribers):
                sub.put(event)

    # ------------------------------------------------------------------
    # User Registry

    def GetUsers(self, request, _context):
        users = self._registry.get_all(include_inactive=request.include_inactive)
        return pb.GetUsersResponse(users=[_user_to_pb(u) for u in users])

    def GetUser(self, request, context):
        lookup = request.WhichOneof("lookup")
        if lookup == "roomie_id":
            raw = self._registry.get_by_roomie(request.roomie_id)
        elif lookup == "uuid":
            raw = self._registry.get_by_uuid(request.uuid)
        elif lookup == "linked_account":
            la = request.linked_account
            raw = self._registry.get_by_linked_account(la.service, la.account_id)
        else:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Exactly one lookup field must be set.")
            return pb.UserResponse()

        if raw is None:
            return pb.UserResponse(found=False)
        return pb.UserResponse(found=True, user=_user_to_pb(raw))

    def LinkAccount(self, request, _context):
        ok = self._registry.link_account(request.roomie_id, request.service, request.account_id)
        msg = "verknüpft" if ok else f"Roomie {request.roomie_id!r} nicht gefunden"
        return pb.StatusResponse(ok=ok, message=msg)

    def UnlinkAccount(self, request, _context):
        ok = self._registry.unlink_account(request.service, request.account_id)
        msg = "entfernt" if ok else "Account nicht gefunden"
        return pb.StatusResponse(ok=ok, message=msg)

    def SetTrustLevel(self, request, _context):
        ok = self._registry.set_trust_level(request.roomie_id, request.level)
        msg = "aktualisiert" if ok else f"Roomie {request.roomie_id!r} nicht gefunden"
        return pb.StatusResponse(ok=ok, message=msg)

    def SetSystemMessages(self, request, _context):
        ok = self._registry.set_system_messages(request.roomie_id, request.enabled)
        msg = "aktualisiert" if ok else f"Roomie {request.roomie_id!r} nicht gefunden"
        return pb.StatusResponse(ok=ok, message=msg)

    # ------------------------------------------------------------------
    # Control

    def _roomie_from_request(self, source_service: str, source_user_id: str) -> str:
        """Löst source_service + source_user_id via linked_accounts auf eine roomie_id auf."""
        if not source_service or not source_user_id:
            return ""
        user = self._registry.get_by_linked_account(source_service, source_user_id)
        return user.get("roomie_id", "") if user else ""

    def SubmitText(self, request, _context):
        roomie_id = self._roomie_from_request(request.source_service, request.source_user_id)
        log.info(
            f"[grpc] SubmitText von {request.source_service}:{request.source_user_id}"
            f" (roomie={roomie_id or 'anonym'}) — {request.text!r}"
        )
        answer, intent_name = self._handle_text(request.text, roomie_id)
        return pb.SubmitTextResponse(answer=answer, intent_name=intent_name)

    def SubmitVoice(self, request, _context):
        roomie_id = self._roomie_from_request(request.source_service, request.source_user_id)
        log.info(
            f"[grpc] SubmitVoice von {request.source_service}:{request.source_user_id}"
            f" (roomie={roomie_id or 'anonym'}, {len(request.audio)} bytes)"
        )
        transcript, answer, intent_name, audio_ogg = self._handle_voice(request.audio, roomie_id)
        return pb.SubmitVoiceResponse(
            transcript=transcript,
            answer=answer,
            intent_name=intent_name,
            audio_ogg=audio_ogg,
        )

    def Announce(self, request, _context):
        try:
            self._announce(request.device, request.text)
            return pb.StatusResponse(ok=True, message="gesendet")
        except Exception as e:
            log.error(f"[grpc] Announce fehlgeschlagen: {e}")
            return pb.StatusResponse(ok=False, message=str(e))

    def Notify(self, request, _context):
        if not self._notificate:
            return pb.StatusResponse(ok=False, message="notification not configured")
        try:
            severity = "direct" if request.direct else (request.severity or "notify")
            log.info(f"[grpc] Notify empfangen: severity={severity!r} text={request.text!r}")
            threading.Thread(
                target=self._notificate, args=(request.text, severity), daemon=True
            ).start()
            return pb.StatusResponse(ok=True, message="queued")
        except Exception as e:
            log.error(f"[grpc] Notify fehlgeschlagen: {e}")
            return pb.StatusResponse(ok=False, message=str(e))

    def GetSatellites(self, _request, _context):
        sats = self._get_satellites()
        result = [
            pb.Satellite(device_id=dev, room=info.get("room", ""), address=info.get("addr", ""))
            for dev, info in sats.items()
        ]
        return pb.GetSatellitesResponse(satellites=result)

    def TriggerFirmwareUpdate(self, request, _context):
        device = request.device
        if not device:
            return pb.StatusResponse(ok=False, message="device required")
        self._on_trigger_firmware_update(device)
        return pb.StatusResponse(ok=True, message=f"OTA-OK gesendet an {device}")

    def GetDevices(self, _request, _context):
        rooms_raw = self._get_devices()
        rooms_pb = []
        for r in rooms_raw:
            devices_pb = [
                pb.DeviceInfo(
                    id=d["id"],
                    name=d["name"],
                    category=d["category"],
                    states=d["states"],
                    current=d["current"],
                )
                for d in r["devices"]
            ]
            rooms_pb.append(pb.RoomInfo(key=r["key"], name=r["name"], devices=devices_pb))
        return pb.GetDevicesResponse(rooms=rooms_pb)

    def ControlDevice(self, request, _context):
        log.info(
            f"[grpc] ControlDevice: device={request.device_id!r}"
            f" state={request.state!r} value={request.value!r}"
        )
        ok = self._control_device(request.device_id, request.state, request.value)
        msg = "OK" if ok else "Gerät oder State nicht gefunden"
        return pb.StatusResponse(ok=ok, message=msg)

    # ------------------------------------------------------------------
    # Car

    def GetCarState(self, _request, _context):
        cars = self._get_all_cars()
        if cars:
            state, home = cars[0]
            if state is not None and state.available:
                return pb.CarStateResponse(available=True, state=_car_to_pb(state, home))
        return pb.CarStateResponse(available=False)

    def GetAllCarStates(self, _request, _context):
        protos = [
            _car_to_pb(state, home)
            for state, home in self._get_all_cars()
            if state is not None and state.available
        ]
        return pb.GetAllCarStatesResponse(states=protos)

    # ------------------------------------------------------------------
    # Event stream

    def SubscribeEvents(self, request, context):
        sub = _Subscriber(list(request.event_types))
        with self._subs_lock:
            self._subscribers.append(sub)
        log.info(f"[grpc] Neuer Event-Subscriber (filter={list(request.event_types) or 'alle'})")

        try:
            while context.is_active():
                result = sub.get(timeout=1.0)
                if result is None:
                    break           # sentinel: server closed the stream
                if result is queue.Empty:
                    continue        # timeout, check context.is_active() again
                yield result
        finally:
            with self._subs_lock:
                if sub in self._subscribers:
                    self._subscribers.remove(sub)
            log.info("[grpc] Event-Subscriber getrennt")

    # ------------------------------------------------------------------
    # Satellite Proxy

    def RegisterProxy(self, request_iterator, context):
        """
        Bidirectional stream: proxy → heartbeats, Hannah → ProxyCommand.

        On first connection Hannah disables its UDP server.
        On last disconnection Hannah re-enables it.
        """
        q: queue.Queue = queue.Queue()
        with self._proxy_lock:
            self._proxy_queues.append(q)
            is_first = len(self._proxy_queues) == 1

        if is_first:
            log.info("[grpc] Erster Proxy verbunden — UDP-Server wird deaktiviert")
            self._disable_udp()

        # Send initial ACK
        yield pb.ProxyCommand(
            ack=pb.ProxyAck(udp_disabled=True, message="UDP-Server gestoppt")
        )

        proxy_id = "unknown"

        def _drain():
            nonlocal proxy_id
            discovery_published = False
            try:
                for hb in request_iterator:
                    proxy_id = hb.proxy_id
                    log.debug(f"[grpc] Heartbeat von Proxy '{proxy_id}'")
                    if not discovery_published and hb.udp_host and hb.udp_port:
                        log.info(
                            f"[grpc] Proxy-Discovery: {hb.udp_host}:{hb.udp_port}"
                            f" → hannah/server wird aktualisiert"
                        )
                        self._on_proxy_discovery(hb.udp_host, hb.udp_port)
                        discovery_published = True
            except Exception as e:
                log.debug(f"[grpc] Proxy-Drain beendet: {e}")
            finally:
                q.put(None)  # signal EOF to yield loop

        drain_thread = threading.Thread(target=_drain, daemon=True, name="proxy-drain")
        drain_thread.start()

        try:
            while context.is_active():
                try:
                    cmd = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if cmd is None:
                    break  # stream ended
                yield cmd
        finally:
            drain_thread.join(timeout=2)
            with self._proxy_lock:
                if q in self._proxy_queues:
                    self._proxy_queues.remove(q)
                no_more = len(self._proxy_queues) == 0
            if no_more:
                log.info("[grpc] Kein Proxy mehr verbunden — UDP-Server + Discovery werden wiederhergestellt")
                self._enable_udp()
                self._on_proxy_discovery(None, 0)  # None → Restore Hannah's own address
            if no_more and self._on_satellite_change:
                with self._proxy_sat_lock:
                    self._proxy_satellites.clear()
                threading.Thread(
                    target=self._on_satellite_change, args=({},), daemon=True
                ).start()
            log.info(f"[grpc] Proxy '{proxy_id}' getrennt")

    def SubmitSatelliteAudio(self, request, context):
        if self._handle_satellite_audio is None:
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            context.set_details("handle_satellite_audio not configured")
            return pb.SubmitSatelliteAudioResponse()

        speaker = request.speaker_roomie_id or ""
        log.info(
            f"[grpc] SubmitSatelliteAudio: device={request.device_id!r}"
            f" room={request.room!r} bytes={len(request.audio_pcm)}"
            + (f" speaker={speaker!r}" if speaker else " speaker=anonymous")
        )
        if self._on_satellite_change and request.device_id:
            with self._proxy_sat_lock:
                known = self._proxy_satellites.get(request.device_id)
                if known is None or known.get("room") != request.room:
                    self._proxy_satellites[request.device_id] = {"room": request.room, "addr": known.get("addr", "") if known else ""}
                    snapshot = {d: info["room"] for d, info in self._proxy_satellites.items()}
            if known is None or known.get("room") != request.room:
                threading.Thread(
                    target=self._on_satellite_change, args=(snapshot,), daemon=True
                ).start()
        if self.is_captured(request.device_id):
            self.push_capture_audio(
                request.device_id, request.audio_pcm,
                request.sample_rate or 16000, end_of_utterance=True,
            )
            log.debug(f"[grpc/capture] Audio von '{request.device_id}' weitergeleitet ({len(request.audio_pcm)} Bytes)")
            return pb.SubmitSatelliteAudioResponse()

        transcript, answer, intent_name, tts_pcm, sample_rate = self._handle_satellite_audio(
            request.device_id,
            request.audio_pcm,
            speaker,
        )
        return pb.SubmitSatelliteAudioResponse(
            transcript=transcript,
            answer=answer,
            intent_name=intent_name,
            audio_pcm=tts_pcm,
            sample_rate=sample_rate,
        )

    def NotifySatelliteRegistered(self, request, _context):
        """Proxy meldet: Satellit hat sich via UDP registriert."""
        device, room, address = request.device_id, request.room, request.address
        with self._proxy_sat_lock:
            self._proxy_satellites[device] = {"room": room, "addr": address}
            snapshot = {d: info["room"] for d, info in self._proxy_satellites.items()}
        log.info(f"[grpc] Satellit registriert via Proxy: '{device}' (Raum: '{room}')")
        if self._on_satellite_change:
            threading.Thread(
                target=self._on_satellite_change, args=(snapshot,), daemon=True
            ).start()
        self.agent_satellite_update(device, room, "", online=True)
        return pb.StatusResponse(ok=True, message="registered")

    def NotifySatelliteGone(self, request, _context):
        """Proxy meldet: Satellit hat sich abgemeldet."""
        device = request.device_id
        with self._proxy_sat_lock:
            self._proxy_satellites.pop(device, None)
            snapshot = {d: info["room"] for d, info in self._proxy_satellites.items()}
        log.info(f"[grpc] Satellit abgemeldet via Proxy: '{device}'")
        if self._on_satellite_change:
            threading.Thread(
                target=self._on_satellite_change, args=(snapshot,), daemon=True
            ).start()
        self.agent_satellite_update(device, "", "", online=False)
        return pb.StatusResponse(ok=True, message="gone")

    # ------------------------------------------------------------------
    # ioBroker Adapter

    def agent_connected(self) -> bool:
        """True if at least one adapter stream is active."""
        with self._agent_lock:
            return len(self._agent_queues) > 0

    def agent_set_state(self, state_id: str, value: str) -> bool:
        """Push SetState command to all connected adapters. Returns True if at least one is active."""
        cmd = pb.AgentCommand(set_state=pb.AgentSetState(state_id=state_id, value=value))
        with self._agent_lock:
            for q in self._agent_queues:
                q.put(cmd)
            return len(self._agent_queues) > 0

    def agent_watch_more(self, state_ids: list[str]) -> bool:
        """Push WatchMore request to all connected adapters."""
        cmd = pb.AgentCommand(watch_more=pb.AgentWatchMore(state_ids=state_ids))
        with self._agent_lock:
            for q in self._agent_queues:
                q.put(cmd)
            return len(self._agent_queues) > 0

    def agent_set_resident(self, resident_id: str, presence_state: int, is_guest: bool) -> bool:
        """Push SetResident command to all connected adapters."""
        cmd = pb.AgentCommand(set_resident=pb.AgentSetResident(
            resident_id=resident_id,
            presence_state=presence_state,
            is_guest=is_guest,
        ))
        with self._agent_lock:
            for q in self._agent_queues:
                q.put(cmd)
            return len(self._agent_queues) > 0

    def agent_satellite_update(self, device_id: str, room: str, address: str, online: bool,
                               volume: int = None, mute: bool = None) -> bool:
        """Push a satellite online/offline or state update to all connected adapters."""
        kwargs = dict(device_id=device_id, room=room, address=address, online=online)
        if volume is not None:
            kwargs["volume"] = volume
        if mute is not None:
            kwargs["mute"] = mute
        cmd = pb.AgentCommand(satellite_update=pb.AgentSatelliteUpdate(**kwargs))
        with self._agent_lock:
            for q in self._agent_queues:
                q.put(cmd)
            return len(self._agent_queues) > 0

    def agent_firmware_event(self, device: str, version: str, update_available: bool = False) -> bool:
        """Push a firmware version update to all connected adapters."""
        cmd = pb.AgentCommand(firmware_event=pb.AgentFirmwareEvent(
            device=device, version=version, update_available=update_available,
        ))
        with self._agent_lock:
            for q in self._agent_queues:
                q.put(cmd)
            return len(self._agent_queues) > 0

    def agent_ble_update(self, label: str, mac: str, room: str, satellite: str, rssi: int) -> bool:
        """Push a BLE tag location update to all connected adapters."""
        cmd = pb.AgentCommand(ble_update=pb.AgentBleUpdate(
            label=label, mac=mac, room=room or "", satellite=satellite or "", rssi=rssi,
        ))
        with self._agent_lock:
            for q in self._agent_queues:
                q.put(cmd)
            return len(self._agent_queues) > 0

    def agent_sensor_update(self, device: str, temperature: float, pressure: float,
                            humidity: float, gas_resistance: float) -> bool:
        """Push a satellite sensor reading to all connected adapters."""
        cmd = pb.AgentCommand(sensor_update=pb.AgentSensorUpdate(
            device=device,
            temperature=temperature,
            pressure=pressure,
            humidity=humidity,
            gas_resistance=gas_resistance,
        ))
        with self._agent_lock:
            n = len(self._agent_queues)
            for q in self._agent_queues:
                q.put(cmd)
            log.debug(f"agent_sensor_update({device}): pushed to {n} adapter(s)")
            return n > 0

    def agent_resident_answered(self, correlation_id: str, answer: str) -> bool:
        """Push AgentResidentAnswered to all connected adapters."""
        cmd = pb.AgentCommand(resident_answered=pb.AgentResidentAnswered(
            correlation_id=correlation_id,
            answer=answer,
        ))
        with self._agent_lock:
            for q in self._agent_queues:
                q.put(cmd)
            return len(self._agent_queues) > 0

    # ------------------------------------------------------------------
    # Timer Service (called from main.py)

    def timer_connected(self) -> bool:
        """True if the Timer Service stream is currently active."""
        with self._timer_lock:
            return self._timer_queue is not None

    def timer_send_ready(self) -> bool:
        """Send TimerReady to the connected Timer Service. No-op if not connected."""
        with self._timer_lock:
            if self._timer_queue is None:
                return False
            self._timer_queue.put(pb.TimerCommand(ready=pb.TimerReady()))
        log.info("[grpc] TimerReady gesendet")
        return True

    def timer_create(self, timer_id: str, label: str, fire_at: int,
                     room: str, roomie_id: str = "") -> bool:
        """Send TimerCreate to the Timer Service. Returns False if not connected."""
        kwargs = dict(timer_id=timer_id, label=label, fire_at=fire_at, room=room)
        if roomie_id:
            kwargs["roomie_id"] = roomie_id
        cmd = pb.TimerCommand(create=pb.TimerCreate(**kwargs))
        with self._timer_lock:
            if self._timer_queue is None:
                return False
            self._timer_queue.put(cmd)
        return True

    def timer_cancel(self, timer_id: str) -> bool:
        """Send TimerCancel to the Timer Service. Returns False if not connected."""
        cmd = pb.TimerCommand(cancel=pb.TimerCancel(timer_id=timer_id))
        with self._timer_lock:
            if self._timer_queue is None:
                return False
            self._timer_queue.put(cmd)
        return True

    def timer_list_request(self) -> bool:
        """Send TimerListRequest to the Timer Service. Returns False if not connected."""
        cmd = pb.TimerCommand(list=pb.TimerListRequest())
        with self._timer_lock:
            if self._timer_queue is None:
                return False
            self._timer_queue.put(cmd)
        return True

    def AgentConnect(self, request_iterator, context):
        """
        Bidirektionaler Stream: Adapter → State-Updates, Hannah → Geräte-Befehle.

        Der Adapter sendet AgentMessage-Frames (state_update / resident_update /
        text_command); Hannah antwortet mit AgentCommand-Frames (set_state /
        watch_more). Beim Disconnect werden alle gepufferten Befehle verworfen.
        """
        q: queue.Queue = queue.Queue()
        with self._agent_lock:
            self._agent_queues.append(q)
        log.info("[grpc] ioBroker-Adapter connected")

        if self._on_agent_connect:
            try:
                self._on_agent_connect()
            except Exception as e:
                log.warning(f"[grpc] on_agent_connect Fehler: {e}")

        def _drain():
            try:
                for msg in request_iterator:
                    which = msg.WhichOneof("payload")
                    if which == "state_update" and self._on_agent_state:
                        u = msg.state_update
                        self._on_agent_state(u.state_id, u.value, u.ack, u.ts)
                    elif which == "resident_update" and self._on_agent_resident:
                        r = msg.resident_update
                        self._on_agent_resident(r.roomie_id, r.presence_state, r.is_guest)
                    elif which == "text_command" and self._on_agent_text_command:
                        answer, intent = self._on_agent_text_command(msg.text_command.text)
                        q.put(pb.AgentCommand(text_answer=pb.AgentTextAnswer(
                            text=answer, intent=intent,
                        )))
                    elif which == "satellite_control" and self._on_agent_satellite_control:
                        sc = msg.satellite_control
                        ctrl = sc.WhichOneof("control")
                        if ctrl:
                            self._on_agent_satellite_control(
                                sc.room, ctrl, getattr(sc, ctrl),
                                device_id=sc.device_id or "",
                            )
                    elif which == "set_resident" and self._on_agent_set_resident:
                        r = msg.set_resident
                        self._on_agent_set_resident(r.resident_id, r.presence_state, r.is_guest)
                    elif which == "send_snapshot" and self._on_agent_device_snapshot:
                        snapshot = msg.send_snapshot
                        self._on_agent_device_snapshot(snapshot.devices)
                    elif which == "send_residents" and self._on_agent_send_residents:
                        r = msg.send_residents
                        self._on_agent_send_residents(r.residents)
                    elif which == "ask_resident" and self._on_agent_ask_resident:
                        ar = msg.ask_resident
                        threading.Thread(
                            target=self._on_agent_ask_resident,
                            args=(ar.correlation_id, ar.room, ar.question),
                            daemon=True, name="agent-ask",
                        ).start()
                    else:
                        log.warning(f"[grpc] Unrecognized AgentMessage payload: {which}")
                            

            except Exception as e:
                log.debug(f"[grpc] Adapter drain ended: {e}")
                log.debug(f"[grpc] Adapter drain ended: {e}", exc_info=True)
            finally:
                q.put(None)

        drain_thread = threading.Thread(target=_drain, daemon=True, name="agent-drain")
        drain_thread.start()

        try:
            while context.is_active():
                try:
                    cmd = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if cmd is None:
                    break
                yield cmd
        finally:
            drain_thread.join(timeout=2)
            with self._agent_lock:
                if q in self._agent_queues:
                    self._agent_queues.remove(q)
            log.info("[grpc] ioBroker-Adapter disconnected")

    def TimerConnect(self, request_iterator, context):
        """
        Bidirektionaler Stream: Timer Service → TimerMessage, Hannah → TimerCommand.

        Nur ein Timer Service kann gleichzeitig verbunden sein. Bei erneutem
        Connect wird die bestehende Verbindung verdrängt.
        """
        q: queue.Queue = queue.Queue()
        with self._timer_lock:
            if self._timer_queue is not None:
                log.warning("[grpc] Timer Service reconnect — bestehende Verbindung wird verdrängt")
                self._timer_queue.put(None)  # EOF für alten Stream
            self._timer_queue = q
        log.info("[grpc] Timer Service connected")

        if self._on_timer_connected:
            try:
                self._on_timer_connected()
            except Exception as e:
                log.warning(f"[grpc] on_timer_connected Fehler: {e}")

        def _drain():
            try:
                for msg in request_iterator:
                    which = msg.WhichOneof("payload")
                    if which == "ack":
                        log.info(
                            f"[grpc] Timer Service Ack: {msg.ack.message!r}"
                            f" ({msg.ack.active_timers} aktive Timer)"
                        )
                    elif which == "fired":
                        fired = msg.fired
                        log.info(f"[grpc] TimerFired: {fired.timer_id!r} ({fired.label!r})")
                        if self._on_timer_fired:
                            try:
                                self._on_timer_fired(fired.timer_id, fired.label)
                            except Exception as e:
                                log.error(f"[grpc] on_timer_fired Fehler: {e}")
                    elif which == "list":
                        log.debug(f"[grpc] TimerListResponse: {len(msg.list.timers)} Timer")
                        if self._on_timer_list:
                            try:
                                self._on_timer_list(list(msg.list.timers))
                            except Exception as e:
                                log.error(f"[grpc] on_timer_list Fehler: {e}")
                    else:
                        log.warning(f"[grpc] Unbekanntes TimerMessage-Payload: {which!r}")
            except Exception as e:
                log.debug(f"[grpc] Timer Service drain ended: {e}")
            finally:
                q.put(None)

        drain_thread = threading.Thread(target=_drain, daemon=True, name="timer-drain")
        drain_thread.start()

        try:
            while context.is_active():
                try:
                    cmd = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if cmd is None:
                    break
                yield cmd
        finally:
            drain_thread.join(timeout=2)
            with self._timer_lock:
                if self._timer_queue is q:
                    self._timer_queue = None
            log.info("[grpc] Timer Service disconnected")

    # ------------------------------------------------------------------
    # Wakeword Capture

    def is_captured(self, device_id: str) -> bool:
        with self._capture_lock:
            return device_id in self._captured_satellites

    def push_capture_audio(self, device_id: str, pcm: bytes, sample_rate: int,
                           end_of_utterance: bool = False):
        """Route raw PCM from a captured satellite into its StreamSatelliteAudio queue."""
        with self._capture_lock:
            q = self._captured_satellites.get(device_id)
        if q is not None:
            q.put(pb.SatelliteAudioChunk(
                pcm=pcm,
                sample_rate=sample_rate,
                end_of_utterance=end_of_utterance,
            ))

    def RequestSatelliteCapture(self, request, _context):
        device_id = request.device_id
        all_sats = self._get_satellites()
        if device_id not in all_sats:
            return pb.SatelliteCaptureResponse(ok=False, error=f"Satellit '{device_id}' nicht gefunden")
        with self._capture_lock:
            if device_id in self._captured_satellites:
                return pb.SatelliteCaptureResponse(ok=False, error=f"'{device_id}' bereits belegt")
            self._captured_satellites[device_id] = queue.Queue()
        sample_type = request.sample_type or "noise"
        log.info(f"[grpc/capture] Satellit '{device_id}' in Capture-Modus versetzt (type={sample_type})")
        self._on_set_capture(device_id, True, sample_type)
        return pb.SatelliteCaptureResponse(ok=True)

    def ReleaseSatelliteCapture(self, request, _context):
        device_id = request.device_id
        with self._capture_lock:
            q = self._captured_satellites.pop(device_id, None)
        if q is not None:
            q.put(None)  # EOF für laufenden StreamSatelliteAudio
            log.info(f"[grpc/capture] Satellit '{device_id}' aus Capture-Modus entlassen")
            self._on_set_capture(device_id, False)
        return pb.StatusResponse(ok=True, message="released")

    def TriggerPlink(self, request, _context):
        device_id = request.device_id
        duration  = request.record_duration if request.record_duration > 0 else 3.0
        self._on_trigger_plink(device_id, duration)
        return pb.StatusResponse(ok=True)


    def StreamSatelliteAudio(self, request, context):
        device_id = request.device_id
        with self._capture_lock:
            q = self._captured_satellites.get(device_id)
        if q is None:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(f"'{device_id}' ist nicht im Capture-Modus — RequestSatelliteCapture zuerst aufrufen")
            return

        log.info(f"[grpc/capture] StreamSatelliteAudio gestartet für '{device_id}'")
        try:
            while context.is_active():
                try:
                    chunk = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if chunk is None:
                    break  # ReleaseSatelliteCapture wurde aufgerufen
                yield chunk
        finally:
            # Cleanup falls Client trennt ohne ReleaseSatelliteCapture
            with self._capture_lock:
                if self._captured_satellites.get(device_id) is q:
                    self._captured_satellites.pop(device_id, None)
                    self._on_set_capture(device_id, False)
                    log.info(f"[grpc/capture] '{device_id}' auto-released nach Stream-Disconnect")

    def EnrollVoiceprint(self, request, _context):
        if self._enroll_voiceprint is None:
            return pb.StatusResponse(
                ok=False,
                message="Kein Voice-ID-Backend konfiguriert.",
            )
        log.info(
            f"[grpc] EnrollVoiceprint: roomie={request.roomie_id!r}"
            f" bytes={len(request.audio_pcm)} rate={request.sample_rate}"
        )
        ok, msg = self._enroll_voiceprint(
            request.roomie_id, request.audio_pcm, request.sample_rate
        )
        return pb.StatusResponse(ok=ok, message=msg)


# ------------------------------------------------------------------
# Server lifecycle

class GrpcServer:
    def __init__(self, cfg: dict, servicer: HannahServicer):
        self._host = cfg.get("host", "0.0.0.0")
        self._port = int(cfg.get("port", 50051))
        self._server: Optional[grpc.Server] = None
        self._servicer = servicer

    def start(self):
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
        pb_grpc.add_HannahServiceServicer_to_server(self._servicer, self._server)
        addr = f"{self._host}:{self._port}"
        self._server.add_insecure_port(addr)
        self._server.start()
        log.info(f"gRPC-Server lauscht auf {addr}")

    def stop(self):
        if self._server:
            self._server.stop(grace=2)
            log.info("gRPC-Server beendet.")


# ------------------------------------------------------------------
# Event factory helpers (called from main.py)

def make_car_parked_event(state, home_address: str = "") -> pb.HannahEvent:
    return pb.HannahEvent(
        event_type="car.parked",
        timestamp=datetime.now(timezone.utc).isoformat(),
        car_state=_car_to_pb(state, home_address),
    )


def make_resident_event(roomie_id: str, display_name: str, event: str) -> pb.HannahEvent:
    """event: 'arrived' | 'departed'"""
    return pb.HannahEvent(
        event_type=f"resident.{event}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        resident_event=pb.ResidentEventProto(
            roomie_id=roomie_id,
            display_name=display_name,
            event=event,
        ),
    )


def make_firmware_event(device: str, version: str) -> pb.HannahEvent:
    return pb.HannahEvent(
        event_type="satellite.firmware",
        timestamp=datetime.now(timezone.utc).isoformat(),
        firmware_event=pb.FirmwareEventProto(device=device, version=version),
    )


def make_system_notification_event(text: str) -> pb.HannahEvent:
    return pb.HannahEvent(
        event_type="system.notification",
        timestamp=datetime.now(timezone.utc).isoformat(),
        system_notification=pb.SystemNotificationEvent(text=text),
    )


# ------------------------------------------------------------------
# Conversion helpers

def _user_to_pb(u: dict) -> pb.User:
    return pb.User(
        uuid=u.get("uuid", ""),
        roomie_id=u.get("roomie_id", ""),
        display_name=u.get("display_name", ""),
        trust_level=u.get("trust_level", 5),
        active=bool(u.get("active", True)),
        linked_accounts=u.get("linked_accounts") or {},
        system_messages=bool(u.get("system_messages", False)),
    )


def _car_to_pb(state, home_address: str = "") -> pb.CarStateProto:
    return pb.CarStateProto(
        latitude=state.latitude or 0.0,
        longitude=state.longitude or 0.0,
        address=state.address or "",
        is_moving=bool(state.is_moving),
        position_date=state.position_date or 0,
        odometer=state.odometer or 0,
        total_range=state.total_range or 0,
        is_car_locked=bool(state.is_car_locked),
        door_lock_status=state.door_lock_status or "",
        overall_status=state.overall_status or "",
        doors=state.doors or {},
        windows=state.windows or {},
        owner_roomie=state.owner_roomie or "",
        display_name=state.display_name or "",
        plate=state.plate or "",
        vin=state.vin or "",
        home_address=home_address,
    )
