"""API key generation, hashing and the stored key record (COL-09).

Keys are minted as ``argox_<base64url-secret>`` where the secret carries 256
bits of entropy from :func:`secrets.token_urlsafe`. Because the secret is
high-entropy random data — not a user-chosen password — a single SHA-256 is the
right hash: it is preimage-resistant and constant-cost, and the slow,
salted KDFs (bcrypt/argon2) exist to defend *low*-entropy secrets against
brute force, which does not apply here. Only the hash is persisted; the raw key
is shown to the operator exactly once, at creation.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import FrozenSet, Optional

from argox_collector.auth.principal import Scope

# Every minted key starts with this marker so the authenticator can tell an API
# key apart from a JWT without parsing, and so leaked keys are greppable.
KEY_PREFIX = "argox_"
# Bytes of entropy in the secret portion (token_urlsafe rounds up to ~43 chars).
_SECRET_BYTES = 32
# Characters of the raw key surfaced for identification in listings. Long enough
# to disambiguate keys, short enough to never expose a usable secret.
_DISPLAY_PREFIX_LEN = 12


def generate_key() -> str:
    """Return a fresh, URL-safe API key string with the Argox prefix."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(_SECRET_BYTES)}"


def hash_key(raw_key: str) -> str:
    """Return the lowercase SHA-256 hex digest used to store/look up a key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def display_prefix(raw_key: str) -> str:
    """Return the non-secret leading slice of a key, for listings."""
    return raw_key[:_DISPLAY_PREFIX_LEN]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ApiKeyRecord:
    """A persisted API key. The raw secret is never stored, only its hash."""

    id: str
    name: str
    key_hash: str
    key_prefix: str
    scopes: FrozenSet[Scope]
    created_at: datetime
    created_by: Optional[str] = None
    revoked_at: Optional[datetime] = None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def is_active(self) -> bool:
        """Return whether the key may still authenticate requests."""
        return self.revoked_at is None


@dataclass(frozen=True)
class NewApiKey:
    """A freshly minted key: the record plus the one-time raw secret.

    The raw key lives only in this object, returned straight to the caller that
    requested creation. It is never written to storage or logged.
    """

    record: ApiKeyRecord
    raw_key: str


def mint_key(
    *,
    name: str,
    scopes: FrozenSet[Scope],
    created_by: Optional[str] = None,
) -> NewApiKey:
    """Create a new key record and its raw secret without persisting anything.

    The caller is responsible for handing :class:`NewApiKey.record` to an
    :class:`~argox_collector.auth.keystore.ApiKeyStore` and surfacing
    :attr:`NewApiKey.raw_key` to the operator exactly once.
    """
    raw_key = generate_key()
    record = ApiKeyRecord(
        id=uuid.uuid4().hex,
        name=name,
        key_hash=hash_key(raw_key),
        key_prefix=display_prefix(raw_key),
        scopes=frozenset(scopes),
        created_at=_now(),
        created_by=created_by,
    )
    return NewApiKey(record=record, raw_key=raw_key)
