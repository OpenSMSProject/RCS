import os
import sqlite3
import threading
import time
import uuid
from typing import Optional

from .security import hash_secret, verify_secret


TERMINAL_STATES = {"sent", "failed"}
NONTERMINAL_STATES = {"queued", "waiting_device", "dispatching", "acknowledged"}
VALID_STATES = NONTERMINAL_STATES | TERMINAL_STATES
ALLOWED_TRANSITIONS = {
    "queued": {"waiting_device", "dispatching", "failed"},
    "waiting_device": {"dispatching", "failed"},
    "dispatching": {"dispatching", "waiting_device", "acknowledged", "sent", "failed"},
    "acknowledged": {"dispatching", "sent", "failed"},
    "sent": set(),
    "failed": set(),
}


class GatewayStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        if db_path != ":memory:":
            directory = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    used_at REAL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pairing_codes_active
                    ON pairing_codes(expires_at, used_at);

                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    credential_hash TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    last_seen_at REAL,
                    online INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    to_number TEXT NOT NULL,
                    text TEXT NOT NULL,
                    state TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    acknowledged_at REAL,
                    completed_at REAL,
                    error_code TEXT,
                    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(device_id) REFERENCES devices(device_id)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_device_state
                    ON messages(device_id, state, created_at);
                """
            )

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[dict]:
        return dict(row) if row is not None else None

    def create_pairing_code(self, code: str, ttl_seconds: int = 300, now: Optional[float] = None) -> dict:
        if not code:
            raise ValueError("pairing code is required")
        now = time.time() if now is None else float(now)
        expires = now + int(ttl_seconds)
        encoded = hash_secret(code)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO pairing_codes(code_hash, expires_at, used_at, created_at) VALUES (?, ?, NULL, ?)",
                (encoded, expires, now),
            )
            pairing_id = cur.lastrowid
        return {"id": pairing_id, "expires_at": expires, "created_at": now}

    def consume_pairing_code(self, code: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else float(now)
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT id, code_hash FROM pairing_codes WHERE used_at IS NULL AND expires_at >= ? ORDER BY id DESC",
                (now,),
            ).fetchall()
            for row in rows:
                if verify_secret(code, row["code_hash"]):
                    updated = self._conn.execute(
                        "UPDATE pairing_codes SET used_at=? WHERE id=? AND used_at IS NULL AND expires_at>=?",
                        (now, row["id"], now),
                    ).rowcount
                    return updated == 1
        return False

    def pair_device(self, code: str, device_id: str, name: str, credential: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else float(now)
        credential_hash = hash_secret(credential)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if self._conn.execute("SELECT 1 FROM devices WHERE device_id=?", (device_id,)).fetchone():
                    raise ValueError("device_exists")
                rows = self._conn.execute(
                    "SELECT id, code_hash FROM pairing_codes WHERE used_at IS NULL AND expires_at >= ? ORDER BY id DESC",
                    (now,),
                ).fetchall()
                pairing_id = None
                for row in rows:
                    if verify_secret(code, row["code_hash"]):
                        pairing_id = row["id"]
                        break
                if pairing_id is None:
                    self._conn.execute("ROLLBACK")
                    return False
                updated = self._conn.execute(
                    "UPDATE pairing_codes SET used_at=? WHERE id=? AND used_at IS NULL AND expires_at>=?",
                    (now, pairing_id, now),
                ).rowcount
                if updated != 1:
                    self._conn.execute("ROLLBACK")
                    return False
                self._conn.execute(
                    "INSERT INTO devices(device_id, name, credential_hash, enabled, created_at, online) VALUES (?, ?, ?, 1, ?, 0)",
                    (device_id, name, credential_hash, now),
                )
                self._conn.execute("COMMIT")
                return True
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def create_device(self, device_id: str, name: str, credential: str, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else float(now)
        encoded = hash_secret(credential)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO devices(device_id, name, credential_hash, enabled, created_at, online) VALUES (?, ?, ?, 1, ?, 0)",
                (device_id, name, encoded, now),
            )
        return self.get_device(device_id)

    def get_device(self, device_id: str, include_secret_hash: bool = False) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        data = self._row(row)
        if data is None:
            return None
        data["enabled"] = bool(data["enabled"])
        data["online"] = bool(data["online"])
        if not include_secret_hash:
            data.pop("credential_hash", None)
        return data

    def list_devices(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM devices ORDER BY created_at, device_id").fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["enabled"] = bool(data["enabled"])
            data["online"] = bool(data["online"])
            data.pop("credential_hash", None)
            result.append(data)
        return result

    def verify_device_credential(self, device_id: str, credential: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT credential_hash, enabled FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return bool(row and row["enabled"] and verify_secret(credential, row["credential_hash"]))

    def revoke_device(self, device_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE devices SET enabled=0, online=0 WHERE device_id=?", (device_id,))

    def set_device_online(self, device_id: str, online: bool, now: Optional[float] = None) -> None:
        now = time.time() if now is None else float(now)
        with self._lock, self._conn:
            if online:
                self._conn.execute("UPDATE devices SET online=1, last_seen_at=? WHERE device_id=? AND enabled=1", (now, device_id))
            else:
                self._conn.execute("UPDATE devices SET online=0 WHERE device_id=?", (device_id,))

    def touch_device(self, device_id: str, now: Optional[float] = None) -> None:
        now = time.time() if now is None else float(now)
        with self._lock, self._conn:
            self._conn.execute("UPDATE devices SET last_seen_at=?, online=1 WHERE device_id=? AND enabled=1", (now, device_id))

    def create_message(self, device_id: str, to_number: str, text: str, idempotency_key: Optional[str] = None, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else float(now)
        if idempotency_key:
            with self._lock:
                existing = self._conn.execute("SELECT * FROM messages WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                return dict(existing)
        message_id = f"msg_{uuid.uuid4().hex}"
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    """INSERT INTO messages(message_id, device_id, to_number, text, state, idempotency_key,
                       created_at, updated_at, dispatch_attempts) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, 0)""",
                    (message_id, device_id, to_number, text, idempotency_key, now, now),
                )
        except sqlite3.IntegrityError:
            if idempotency_key:
                with self._lock:
                    existing = self._conn.execute("SELECT * FROM messages WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if existing:
                    return dict(existing)
            raise
        return self.get_message(message_id)

    def get_message_by_idempotency(self, idempotency_key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return self._row(row)

    def ready(self) -> bool:
        try:
            with self._lock:
                return self._conn.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def get_message(self, message_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
        return self._row(row)

    def transition_message(self, message_id: str, new_state: str, error_code: Optional[str] = None, now: Optional[float] = None) -> dict:
        if new_state not in VALID_STATES:
            raise ValueError("invalid message state")
        now = time.time() if now is None else float(now)
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM messages WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                raise KeyError(message_id)
            old_state = row["state"]
            if new_state != old_state and new_state not in ALLOWED_TRANSITIONS[old_state]:
                raise ValueError(f"invalid transition {old_state}->{new_state}")
            acknowledged_at = row["acknowledged_at"]
            completed_at = row["completed_at"]
            attempts = row["dispatch_attempts"]
            if new_state == "dispatching" and old_state != "dispatching":
                attempts += 1
            if new_state == "acknowledged" and acknowledged_at is None:
                acknowledged_at = now
            if new_state in TERMINAL_STATES:
                completed_at = now
            self._conn.execute(
                """UPDATE messages SET state=?, updated_at=?, acknowledged_at=?, completed_at=?, error_code=?, dispatch_attempts=?
                   WHERE message_id=?""",
                (new_state, now, acknowledged_at, completed_at, error_code, attempts, message_id),
            )
        return self.get_message(message_id)

    def list_dispatchable(self, device_id: str, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM messages WHERE device_id=? AND state IN ('queued','waiting_device','dispatching','acknowledged')
                   ORDER BY created_at, message_id LIMIT ?""",
                (device_id, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]
