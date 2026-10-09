import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import ValidationError

logger = logging.getLogger(__name__)


@dataclass
class OAuthConnection:
    token: str = field(repr=False)
    session_id: str
    identity_id: str
    client_id: str
    expires_at: float
    scopes: list[str] = field(default_factory=list)
    state: str = "active"


class OAuthConnectionStore(Protocol):
    """Storage contract for OAuth clients and their managed Connhex sessions."""

    def get_client(
        self, client_id: str
    ) -> OAuthClientInformationFull | None: ...

    def put_client(self, client_info: OAuthClientInformationFull) -> None: ...

    def get_connection(self, token: str) -> OAuthConnection | None: ...

    def put_connection(self, record: OAuthConnection) -> None: ...

    def active_connections(self) -> list[OAuthConnection]: ...

    def update_expiry(self, token: str, expires_at: float) -> None: ...

    def deactivate(self, token: str, state: str = "invalid") -> None: ...


class SQLiteOAuthConnectionStore:
    """Persist OAuth clients and encrypted sessions across server restarts."""

    def __init__(self, path: str, encryption_key: str):
        self.path = Path(path)
        self._cipher = Fernet(encryption_key.encode())
        if not self.path.parent.exists():
            raise ValueError(
                f"OAuth store directory does not exist: {self.path.parent}"
            )
        if not self.path.parent.is_dir():
            raise ValueError(
                f"OAuth store parent is not a directory: {self.path.parent}"
            )
        try:
            self._ensure_schema()
            self._validate_encryption_key()
        except sqlite3.Error as exc:
            raise ValueError(
                f"Unable to initialize OAuth SQLite store at {self.path}"
            ) from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    client_info TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oauth_connections (
                    token_hash TEXT PRIMARY KEY,
                    encrypted_token TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    scopes TEXT NOT NULL,
                    state TEXT NOT NULL
                )
            """)

    def _validate_encryption_key(self) -> None:
        # Include revoked records: wrong keys must fail before serving traffic.
        with self._connect() as conn:
            for row in conn.execute("SELECT * FROM oauth_connections"):
                self._decode(row)

    def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT client_info FROM oauth_clients WHERE client_id = ?",
                    (client_id,),
                ).fetchone()
        except sqlite3.Error:
            logger.warning(
                "Failed to load OAuth client %s from SQLite store",
                client_id,
                exc_info=True,
            )
            return None

        if row is None:
            return None

        try:
            return OAuthClientInformationFull.model_validate(
                json.loads(row["client_info"])
            )
        except (json.JSONDecodeError, TypeError, ValidationError):
            logger.warning(
                "Ignoring invalid persisted OAuth client %s",
                client_id,
                exc_info=True,
            )
            return None

    def put_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            return

        now = int(time.time())
        payload = json.dumps(
            client_info.model_dump(mode="json"),
            sort_keys=True,
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_clients (
                    client_id,
                    client_info,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    client_info = excluded.client_info,
                    updated_at = excluded.updated_at
                """,
                (client_info.client_id, payload, now, now),
            )

    @staticmethod
    def _token_hash(token: str) -> str:
        return sha256(token.encode()).hexdigest()

    def _decode(self, row: sqlite3.Row) -> OAuthConnection:
        try:
            token = self._cipher.decrypt(
                row["encrypted_token"].encode()
            ).decode()
            if self._token_hash(token) != row["token_hash"]:
                raise ValueError("Token hash mismatch")
            return OAuthConnection(
                token=token,
                session_id=row["session_id"],
                identity_id=row["identity_id"],
                client_id=row["client_id"],
                expires_at=row["expires_at"],
                scopes=json.loads(row["scopes"]),
                state=row["state"],
            )
        except (InvalidToken, ValueError, UnicodeError, TypeError) as exc:
            raise ValueError(
                "Unable to decrypt OAuth connection store"
            ) from exc

    def get_connection(self, token: str) -> OAuthConnection | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM oauth_connections WHERE token_hash = ?",
                (self._token_hash(token),),
            ).fetchone()
        return self._decode(row) if row else None

    def active_connections(self) -> list[OAuthConnection]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM oauth_connections WHERE state = 'active'"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def put_connection(self, record: OAuthConnection) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO oauth_connections (
                    token_hash, encrypted_token, session_id, identity_id,
                    client_id, expires_at, scopes, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_hash) DO NOTHING
                """,
                (
                    self._token_hash(record.token),
                    self._cipher.encrypt(record.token.encode()).decode(),
                    record.session_id,
                    record.identity_id,
                    record.client_id,
                    record.expires_at,
                    json.dumps(record.scopes),
                    record.state,
                ),
            )

    def update_expiry(self, token: str, expires_at: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE oauth_connections SET expires_at = ? "
                "WHERE token_hash = ? AND state = 'active'",
                (expires_at, self._token_hash(token)),
            )

    def deactivate(self, token: str, state: str = "invalid") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE oauth_connections SET state = ? WHERE token_hash = ?",
                (state, self._token_hash(token)),
            )
