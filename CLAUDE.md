# Hannah — Projekt-Kontext für Claude

## Projekt-Überblick

Hannah ist ein **lokal betriebener, deutschsprachiger Sprachassistent** fur das Smart Home — gedacht als selbst gehosteter Ersatz fur Google Assistant / Amazon Echo. Betrieben auf einem Raspberry Pi, integriert mit ioBroker. Satelliten sind ESP32-S3-basierte Geräte in verschiedenen Räumen die per Wake-Word / PTT Sprachbefehle aufnehmen und an Hannah Core senden.

**Langfristiges Ziel:** Vollständige Bidirektionalität (Sprache + Text), Persönlichkeit (Hannah, 24, Masterstudentin), Autonome Aktionen, Speaker-ID, proaktives Verhalten.

**Persona:** Hannah ist die echte Mitbewohnerin der Projektentwicklerin. Die KI-Hannah hat eine ausgearbeitete Persönlichkeit — freundlich aber direkt, eigenständig, studiert Informationswissenschaft im Fernstudium an der TU München. Persona-Text liegt in `core/forum_post.md`.

---

## Repository-Struktur

```
hannah/                          ← Mono-Repo (Branch: DanielDuesentrieb)
├── core/                        ← Hannah Core (Python, Raspberry Pi)
│   ├── hannah/                  ← Python-Package
│   │   ├── main.py              ← Einstiegspunkt, Orchestrierung
│   │   ├── nlu.py               ← Natural Language Understanding (regelbasiert)
│   │   ├── iobroker.py          ← ioBroker REST API Client (Port 8093)
│   │   ├── mqtt_handler.py      ← MQTT Pub/Sub
│   │   ├── udp_server.py        ← UDP Audio-Empfang von Satelliten
│   │   ├── grpc_server.py       ← gRPC Server (externe Services, Proxy)
│   │   ├── tts.py               ← TTS (Azure Cognitive Services / Piper)
│   │   ├── stt.py               ← STT (faster-whisper)
│   │   ├── llm.py               ← LLM-Integration (Ollama)
│   │   ├── car_tracker.py       ← Auto-Status per MQTT (VW Connect)
│   │   ├── user_registry.py     ← SQLite-Benutzer-Registry (UUID, Trust Level)
│   │   ├── residents.py         ← ioBroker Residents-Adapter Integration
│   │   ├── conversation.py      ← Konversations-Kontext (Multi-Turn)
│   │   ├── memory.py            ← Langzeit-Erinnerungen (SQLite)
│   │   ├── trigger_engine.py    ← Proaktive Trigger (ioBroker State-Änderungen)
│   │   ├── routines.py          ← Geplante Routinen (routines.yaml)
│   │   ├── weather.py           ← Wetter-Abfragen (OpenWeatherMap)
│   │   ├── audio.py             ← Audio-Utilities (Resampling, VAD)
│   │   └── proto/               ← Generierte gRPC-Stubs
│   ├── config.yaml              ← Hauptkonfiguration
│   ├── triggers.yaml            ← Trigger-Definitionen (hot-reload)
│   └── routines.yaml            ← Routinen-Definitionen (hot-reload)
│
├── proxy/                       ← Go gRPC-Proxy (UDP-Satelliten → gRPC → Core)
│   └── proto/hannah.proto       ← Einzige Source of Truth fur das Protokoll
│
├── satellite-esp/               ← ESP32-S3 Firmware (ESP-IDF, C)
│   ├── main/main.c              ← FreeRTOS App-Main
│   ├── components/
│   │   ├── hannah_net/          ← WiFi, MQTT-Discovery, UDP-Streaming
│   │   ├── hannah_audio/        ← I2S Mic (INMP441×2), Speaker (MAX98357A)
│   │   ├── hannah_led/          ← WS2812B LED-Ring State-Machine
│   │   ├── hannah_sensors/      ← BMP280, AHT20 (I2C)
│   │   ├── hannah_wakeword/     ← microWakeWord / ESP-SR (in Arbeit)
│   │   └── microfrontend/       ← Audio-Frontend (Spectrogramm fur WW)
│   └── hardware/
│       ├── Phase2/              ← KiCad PCB Rev. 2 (aktuelle Bestellung)
│       │   ├── Hannah_Satellite.kicad_pcb
│       │   └── Hannah_Satellite.kicad_sch
│       └── Enclosure/           ← FreeCAD Gehäuse fur FPH Satellite1
│           ├── Enclosure.FCStd  ← Haupt-FreeCAD-Datei (Topf + Deckel)
│           └── Enclosure-Deckel.step ← Exportierter Deckel
│
├── satellite-pi/                ← Raspberry Pi Satellit (Python, Legacy)
│   └── satellite.py             ← Python-Satellit (OpenWakeWord, PyAudio)
│
├── telegram/                    ← Telegram-Bot Microservice (Python)
├── voiceid/                     ← Speaker-ID Service (Python)
├── audiolib/                    ← C-Audio-Bibliothek (fruhe Phase)
├── iobroker.hannah/             ← ioBroker-Adapter (TypeScript)
└── scripts/                     ← Build- und Release-Scripts
```

---

## Software-Architektur

### Hannah Core (`core/`)

Python-Dienst, läuft auf Raspberry Pi. Orchestriert alle Komponenten:

**Datenfluss:**
```
Satellit (Audio/PTT)
    → UDP (raw PCM, 16kHz, 16-bit, mono)  [Legacy oder via Proxy]
    → Hannah Core STT (faster-whisper)
    → NLU (regelbasiert, nlu.py)
    → Intent-Handler (ioBroker / Antwort-Generator)
    → TTS (Azure Cognitive Services oder Piper)
    → UDP/gRPC zurück zum Satelliten
```

**Wichtige Module:**
- `nlu.py`: Regelbasiertes NLU. Erkennt Intents: TurnOn/TurnOff/SetLevel/SetColor, QuerySensor, CarQuery, WeatherQuery, u.a. Drei-Ebenen-Matching: Raum + optionaler Gerätename + Aktion.
- `iobroker.py`: Lädt ioBroker-Gerätebaum uber REST API (Port 8093, `/v1/enum/rooms`, `/v1/state/`). States werden per `PATCH` gesetzt (ack=false).
- `grpc_server.py`: Servicer fur externe Services (Telegram, Proxy). Subscriber-Registry fur Event-Streams.
- `trigger_engine.py`: Abonniert ioBroker States per MQTT, logt Trigger, feuert Routinen.
- `user_registry.py`: SQLite, synct Roomies aus ioBroker Residents-Adapter, speichert Trust-Level und Linked Accounts (Telegram-ID etc.).

**STT/TTS:**
- STT: `faster-whisper` (lokal auf dem Pi, kein Cloud-Zwang)
- TTS: Azure Cognitive Services (Hauptpfad) oder Piper (lokal, niedrigere Qualität)
- Piper-Modelle: `kerstin-medium` oder `thorsten-medium` fur 22050Hz

### Satellite Firmware (`satellite-esp/`)

ESP-IDF (C), FreeRTOS. Chip: **ESP32-S3** (nicht original ESP32, da AI-Beschleuniger und mehr RAM benotigt).

**Komponenten:**
- `hannah_net`: WiFi STA mit Auto-Reconnect. MQTT-Discovery: subscribt auf `hannah/server` (retained) um Hannah Core IP:Port zu finden. UDP-Registrierung beim Start + Heartbeat alle 30s.
- `hannah_audio`: I2S0 (INMP441 stereo, linker Kanal als Mono), I2S1 (MAX98357A Speaker). PTT-Button: halten → streamen, loslassen → audio_end. TTS-Chunks in asynchroner Queue.
- `hannah_led`: WS2812B LED-Ring, 7 Zustande: BOOT / IDLE / WAKE / STREAM / SPEAK / MUTE / ERROR
- `hannah_sensors`: BMP280 (Temperatur + Luftdruck), AHT20 (Feuchte) uber I2C
- `hannah_wakeword`: microWakeWord / ESP-SR (noch in Arbeit, 6 verbleibende Kompilierfehler)

**LED-Zustands-Semantik:** LED zeigt immer den aktuellen Verbindungs- / Gesprächszustand fur den Nutzer sichtbar an.

**ESP-IDF Umgebung aktivieren:**
```powershell
C:\Users\rene\esp\v6.0\esp-idf\export.ps1
```

### Kommunikations-Protokoll

**UDP (Satellit ↔ Hannah Core, Legacy + Fallback):**
```
Typ 0x01: JSON-Steuernachricht (Register, Heartbeat, Status)
Typ 0x02: Audio-Chunk (raw PCM, 16kHz, 16-bit, mono)
Typ 0x03: TTS-Audio-Chunk von Hannah zum Satelliten
```

**Registrierung (UDP, JSON):**
```json
{"type": "register", "device": "kueche-esp", "room": "Küche", "ip": "...", "port": 5005}
```

**Audio-Stream:** Rohe PCM-Pakete, kein Framing, kein Container. 16kHz, 16-bit, mono. Kein TLS auf UDP (zu teuer fur ESP32).

**gRPC (Hannah Core ↔ externe Services):**
- Proto: `core/proto/hannah.proto` (einzige Source of Truth — nicht `proxy/proto/`)
- Bei Änderungen: Datei manuell in **alle** Konsumenten kopieren, dann Stubs neu generieren via `core/proto/gen_proto.sh`
  - Konsumenten: `proxy/proto/hannah.proto`, `iobroker.hannah/src/proto/hannah.proto`
  - TODO: echte Single Source of Truth evaluieren (prebuild-Hook scheidet aus, da CI keinen Zugriff auf core/ hat)
- Port: 50051 (lokal, kein Internet-Exposure)

**Wichtige gRPC-Methoden:**
- `SubmitText` / `SubmitVoice`: Text/Voice-Befehl → Intent + Antwort
- `SubmitSatelliteAudio`: Proxy reicht Satellit-Audio durch → STT+NLU+TTS in einer Transaktion
- `RegisterProxy`: Bidirektionaler Keep-alive-Stream. Proxy sendet Heartbeats; Hannah sendet `PlayAudioCommand` zurück. Solange Stream offen: Hannah deaktiviert UDP-Server. Bei Disconnect: UDP reaktiviert.
- `SubscribeEvents`: Server-Side Stream fur Events (`car.parked`, `resident.arrived`, etc.)
- `EnrollVoiceprint`: Sprach-Enrollment fur Speaker-ID

**MQTT (Hannah Core ↔ ioBroker / Satelliten):**
- Discovery: `hannah/server` (retained) → Proxy-IP:Port
- Audio (Legacy): `hannah/{device}/audio`
- Antworten: `hannah/{device}/answer`, `hannah/{device}/intent`, `hannah/{device}/text`
- ioBroker States lesen: `ioBroker/javascript/0/virtualDevice/#` (Präfix `ioBroker/` ist pflicht!)
- States setzen: `0_userdata/0/virtualDevice/...` oder per REST PATCH

### ioBroker-Integration

Hannah liest Geräte aus `0_userdata.0.virtualDevice.<Kategorie>.<Etage>.<Raum>.<Gerätename>.<State>`.

**API:** REST auf Port 8093 (`/v1/enum/rooms`, `/v1/state/{id}`)

**States setzen:** HTTP `PATCH /v1/state/{state_id}` mit `{"val": <value>}` setzt `ack=false` (kommt an der Hardware an). `PUT` funktioniert nicht korrekt.

**Residents-Adapter:** Topics `residents/0/roomie/{name}/presence/state` (read) und `hannah/set/residents/roomie/{name}/presence/state` (write). Hannah meldet sich beim Start als "home" (Roomie: "hannah").

**Trigger-Engine:** Subscribt auf ioBroker-State-Topics per MQTT. Bei Änderung: `triggers.yaml` wird gepruft, matching Aktionen werden ausgefuhrt (hot-reload, kein Neustart notwendig).

---

## Hardware (Hannah Satellite PCB)

### Revisions-Ubersicht

| Rev | Status | Grösse | Besonderheit |
|-----|--------|--------|--------------|
| Rev. 1 | Prototyp (nicht bestellt) | — | Erste Machbarkeitsstudie |
| Rev. 2 | Bestellt bei JLCPCB, ~185€, 5 Stück | 114mm rund (Versehen: 57mm Radius statt 75mm Durchmesser) | Nur elektrischer Test, nicht produktiv nutzbar |
| Rev. 3 | Aktiv in Entwicklung (KiCad + FreeCAD, Branch DanielDuesentrieb) | 88mm rund | Aktuelles Zieldesign |

### PCB Rev. 3 (aktuell in Entwicklung, `satellite-esp/hardware/Phase2/`)

**Abmessungen:** 88mm Durchmesser (rund), eine Seite leicht abgeflacht für USB-C/Anschluss. 4-lagig: F.Cu / In1.Cu (GND-Plane) / In2.Cu (3.3V-Plane) / B.Cu. ENIG Surface Finish.

**Hauptkomponenten Oberseite:**
- 4× ALPS ALPINE SKRPABE010 SMD-Taster (Mute, Vol+, Vol-, PTT) — 4.2×3.2mm, Höhe 2.5mm — brauchen Membran im Deckel
- ~24× WS2812B LED-Ring am Rand

**Hauptkomponenten Unterseite:**
- ESP32-S3-WROOM-1-N16R8
- 2× SPH0641LU4H-1 (PDM-Mikrofon, direkt am ESP32-S3)
- MAX98357A (I2S-Verstärker für Speaker)
- LD2410 (mmWave-Radar, Präsenzerkennung, 24GHz, UART) — Female Header
- BMP280 (Temperatur + Luftdruck, I2C)
- AMS1117-3.3 SOT-223
- SN74AHCT125D (Level-Shifter 3.3V→5V für WS2812B LEDs) — auf B.Cu
- USB-C HRO TYPE-C-31-M-12
- 2-Pin JST PH (Speaker), 6-Pin Header (externer optionaler Verstärker)
- 2× ALPS ALPINE SKRPABE010 SMD-Taster: EN + IO0 (Boot/Reset) — nur für frühe Revisionen zum Flashen. Ab Rev. 5/6+: entfallen komplett. Initiale Firmware wird durch JLCPCB beim Assembly-Service geflasht, weitere Updates per OTA.
- 4× Montagelöcher

**Geparkte Ideen (nicht verworfen, aber zurückgestellt):**
- 4 PDM-Mikrofone statt 2 (für besseres Beamforming) — Leonie will das, technische Umsetzung noch offen
- RP2350 als Co-Prozessor: **definitiv verworfen** — aktuell kein Bedarf, ESP32-S3 reicht

**Wichtige Design-Entscheidungen Rev. 3:**
- INMP441 (I2S) EOL → PDM (SPH0641LU4H-1) direkt am ESP32-S3
- RP2350 verworfen: Co-Prozessor nicht erforderlich nach aktuellem Stand
- Level-Shifter auf B.Cu für mehr Platz auf F.Cu
- Gehäuse-Ziel: Eigenes FreeCAD-Design, 88mm Durchmesser Platine

### Gehäuse (`satellite-esp/hardware/Enclosure/`)

**Ursprung:** An FutureProofHomes (FPH) Satellite1 orientiert (Innendurchmesser 88mm, 4 Montageloch-Bosses). Lang überlegt FPH-Gehäuse direkt zu nutzen — dann entschieden: **eigenes FreeCAD-Design** (mehr Kontrolle, kein XMOS-Ökosystem-Zwang).

**Eigenes FreeCAD-Design** (`Enclosure.FCStd`, Branch DanielDuesentrieb):
- **Zweiteilig: Topf (Unterteil) + Deckel (Oberteil)**
- Topf grundlegend fertig, aber noch ohne Speaker-Gitter
- Deckel: quadratisch-abgerundet, Innenmass für 88mm PCB

**Topf (Unterteil) — Stand 2026-05-14:**
- Speaker-Öffnung geplant/gedacht, noch nicht final modelliert
- Speaker-Gitter: soll **separat gedruckt** werden, steckbar auf die Speaker-Schrauben-Bosse, auswechselbar
- Speaker selbst wird an Bossen festgeschraubt

**Deckel (Oberteil) — Stand 2026-05-14:**
- 4 Membran-Taster: Ring-Schlitz (1mm, war 0.5mm — zu eng für 0.4mm Nozzle) + Steg
- LED-Ring-Schlitz an äußerer Ringkante
- Stützen für PCB-Höhe: ~0.5mm (PCB-Unterseite 0.5mm von Deckeldecke entfernt) — noch nicht modelliert
- USB-C Ausschnitt seitlich: noch nicht modelliert
- Montagelöcher (4×, passend zu PCB): noch nicht modelliert

**Taster-Geometrie:** ALPS ALPINE SKRPABE010, Höhe 2.5mm. Pocket-Tiefe 2.5mm, Membrandicke 0.5mm, Deckeldicke 3mm → PCB-Oberseite liegt **direkt an der Deckel-Innenfläche an** (S=0, keine Stützen nötig). Die Deckeldecke ist gleichzeitig die Auflagefläche. Fixierung durch 4 Montageschrauben (noch nicht modelliert).

**FreeCAD-Workflow:**
1. KiCad STEP exportieren → FreeCAD importieren
2. Python-Konsole fur Massnahmen: `obj.Shape.BoundBox`
3. Part Design Workbench: Sketch → Pad (Korper), Pocket (Aussparungen)
4. Wichtig: Sketch-Constraints mussen alle geschlossen sein vor Pad/Pocket
5. STEP export fur Weitergabe, STL fur 3D-Druck

**Druckmaterial:** PLA fur Prototypen, PETG fur finale Version (wärmebeständiger).

### Wichtige Bauteil-Entscheidungen

| Entscheidung | Gewählt | Verworfen | Grund |
|---|---|---|---|
| Mikrofon | SPH0641 (PDM) | INMP441 (I2S) | INMP441 ist EOL, nicht mehr bei LCSC verfugbar |
| Wake-Word ESP | microWakeWord | OWW ONNX direkt | OWW braucht Google Speech Embedding als Vorschritt, zu rechenintensiv fur ESP |
| LED-Typ Rev.3 | SK6812-Mini-E | WS2812B | SK6812 ist 3.3V-kompatibel → Level-Shifter entfallt |
| Prozessor-Strategie | ESP32-S3 | Original ESP32 | S3 hat AI-Beschleuniger und mehr RAM (PSRAM), notwendig fur TFLite |
| Audio-ADC Rev.3 | ES7210 | STM32G031 | STM32G031 hat kein DFSDM fur PDM, ES7210 ist dedizierter PDC-ADC-Chip |
| Gehäuse | Eigenes FreeCAD-Design (an FPH orientiert) | FPH Satellite1 direkt nutzen | FPH nutzt XMOS-Chip + ESPHome-Firmware, inkompatibel; eigenes Design gibt volle Kontrolle |
| Satellit-Platform | ESP32-S3 Custom PCB | Pi Zero 2 W | Kosten (~4€ vs 18€), Stromverbrauch (0.1W vs 1W), kein Linux-Boot |
| Kommunikation Satellit→Core | gRPC via Go-Proxy | direktes UDP | Go-Proxy ermoglicht Protokoll-Entkopplung, TLS, bidirektionale Streams |

---

## Wichtige Architektur-Entscheidungen (mit Begrundung)

1. **gRPC als Hauptprotokoll fur externe Services** (statt MQTT uberall): MQTT bleibt fur ioBroker-Integration und einfache Events. gRPC wird genutzt wenn bidirektionales Streaming, Typed API oder mehrsprachige Clients benotigt werden. Entschieden April 2026 als Telegram-Bot als erster externer Service kam.

2. **Telegram als eigenständiger Microservice** (nicht eingebettet in Hannah Core): Separater Lebenszyklus, eigene Auth-Flows, Absturz darf Hannah nicht mitreißen. Verbindet sich per gRPC.

3. **RegisterProxy-Stream als doppelter Keepalive + Push-Kanal**: Proxy sendet Heartbeats → Hannah weiß Proxy ist da. Hannah schickt `PlayAudioCommand` uber denselben Stream zurück fur Announcements. Kein zweiter Stream notwendig. Solange Proxy verbunden: UDP-Server deaktiviert; bei Disconnect: UDP reaktiviert (Fallback).

4. **User-Registry mit Trust-Level** (SQLite, synct aus Residents): Jeder Nutzer hat UUID, Roomie-ID (ioBroker-Referenz), Trust-Level (0-10), und Linked Accounts (z.B. Telegram-Chat-ID). Ermoglicht differenzierte Berechtigungen ("Alarmanlage deaktivieren" nur bei Trust Level 8+).

5. **STT lokal mit faster-whisper** (nicht Cloud): 16kHz, Mono, kein Upsampling notwendig (Whisper trainiert auf 16kHz). Höhere Sample-Rates bringen null Verbesserung.

6. **LLM optional per Ollama** (Fallback DummyLLM): Hannah funktioniert auch ohne LLM (regelbasiertes NLU). LLM aktiviert Kontext-Folgefragen und naturlichere Antworten.

7. **ioBroker: Virtuelle Devices statt Enum-API**: Direkt den virtualDevice-Baum laden statt Enums lesen. Ermoglicht drei-gliedriges Matching (Raum + Gerät + Aktion) und Sensor-States pro Gerät.

8. **Audio: 16kHz Mono fur Mic-Pfad, keine TLS auf UDP**: 16kHz ist Modell-Anforderung (OWW, Whisper). UDP ohne TLS spart RAM/CPU auf ESP32. Fur LAN akzeptabel.

9. **Gitflow: nie direkt in master committen**: Feature-Branches → PR → Merge. Aktueller Hardware-Branch: `DanielDuesentrieb`. Release per `node scripts/release.js patch|minor|major`.

---

## Aktueller Arbeitsstand (Stand 2026-05-14)

**In Arbeit:**
- `satellite-esp/hardware/Enclosure/Enclosure.FCStd`: Eigenes FreeCAD-Gehäuse (an FPH Satellite1 orientiert). Topf grundlegend fertig, Speaker-Gitter fehlt noch. Deckel: LED-Schlitz + 4 Membran-Taster vorhanden. Stützen für PCB-Auflage, Montagelöcher, USB-C-Ausschnitt fehlen noch. Aktuell läuft Druck mit 1mm-Schlitz (0.5mm war zu eng für 0.4mm Nozzle).
- `satellite-esp/hardware/Phase2/`: PCB Rev. 2 bei JLCPCB bestellt. Kommt noch. SPH0641 Mics werden selbst eingelötet.
- `hannah_wakeword` Komponente: 6 verbleibende Kompilierfehler in IDF 6.0, detaillierte Fix-Dokumentation in Memory.

**Offen / Nächste Schritte:**
- FreeCAD-Deckel: Stutzen (4×, 6mm hoch) fur PCB-Auflage modellieren
- FreeCAD-Deckel: Montagelöcher (M3, passend zu FPH-Bosse) hinzufugen
- FreeCAD-Deckel: USB-C Ausschnitt seitlich
- ESP Firmware: `hannah_wakeword` Kompilierfehler beheben (IDF 6.0)
- PCB Rev. 2: Wenn geliefert, elektrischen Test durchfuhren
- PCB Rev. 3: Neues KiCad-Projekt (88mm, RP2350 + ES7210 + 4 PDM-Mics)
- Branch `DanielDuesentrieb` → PR → Merge wenn Hardware-Stand stabil

**Geparkte Ideen (Firmware):**
- **Satellite-Light**: Abgespeckte ESP-Firmware nur mit `hannah_net` + `hannah_sensors` + optional `hannah_ble`, ohne Audio/Wakeword/LED. Eigenes `sdkconfig.defaults.light`. Protokollseitig bereits vollständig kompatibel (gleiche MQTT-Topics). Ziel: günstige Miniplatine die nur Sensor-/BLE-Daten liefert.
- **Hannah Android-App**: Soft-Satellite als App — primär Sprachsteuerung/Announcements, optional Sensordaten (Barometer, Temperatur) per MQTT wenn aktiviert. Gleiche MQTT-Topics wie Hardware-Satelliten, keine neue Infrastruktur nötig. Setzt Satellit-Ownership voraus (siehe unten).
- **Satellit-Ownership + personalisiertes Routing** (Roadmap): Satelliten werden Roomies zugeordnet. Announcements an eine Person spielen auf deren Satelliten + raumlosen Satelliten, nicht auf fremde. Trigger- und Routinen-Engine werden per-Person konfigurierbar (eigene YAML/Config pro Person). Routinen/Trigger können Satellit oder Raum als Ziel-Constraint haben (z.B. "nur auf Test-ESP"). Handy-App gehört per Definition einer Person. Grundlage für alle weiteren Personalisierungs-Features.

- **Update-Server als universelle Deployment-Pipeline** (Roadmap): Hannah-AutoDeploy lädt nicht mehr aus git, sondern vom Update-Server. CI lädt kompilierte Go-Binaries und Python-tar-Archive hoch. Channel-Format: `satellite-esp-stable`, `satellite-esp-dev`, `core-stable`, `core-dev` etc. Fine-Grained Access Tokens: CI bekommt breite Schreibrechte, jede Komponente nur Leserecht auf ihren Channel. Update-Server unterstützt bereits beliebige Dateitypen. Fehlt noch: Channel-Management im Update-Server (in Arbeit).

**Was bereits läuft:**
- Hannah Core vollständig funktionsfähig (STT/NLU/TTS/ioBroker-Steuerung)
- gRPC-Server mit allen definierten Methoden implementiert
- Go-Proxy implementiert (RegisterProxy, SubmitSatelliteAudio)
- Telegram-Microservice (eigenständiges Repo)
- ESP32-S3 Firmware Phase 1: WiFi/MQTT/UDP funktioniert (getestet auf DevKit)
- FreeCAD Gehäuse fur WLED-Verteilerbox fertig (separates Projekt)

---

## Bekannte Probleme / Workarounds

### FreeCAD
- Sketch-Constraints: Vor jedem Pad/Pocket muss der Sketch vollständig geschlossen und vollständig bestimmt sein (keine roten Linien)
- Bodenskatches fur Pocket: FreeCAD braucht manchmal eine explizite Flächen-Referenz. Wenn Pocket fehlschlägt: Objekt temporär ausblenden (Leertaste), Fläche anklicken, wieder einblenden.
- ZIP-Workaround fur Python-Fixes: FreeCAD-Dateien sind ZIP-Archive, bei Korruption `python -m zipfile -e Datei.FCStd /tmp/extract/` fur Reparatur.

### ESP Firmware (IDF 6.0)
- `hannah_wakeword` hat 6 Kompilierfehler (API-Änderungen in IDF 6.0). Fixes dokumentiert in `c--Users-rene-git-hannah/memory/project_wakeword_build_status.md`.
- Phase2 `.history` Verzeichnis enthält eingebettetes Git-Repo (VS Code History). Nicht committen: `.gitignore` deckt es ab.

### Protokoll
- Nach jedem `protoc`-Aufruf: absoluten Import in `hannah_pb2_grpc.py` manuell auf relativen Import korrigieren (`from . import hannah_pb2 as ...` statt `import hannah_pb2 as ...`).
- ioBroker MQTT-Adapter hört nur auf Topics mit `ioBroker/`-Präfix. Beim Senden an ioBroker immer `ioBroker/...` verwenden.

### Audio
- OWW-Inferenz auf Pi 3B: 50-150ms pro 80ms-Chunk → nicht mehr Realtime auf schwacher Hardware. Lösung: Pre-Buffer (letzte 1-2s im Ringpuffer), oder Pi 4/5 als Satellit.
- TTS-Rate muss zur Soundkarte passen. `--tts-rate` Argument fur Python-Satelliten.
- onnxruntime fur ARM: Nicht auf piwheels fur Python 3.11. Alternatives Wheel: `https://github.com/KumaTea/onnxruntime-rpi/releases/`

### Allgemein
- Commits nur auf explizite Anfrage, nie unaufgefordert
- Changelog-Einträge (README.md + CHANGELOG.md) immer auf Englisch, immer in WIP-Sektion
- `en.json` fur i18n manuell pflegen; andere Sprachen kommen vom ioBroker-Translator
