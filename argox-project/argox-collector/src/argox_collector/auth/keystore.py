"""DuckDB-backed store for hashed API keys (COL-09).

Keys live in an ``api_keys`` table inside the Collector's index DB (the same
DuckDB file as the span index, per the ticket). Only the SHA-256 hash of each
key is stored; lookups hash the presented credential and match on the hash
column, so the raw secret never has to be compared in plaintext.

A dedicated DuckDB connection is opened on the index path. DuckDB shares one
in-process database instance per file, so this coexists with the trace index's
connection; writes here are rare (admin operations) and guarded by a local lock.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import duckdb
import structlog

from argox_collector.auth.keys import ApiKeyRecord
from argox_collector.auth.principal import Scope, parse_scopes

logger = structlog.get_logger(__name__)


class ApiKeyStoreError(RuntimeError):
    """Raised when the API key store cannot complete an operation."""


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc)


class ApiKeyStore:
    """CRUD for hashed API keys over a DuckDB table."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR,
                    key_hash VARCHAR UNIQUE,
                    key_prefix VARCHAR,
                    scopes VARCHAR,
                    created_at TIMESTAMP,
                    created_by VARCHAR,
                    revoked_at TIMESTAMP
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (key_hash)"
            )

    def create(self, record: ApiKeyRecord) -> ApiKeyRecord:
        """Persist a new key record.

        Raises:
            ApiKeyStoreError: If a key with the same id or hash already exists.
        """
        scopes_json = json.dumps(sorted(scope.value for scope in record.scopes))
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO api_keys (
                        id, name, key_hash, key_prefix,
                        scopes, created_at, created_by, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.name,
                        record.key_hash,
                        record.key_prefix,
                        scopes_json,
                        _to_naive_utc(record.created_at),
                        record.created_by,
                        _to_naive_utc(record.revoked_at)
                        if record.revoked_at
                        else None,
                    ),
                )
            except duckdb.ConstraintException as exc:
                raise ApiKeyStoreError("api key already exists") from exc
        return record

    def get_by_hash(self, key_hash: str) -> Optional[ApiKeyRecord]:
        """Return the key with this hash, or ``None`` if there is no match.

        Runs on a dedicated cursor off the write lock — authentication is on the
        request hot path and must not serialise behind a rare key write.
        """
        cursor = self._conn.cursor()
        try:
            rows = cursor.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
            ).fetchall()
        finally:
            cursor.close()
        if not rows:
            return None
        return self._row_to_record(rows[0])

    def list(self) -> List[ApiKeyRecord]:
        """Return every stored key, newest first. Never exposes hashes to callers."""
        cursor = self._conn.cursor()
        try:
            rows = cursor.execute(
                "SELECT * FROM api_keys ORDER BY created_at DESC, id"
            ).fetchall()
        finally:
            cursor.close()
        return [self._row_to_record(row) for row in rows]

    def revoke(self, key_id: str) -> bool:
        """Mark a key revoked. Returns ``False`` if no such active key existed.

        Idempotent: revoking an already-revoked key leaves the original
        ``revoked_at`` untouched and returns ``False``.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE api_keys SET revoked_at = ? "
                "WHERE id = ? AND revoked_at IS NULL",
                (_to_naive_utc(datetime.now(timezone.utc)), key_id),
            )
            changed = cursor.fetchall()
        return bool(changed and changed[0][0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_record(row: tuple) -> ApiKeyRecord:
        # Column order matches the CREATE TABLE above.
        scopes = _decode_scopes(row[4])
        return ApiKeyRecord(
            id=row[0],
            name=row[1],
            key_hash=row[2],
            key_prefix=row[3],
            scopes=scopes,
            created_at=_to_aware_utc(row[5]),
            created_by=row[6],
            revoked_at=_to_aware_utc(row[7]),
        )


def _decode_scopes(raw: Optional[str]) -> frozenset[Scope]:
    """Decode the stored scope JSON, dropping any value no longer recognised.

    An unknown scope (e.g. one removed in a later release) is logged and skipped
    rather than failing the whole key load — a stale scope must not lock the
    operator out of an otherwise valid key.
    """
    if not raw:
        return frozenset()
    try:
        values = json.loads(raw)
    except (ValueError, TypeError):
        return frozenset()
    try:
        return parse_scopes(values)
    except ValueError as exc:
        logger.warning("api_key_unknown_scope", error=str(exc))
        known = []
        for value in values:
            try:
                known.append(Scope(value))
            except ValueError:
                continue
        return frozenset(known)
