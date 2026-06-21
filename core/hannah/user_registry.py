"""
Hannah User Registry

Persistente Nutzerdatenbank die ioBroker Residents als Quelle der Wahrheit verwendet,
aber eigene Felder (UUID, Trust Level, Linked Accounts) hinzufügt.

Sync-Strategie:
  - Beim Start einmalig synchronisieren
  - Danach alle sync_interval Sekunden im Hintergrund
  - Neue Roomies werden angelegt, gelöschte werden deaktiviert (nicht gelöscht)

Dieses Modul hat kein MQTT/gRPC — es ist reine Datenhaltung mit einem
fetch-Callable als einziger externer Abhängigkeit. So bleibt es
leicht wrappbar (REST, gRPC, etc.) ohne die Logik zu duplizieren.
"""
import logging
import sqlite3
import threading
import time
import uuid as _uuid
from typing import Callable, Iterable, Optional
from hannah.proto import hannah_pb2 as pb
from hannah.residents import Resident, Roomie, Guest, Pet

log = logging.getLogger(__name__)

_RESIDENT_TYPE_CLASSES = {
    pb.ResidentType.ROOMIE: Roomie,
    pb.ResidentType.GUEST: Guest,
    pb.ResidentType.PET: Pet,
}


class User:
    """
    Decorator um Resident (Roomie/Guest/Pet) — fügt Registry-Felder hinzu
    (UUID, Trust Level, System-Messages), die nichts mit Presence zu tun haben.

    In einem SmartHome sind Haustiere genauso Anwender wie Menschen — daher
    bekommt auch Pet ein trust_level (z.B. um eine elektronische Katzenklappe
    erst ab einem bestimmten Trust-Level zu öffnen).
    """

    def __init__(self, resident: Resident, uuid: str, trust_level: int = 5, system_messages: bool = False):
        self.resident = resident
        self.uuid = uuid
        self.trust_level = trust_level
        self.system_messages = system_messages

    @property
    def roomie_id(self) -> str:
        return self.resident.roomie_id

    @property
    def display_name(self) -> str:
        return self.resident.display_name


class UserRegistry:
    def __init__(
        self,
        cfg: dict,
        hannah_roomie: str = "hannah",
    ):
        """
        cfg           : user_registry-Abschnitt aus config.yaml
        fetch_roomies : fn() → {roomie_id: display_name}
                        Wird beim Sync aufgerufen (z.B. iobroker.list_roomies).
        hannah_roomie : Roomie-ID von Hannah selbst — bekommt immer trust_level=10.
        """
        self._db_path       = cfg.get("db_path", "hannah_users.db")
        self._sync_interval = int(cfg.get("sync_interval", 60))
        self._hannah_roomie = hannah_roomie
        self._lock          = threading.Lock()
        self._residents_client = None  # set via set_residents_client(), late-binding (ResidentsClient entsteht erst nach UserRegistry in main.py)
        self._users: dict[str, User] = {}
        self._init_db()

    def set_residents_client(self, residents_client):
        """Verbindet die Registry mit ResidentsClient, damit sync() Resident-Instanzen (Roomie/Guest/Pet) für die User-Wrapper holen kann."""
        self._residents_client = residents_client

    # ------------------------------------------------------------------
    # Schema

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    uuid            TEXT    PRIMARY KEY,
                    roomie_id       TEXT    NOT NULL,
                    type            TEXT,
                    display_name    TEXT    NOT NULL,
                    trust_level     INTEGER NOT NULL DEFAULT 5,
                    system_messages INTEGER NOT NULL DEFAULT 0,
                    active          INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(roomie_id, type)
                );
            """)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            # Migration: system_messages column for existing DBs
            if "system_messages" not in existing:
                conn.execute("ALTER TABLE users ADD COLUMN system_messages INTEGER NOT NULL DEFAULT 0")
            # Migration: roomie_id war früher alleine UNIQUE — ein Gast und ein Roomie
            # mit demselben Namen (unterschiedliche Präfixe im Residents-Adapter)
            # hätten kollidiert. SQLite kann ein Spalten-UNIQUE nicht per ALTER TABLE
            # ändern, daher Table-Rebuild. Bestandszeilen bekommen type=NULL (der
            # echte Typ war vor dieser Migration nie gespeichert) — sync() trägt ihn
            # beim nächsten Lauf anhand der echten ioBroker-Daten nach, ohne Duplikate.
            if "type" not in existing:
                conn.executescript("""
                    ALTER TABLE users RENAME TO users_old;
                    CREATE TABLE users (
                        uuid            TEXT    PRIMARY KEY,
                        roomie_id       TEXT    NOT NULL,
                        type            TEXT,
                        display_name    TEXT    NOT NULL,
                        trust_level     INTEGER NOT NULL DEFAULT 5,
                        system_messages INTEGER NOT NULL DEFAULT 0,
                        active          INTEGER NOT NULL DEFAULT 1,
                        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                        updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                        UNIQUE(roomie_id, type)
                    );
                    INSERT INTO users (uuid, roomie_id, display_name, trust_level, system_messages, active, created_at, updated_at)
                        SELECT uuid, roomie_id, display_name, trust_level, system_messages, active, created_at, updated_at FROM users_old;
                    DROP TABLE users_old;
                """)
                log.info("UserRegistry: Schema-Migration — Spalte 'type' ergänzt, UNIQUE(roomie_id) → UNIQUE(roomie_id, type)")
            conn.executescript("""

                CREATE TABLE IF NOT EXISTS linked_accounts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uuid   TEXT    NOT NULL REFERENCES users(uuid),
                    service     TEXT    NOT NULL,
                    account_id  TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(service, account_id)
                );
            """)

    # ------------------------------------------------------------------
    # Sync mit ioBroker

    def sync(self, residents: Iterable[pb.AgentResident]) -> tuple[int, int]:
        """
        Gleicht Registry mit ioBroker ab. Roomies, Guests und Pets bekommen alle
        einen User-Eintrag inkl. trust_level — im SmartHome sind Haustiere genauso
        Anwender wie Menschen, nur i.d.R. mit niedrigerem Trust-Level.
        Gibt (added, deactivated) zurück.
        """
        residents = list(residents)
        added = deactivated = 0

        log.info(f"UserRegistry: Sync gestartet ({len(residents)} Residents von ioBroker)")

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT uuid, roomie_id, type, trust_level, system_messages FROM users"
            ).fetchall()
            # (roomie_id, type) -> (uuid, trust_level, system_messages). type kann NULL sein
            # für Altzeilen von vor der Type-Spalte — die werden unten beim ersten Treffer
            # auf den echten Typ migriert statt ein Duplikat anzulegen.
            by_key: dict[tuple[str, Optional[str]], tuple[str, int, int]] = {
                (roomie_id, type_): (uuid_, trust_level, system_messages_int)
                for uuid_, roomie_id, type_, trust_level, system_messages_int in rows
            }
            matched_uuids: set[str] = set()

            for r in residents:
                roomie_id = r.roomie_id
                type_name = pb.ResidentType.Name(r.type)
                display_name = r.name or roomie_id
                is_hannah = (roomie_id == self._hannah_roomie)

                row = by_key.get((roomie_id, type_name))
                legacy_untyped = row is None and (roomie_id, None) in by_key
                if legacy_untyped:
                    row = by_key[(roomie_id, None)]

                if row is None:
                    user_uuid = str(_uuid.uuid4())
                    trust_level = 10 if is_hannah else 5
                    system_messages = False
                    conn.execute(
                        "INSERT INTO users (uuid, roomie_id, type, display_name, trust_level)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (user_uuid, roomie_id, type_name, display_name, trust_level),
                    )
                    log.info(
                        f"UserRegistry: +{display_name!r} ({roomie_id}/{type_name})"
                        f" trust={trust_level} → {user_uuid}"
                    )
                    added += 1
                    by_key[(roomie_id, type_name)] = (user_uuid, trust_level, 0)
                else:
                    user_uuid, trust_level, system_messages_int = row
                    system_messages = bool(system_messages_int)
                    if legacy_untyped:
                        # Altzeile ohne Typ jetzt auf den echten Typ migrieren statt Duplikat anzulegen;
                        # aus by_key entfernen, damit ein zweiter Resident mit gleichem roomie_id
                        # aber anderem Typ (z.B. Gast "leonie" neben Roomie "leonie") im selben
                        # Sync-Lauf nicht denselben Altbestand nochmal trifft.
                        conn.execute(
                            "UPDATE users SET type = ?, updated_at = datetime('now') WHERE uuid = ?",
                            (type_name, user_uuid),
                        )
                        log.info(f"UserRegistry: {roomie_id!r} → Typ nachträglich auf {type_name} gesetzt (Schema-Migration)")
                        del by_key[(roomie_id, None)]
                        by_key[(roomie_id, type_name)] = (user_uuid, trust_level, system_messages_int)
                    if is_hannah and trust_level != 10:
                        # Hannah bekommt immer trust_level=10, auch wenn sie schon existiert
                        trust_level = 10
                        conn.execute(
                            "UPDATE users SET trust_level = 10, updated_at = datetime('now') WHERE uuid = ?",
                            (user_uuid,),
                        )
                    # Wiederkehrende Residents reaktivieren (z.B. nach ioBroker-Neustart) — idempotent
                    conn.execute(
                        "UPDATE users SET active = 1, updated_at = datetime('now') WHERE uuid = ?",
                        (user_uuid,),
                    )

                matched_uuids.add(user_uuid)

                if self._residents_client is not None:
                    cls = _RESIDENT_TYPE_CLASSES.get(r.type)
                    if cls is not None:
                        resident_obj = self._residents_client.get_or_create(roomie_id, cls)
                        self._users[user_uuid] = User(
                            resident_obj, uuid=user_uuid, trust_level=trust_level, system_messages=system_messages,
                        )

            # In ioBroker gelöschte Residents deaktivieren
            for uuid_, roomie_id, type_, _trust_level, _system_messages in rows:
                if uuid_ not in matched_uuids:
                    conn.execute(
                        "UPDATE users SET active = 0, updated_at = datetime('now') WHERE uuid = ?",
                        (uuid_,),
                    )
                    log.info(f"UserRegistry: -{roomie_id!r} ({type_}) (in ioBroker gelöscht) → deaktiviert")
                    deactivated += 1
                    self._users.pop(uuid_, None)

            conn.commit()

        if added or deactivated:
            log.info(f"UserRegistry: Sync abgeschlossen (+{added} / -{deactivated} )")
        return added, deactivated

    # ------------------------------------------------------------------
    # Abfragen

    def get_all(self, include_inactive: bool = False) -> list[dict]:
        """Gibt alle Nutzer mit ihren verknüpften Accounts zurück."""
        where = "" if include_inactive else "WHERE u.active = 1"
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT
                    u.uuid, u.roomie_id, u.display_name,
                    u.trust_level, u.system_messages, u.active,
                    u.created_at, u.updated_at,
                    GROUP_CONCAT(la.service || ':' || la.account_id) AS linked_accounts
                FROM users u
                LEFT JOIN linked_accounts la ON la.user_uuid = u.uuid
                {where}
                GROUP BY u.uuid
                ORDER BY u.display_name
            """).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_by_roomie(self, roomie_id: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT u.*, GROUP_CONCAT(la.service || ':' || la.account_id) AS linked_accounts
                FROM users u
                LEFT JOIN linked_accounts la ON la.user_uuid = u.uuid
                WHERE u.roomie_id = ? AND u.active = 1
                GROUP BY u.uuid
            """, (roomie_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_by_uuid(self, user_uuid: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT u.*, GROUP_CONCAT(la.service || ':' || la.account_id) AS linked_accounts
                FROM users u
                LEFT JOIN linked_accounts la ON la.user_uuid = u.uuid
                WHERE u.uuid = ?
                GROUP BY u.uuid
            """, (user_uuid,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_by_linked_account(self, service: str, account_id: str) -> Optional[dict]:
        """Sucht einen Nutzer anhand eines verknüpften Accounts (z.B. Telegram-ID)."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT u.* FROM users u
                JOIN linked_accounts la ON la.user_uuid = u.uuid
                WHERE la.service = ? AND la.account_id = ? AND u.active = 1
            """, (service, str(account_id))).fetchone()
        return _row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Mutationen

    def link_account(self, roomie_id: str, service: str, account_id: str) -> bool:
        """Verknüpft einen externen Account (z.B. Telegram) mit einem Roomie."""
        user = self.get_by_roomie(roomie_id)
        if not user:
            log.warning(f"UserRegistry: link_account — Roomie {roomie_id!r} nicht gefunden")
            return False
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO linked_accounts (user_uuid, service, account_id)"
                " VALUES (?, ?, ?)",
                (user["uuid"], service, str(account_id)),
            )
        log.info(f"UserRegistry: {roomie_id} → {service}:{account_id} verknüpft")
        return True

    def unlink_account(self, service: str, account_id: str) -> bool:
        with self._lock, self._connect() as conn:
            c = conn.execute(
                "DELETE FROM linked_accounts WHERE service = ? AND account_id = ?",
                (service, str(account_id)),
            )
        return c.rowcount > 0

    def set_trust_level(self, roomie_id: str, level: int) -> bool:
        level = max(0, min(10, level))
        with self._lock, self._connect() as conn:
            c = conn.execute(
                "UPDATE users SET trust_level = ?, updated_at = datetime('now')"
                " WHERE roomie_id = ? AND active = 1",
                (level, roomie_id),
            )
        return c.rowcount > 0

    def set_system_messages(self, roomie_id: str, enabled: bool) -> bool:
        """Aktiviert/deaktiviert System-Notifications für einen Nutzer."""
        with self._lock, self._connect() as conn:
            c = conn.execute(
                "UPDATE users SET system_messages = ?, updated_at = datetime('now')"
                " WHERE roomie_id = ? AND active = 1",
                (1 if enabled else 0, roomie_id),
            )
        return c.rowcount > 0

    def get_system_message_recipients(self) -> list[dict]:
        """Gibt alle aktiven Nutzer zurück, die System-Notifications erhalten sollen."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT u.*, GROUP_CONCAT(la.service || ':' || la.account_id) AS linked_accounts
                FROM users u
                LEFT JOIN linked_accounts la ON la.user_uuid = u.uuid
                WHERE u.active = 1 AND u.system_messages = 1
                GROUP BY u.uuid
            """).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # linked_accounts als Liste parsen statt kommasepariertem String
    raw = d.get("linked_accounts")
    if raw:
        accounts: dict[str, str] = {}
        for entry in raw.split(","):
            if ":" in entry:
                svc, aid = entry.split(":", 1)
                accounts[svc] = aid
        d["linked_accounts"] = accounts
    else:
        d["linked_accounts"] = {}
    return d
