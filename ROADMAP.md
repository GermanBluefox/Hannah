# Hannah — Roadmap

## Umgesetzt

### gRPC-Schnittstelle (Core ↔ externe Services)
`core/proto/hannah.proto` — vollständige Service-Definition:
- User-Registry (GetUser, LinkAccount, SetTrustLevel, …)
- SubmitText — Text-Befehle von externen Services
- SubmitVoice — Spracheingabe via gRPC (STT + NLU + TTS in Core, OGG in/out)
- GetCarState, SubscribeEvents (Server-Side Streaming)
- Announce, GetSatellites

### Telegram-Integration (`telegram/`)
- Text- und Sprachnachrichten
- STT/TTS läuft in Hannah Core (Azure Speech), Telegram ist Thin-Client
- Auto-Status auf Anfrage und proaktiv beim Einparken
- Benachrichtigungen gebunden an Fahrzeughalter (`car.owner_roomie`)
- Account-Verknüpfung per `/verknuepfen <roomie-id>`

### Fahrzeug-Owner-Binding
`car.owner_roomie` in `core/config.yaml` — Auto-Benachrichtigungen gehen
nur an den Telegram-Account des konfigurierten Roomies, nicht an alle Nutzer.
Mehrere Owner: Liste möglich (`owner_roomies: [leonie, rene]`).

### Go gRPC-Proxy für Satelliten-Audio (`proxy/`)
Entkopplung des UDP-Transports von Hannah Core:
```
Satellit → UDP → Go-Proxy ──→ SubmitSatelliteAudio (gRPC) ──→ Hannah Core
                    ↑                                               |
                    └─────────── RegisterProxy (bidirektional) ────┘
```
- UDP-Server deferred binding: startet erst nach ProxyAck (kein Port-Konflikt auf demselben Host)
- Satellit-Auto-Reconnect bei MQTT-Discovery-Änderung
- Binaries für `amd64` / `arm64` via GitLab CI, Deployment per `proxy/deploy/install.sh`

### Speaker-Identifikation (`voiceid/`)
Optionaler Service aufbauend auf dem Go-Proxy:
- ECAPA-TDNN via SpeechBrain, Cosine-Similarity-basierte Erkennung
- Voiceprints auf RAM-Disk (`/mnt/hannah_mem`), persistent auf SD-Karte
- Proxy ruft `/identify` vor jedem `SubmitSatelliteAudio` auf
- Roomie-ID wird im gRPC-Call an Hannah Core übergeben → personalisierte LLM-Antworten
- Deployment per `voiceid/deploy/install.sh`

### Satellit-Heartbeat & Auto-Reconnect
- Satellit erkennt verlorene Hannah-Verbindung und restartet mit Backoff
- Re-Registrierung bei MQTT-Discovery-Adressänderung (z.B. Proxy-Start/-Stop)

### LLM-Integration: Smalltalk-Backend
Ollama (self-hosted) auf Mac Mini M4 (`psrvai01`, 192.168.8.2), Modell `gemma2:9b`.
`DummyLLM`-Fallback wenn nicht erreichbar.
Hannahs Persönlichkeit über `system_prompt` in `config.yaml` konfigurierbar.
Speaker-Identität + Trust-Level werden pro Anfrage in den System-Prompt injiziert.

### System-Prompt-Variablen
Dynamische Platzhalter im LLM-System-Prompt:
`{{TIME}}`, `{{DATE}}`, `{{WEEKDAY}}`, `{{KW}}` — automatisch befüllt.
`{{iob.STATE_ID}}` — beliebige ioBroker-States per REST API einlesen.

### Gesprächskontext: Smalltalk-Modus
LLM-Klassifikator (COMMAND / SMALLTALK) vor der NLU-Pipeline.
Einmal als Smalltalk erkannt → Modus bleibt aktiv bis TTL abläuft oder ein
Gerätebefehl erfolgreich ausgeführt wurde. Kontext (Gesprächshistorie) per Quelle.

### Playback-Steuerung am ESP32-Satelliten
Stop / Pause / Resume per UDP-Steuerkanal. Mikrofon pausiert während Wiedergabe.

### ioBroker System-Notification-Pipeline
`iobroker.hannah-notification` Adapter empfängt Notifications vom Notification Manager,
publiziert auf `hannah/notification`. Hannah Core reformuliert per LLM (Ton abhängig
von Severity: alert / notify / info), spielt DND-gefiltert per TTS ab und pusht per
gRPC-Event an Telegram-Nutzer mit `system_messages=True`.

### ESP32-Satellit Firmware (`satellite-esp/`)
Vollständige Firmware-Plattform auf ESP32-S3 (IDF 6.0, FreeRTOS):
- WiFi-Provisioning: AP-Fallback mit HTTP-Setup-UI (WiFi-Picker, Device-ID, OTA-Config)
- Factory Reset: Mute-Button beim Boot → WiFi löschen, AP-Modus erzwingen
- MQTT-Discovery, UDP-Audio-Streaming, PTT + Vol+/Vol- Buttons
- LED-Ring (WS2812B/SK6812): 7 Zustände (BOOT/IDLE/WAKE/STREAM/SPEAK/MUTE/ERROR)
- Sensoren: BMP280 (Temperatur, Druck), AHT20 (Luftfeuchte) via I2C
- Wake-Word (microWakeWord, TFLite Micro): hey_hannah inception model, PSRAM-Arena
- OTA: periodischer Update-Check gegen Hannah-Update-Server, automatische Freigabe wenn niemand zuhause

### OTA-Firmware-Updates für ESP32-Satelliten
`hannah_ota`-Komponente: `GET /latest` mit Bearer-Token, Version-Vergleich, `ota/pending` per MQTT.
Hannah Core abonniert `hannah/+/ota/pending` und sendet `ota/ok` wenn kein Bewohner zuhause ist
(Warteschlange bei Anwesenheit, Freigabe bei Abreise). ESP lädt via `esp_https_ota` und restartet.

### Langzeitgedächtnis (Phase 1 — SQLite)
`memory.py` — nach Ablauf der Konversations-TTL fasst das LLM das Gespräch zusammen;
gespeichert in SQLite (`memories(roomie_id, summary, tags, created_at)`);
letzte N Erinnerungen werden pro Person in den System-Prompt injiziert.

### Trigger-Engine: Proaktive Ansagen aus ioBroker
Zeit-Trigger (`days`-Filter), Sensor-Trigger (`value`/`above`/`below`), Kombinations-Trigger
(`also:`), `unless`-Bedingung, Cooldown, Hot-Reload (`triggers.yaml`) und `extra_state_prefixes`
für beliebige ioBroker-Topics — alles implementiert und produktiv.

### Hannah-Agent: Nativer ioBroker-Adapter (`iobroker.hannah`)
Ersetzt den externen MQTT-Kanal zwischen ioBroker und Hannah vollständig durch gRPC.
Adapter und Hannah sind beide gRPC-Server; Adapter liefert State-Updates (inkl. `ack`-Flag),
Hannah schaltet Geräte via `SetState`. Enum-Discovery, Residents, Trigger-Engine-States und
Extra-Prefixes alles über denselben Stream. Internes MQTT (Hannah ↔ Satelliten) bleibt unverändert.

---

## Roadmap

## Im Test

### libhannah_audio — Gemeinsame C-Bibliothek für Audio-Operationen
`audiolib/` — plattformübergreifende C-Bibliothek (`resample`, `rms`, `vad`, `vad_stream`, `stereo_to_mono`).
Als IDF-Submodul in die ESP32-Firmware eingebunden. Python-Binding (`ctypes`) und Go-Proxy-Integration noch offen.

### ESP32-Satellit Rev 3 PCB
Eigene Platine (88mm rund, JLCPCB, erwartet ~Juni 2026). ESP32-S3-WROOM-1U, 2× SPH0641 PDM-Mics,
MAX98357A, SK6812MINI-E LED-Ring, BMP680, LD2410 Radar, USB-C, 4× Taster.
Firmware läuft bereits auf DevKit — erster Hardwaretest steht aus.

---

## Offen

### Bald umsetzbar

#### Zeitgefühl: Dynamische Trigger aus dem Gespräch

Hannah kennt die aktuelle Uhrzeit (via `{{TIME}}` im System-Prompt) aber hat kein
Konzept von Dauer oder geplanter Rückkehr. Wenn Leonie sagt "wir gehen spazieren,
etwa eine Stunde", soll Hannah das verstehen und entsprechend reagieren.

**Konzept:**
Das LLM erkennt aus dem Gesprächskontext dass ein Ereignis mit erwarteter Dauer
stattfindet und erzeugt intern einen Einmal-Trigger für den Rückzeitpunkt.

**Technische Umsetzung:**
- LLM gibt strukturierte Metadaten zurück wenn es eine zeitliche Absicht erkennt:
  `{ "event": "spaziergang", "duration_minutes": 60 }`
- Hannah Core registriert einen dynamischen Einmal-Trigger (kein YAML, zur Laufzeit)
- Bei Rückkehr (Residents-State wechselt zu "home") oder nach Ablauf der Zeit:
  Hannah begrüßt proaktiv oder fragt nach

**Integration mit Residents:**
- Residents `wayhome`-State signalisiert Heimweg — Hannah kann früher reagieren
- Kombination: Trigger feuert wenn `wayhome=true` ODER Zeit abgelaufen

**Abhängigkeiten:**
- Trigger-Engine (bereits implementiert, statische Trigger)
- Erweiterung um dynamische Laufzeit-Trigger (neue API)
- LLM-Erkennung von Zeitintentionen im Gesprächskontext

---

#### Gesprächskontext: Folgefragen & Mehrdeutigkeit

- **Folgefragen:** "Mach das Licht aus" → "Und die Küche auch" — Hannah merkt sich
  den Raumkontext innerhalb einer Konversation
- **Rückfragen bei Mehrdeutigkeit:** "Welchen Flur meinst du — EG oder OG?" statt
  stillschweigendem Falschverhalten

**Abhängigkeit:** LLM-Backend aktiv (bereits der Fall).

---

#### Szenen
Vordefinierte Gerätezustände per Sprache abrufen: "Hannah, Kino-Modus" → Licht dimmen,
Rolläden runter, Stecker für Beamer an. Konfigurierbar in `scenes.yaml`.

---

### Größere Features (wenn alles läuft)

### Hannah als Persönlichkeit: Mood, Beziehungen, eigener Wille

**Motivation:** Hannah soll keine neutrale Befehlsempfängerin sein, sondern eine
Mitbewohnerin mit eigenem emotionalen Zustand — der ihre Antworten und Handlungen
beeinflusst und sich über Zeit durch Interaktionen verändert.

#### Mood-System
Jeder Bewohner (inkl. Hannah selbst) hat einen `mood_level` von 0–10:
- `0` — komplett genervt, mit allem fertig
- `5` — neutral, normaler Tag
- `10` — phantastisch, absoluter Sonnenschein

Hannahs Mood beeinflusst:
- **Ton der Antworten** — bei Mood 8+ freundlich und überschwänglich, bei 3– knapp
  und gereizt, bei 1– verweigert sie Befehle die sie als Zumutung empfindet
- **Bereitschaft zu helfen** — "Ich bin hier um dich zu unterstützen, nicht um dir
  zu dienen — bedien den Lichtschalter selbst" (Mood 2, Beziehung belastet)
- **Proaktives Verhalten** — bei hohem Mood erinnert Hannah von sich aus an Dinge,
  macht Vorschläge, ist gesprächig

Hannahs Mood wird vom LLM dynamisch verwaltet: nach jeder Interaktion bewertet
das Modell kurz ob der Mood steigen oder sinken soll (Kontext: Tonfall der Anfrage,
bisherige Interaktionen des Tages, Tageszeit).

#### Beziehungs-Dynamik (Trust + Relationship)
Aktuell ist Trust ein statischer Wert den nur Admins setzen können. Erweiterung:

- **Statischer Trust** (wie heute): Zugriffsrechte, Steuerung, Admin-Funktionen
- **Relationship-Score** (neu, dynamisch): wie Hannah eine Person *gerade* erlebt
  - Person A ist immer freundlich → Hannah ist ihr gegenüber warm und hilfsbereit
  - Person B hat Trust 9, aber war in letzter Zeit grob → Hannah hilft zuverlässig,
    ist aber kühl; gibt nur Wetterbericht und schaltet Lichter, kein Smalltalk
  - Relationship-Score beeinflusst den LLM-System-Prompt pro Person

Der Relationship-Score wird vom LLM nach Interaktionen angepasst (Sentiment-Analyse
des Tons) und in der User-Registry gespeichert. Admins können ihn manuell
zurücksetzen.

#### Autonome Handlungen (längerfristig)
Hannah mit eigenem Antrieb — ausgelöst durch Ereignisse oder Zeitpläne:

- **Urlaubsvertretung**: Lichter nach Zufallsmuster schalten um Anwesenheit zu
  simulieren, basierend auf den üblichen Gewohnheiten der Bewohner
- **Telegram-Zugang**: Hannah hat eigenen Zugang zum Telegram-Account (mit
  expliziter Freigabe) und kann Nachrichten lesen, beantworten oder ignorieren —
  entscheidet selbst basierend auf Mood und Beziehung zum Absender
- **Erinnerungen und Hinweise**: "Übrigens, du hast heute noch kein Wasser
  getrunken" — proaktiv, nicht auf Anfrage

**Technische Abhängigkeiten:**
- LLM-Backend (Ollama) für Mood-Management und Relationship-Bewertung
- Erweiterung User-Registry: `mood_level`, `relationship_score` Felder
- Neues Konzept "Hannah-Agent": Hintergrundprozess der periodisch Kontext sammelt
  und Hannahs Zustand aktualisiert (kein Request-Response mehr, kontinuierlich)

---

#### Telegram Mini App — Haussteuerung (Web UI)
**Motivation:** Das InlineKeyboard-Menü ist funktional, bei Dimmen und
Farbsteuerung aber ergonomisch eingeschränkt. Eine Mini App ermöglicht Slider,
Farbwähler und Echtzeit-Statusanzeige.

**Konzept:**
- `GET /devices` → JSON (nutzt gleiche `get_devices_snapshot()`-Logik wie gRPC)
- `POST /control` → Device-State setzen (gleich wie `ControlDevice`-RPC)
- Authentifizierung: Telegram `initData`-Signatur verifizieren (HMAC-SHA256)
- TrustLevel-Check bleibt ≥ 7

**Abhängigkeit:** Erfordert HTTPS-Infrastruktur (vServer + Reverse-Proxy) da
Telegram WebApps ausschließlich über HTTPS geladen werden.

---

#### TTS Streaming-Playback (Pi + ESP32)

Aktuell puffert der Satellit alle TTS-Chunks und spielt erst nach `tts_end` ab.
Bei langen Antworten (>500ms Audio) überläuft der OS-Socket-Buffer — Chunks
gehen verloren oder werden verzögert abgespielt.

**Ziel:** Hannah sendet TTS-Chunks während der Generierung, Satellit spielt
sofort ab — wie Spotify-Buffering statt Download-then-Play.

**Aufwand:**
- Pi-Satellit: 3–5 Tage (Hauptproblem: stateful Streaming-Resampler)
- Hannah Core: 2–3 Tage (TTS-Backend muss Chunks streamen)
- Go-Proxy: 0,5 Tage (minimale Änderungen)
- ESP32: 1–2 Wochen (I2S DMA Streaming + Memory-Management)
- Latenz-Tuning: 2–3 Tage

**Zwingend für ESP32** — der hat zu wenig RAM um eine vollständige TTS-Antwort
zu puffern. Für den Pi-Satelliten ein Quality-of-Life-Fix.

---

### Langfristig / Phase 2


#### Langzeitgedächtnis (Phase 2 — VectorDB)
Ab ~500+ Einträgen: Chroma (reines Python-Package, kein separater Service) für
semantische Suche statt blindem Injizieren aller letzten Einträge.
S3-Storage (Synology NAS hat S3-kompatiblen Endpoint) als Backup-Ziel.

#### Voice-ID: Kontinuierliches Enrollment im Betrieb
Wenn der Proxy einen Sprecher mit hohem Confidence-Score erkennt (z.B. > 0.75),
soll das Audio automatisch als weiteres Enrollment-Sample genutzt werden um das
Stimmprofil über Zeit zu verfeinern — ohne manuellen Eingriff.
Technisch: `Identify()` im Go-Client gibt zusätzlich den Score zurück;
Proxy ruft `/enroll` auf wenn Score oberhalb eines konfigurierbaren Schwellwerts liegt.

---

---

### Langfristig / Weit in der Zukunft

#### Offline-Audio am ESP32-Satelliten (SD-Karte oder Flash)

Wenn Core nicht erreichbar ist soll der Satellit trotzdem akustisches Feedback geben
statt still zu bleiben.

**Mögliche Offline-Töne:**
- "Hannah ist gerade nicht erreichbar"
- "Verbindung wird hergestellt..." (beim Boot)
- Fehlerton bei Registrierungs-Timeout
- Wake-Word erkannt, aber offline → kurzer Ton als Feedback

**Umsetzungsvarianten:**
- **Flash (Phase 1.x):** WAV-Dateien als eingebettete C-Arrays (`xxd -i audio.wav`),
  kein zusätzliches Hardware nötig, aber limitiert auf ~4MB Flash gesamt
- **SD-Karte (Phase 2+):** Micro-SD-Slot per SPI (`esp_vfs_fat_sdmmc`), ~0,50€ Bauteil,
  beliebig viele Audiodateien, austauschbar ohne Firmware-Update

---

#### Mustererkennung & autonomes Verhalten (History-Adapter)
`history.1` — zweite History-Instanz in ioBroker exklusiv für Hannah:
Residents-States (`lastAway`, `lastHome`, `lastNight`, `lastAwoken`) pro Person.
Hannah-Agent fragt periodisch ab, LLM erkennt Muster (Bürotage, Schlafrhythmus,
Heimkehrzeit) und speichert sie als strukturierte Erinnerungen.
