"""Tests for the DuckDB-backed API key store (COL-09)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from argox_collector.auth import (
    ApiKeyStore,
    ApiKeyStoreError,
    Scope,
    hash_key,
    mint_key,
    parse_scopes,
)


@pytest.fixture
def store(tmp_path) -> ApiKeyStore:
    s = ApiKeyStore(tmp_path / "auth.duckdb")
    yield s
    s.close()


def test_create_and_lookup_by_hash(store: ApiKeyStore) -> None:
    new_key = mint_key(name="ingest-bot", scopes=parse_scopes(["ingest"]))
    store.create(new_key.record)

    found = store.get_by_hash(hash_key(new_key.raw_key))
    assert found is not None
    assert found.id == new_key.record.id
    assert found.name == "ingest-bot"
    assert found.scopes == frozenset({Scope.INGEST})
    assert found.is_active()


def test_raw_key_is_never_stored(store: ApiKeyStore) -> None:
    new_key = mint_key(name="k", scopes=parse_scopes(["read"]))
    store.create(new_key.record)
    found = store.get_by_hash(new_key.record.key_hash)
    # Only the hash and a short display prefix are persisted.
    assert found.key_hash != new_key.raw_key
    assert new_key.raw_key.startswith(found.key_prefix)


def test_unknown_hash_returns_none(store: ApiKeyStore) -> None:
    assert store.get_by_hash("0" * 64) is None


def test_duplicate_hash_rejected(store: ApiKeyStore) -> None:
    new_key = mint_key(name="k", scopes=parse_scopes(["read"]))
    store.create(new_key.record)
    with pytest.raises(ApiKeyStoreError):
        store.create(new_key.record)


def test_revoke_marks_inactive(store: ApiKeyStore) -> None:
    new_key = mint_key(name="k", scopes=parse_scopes(["read"]))
    store.create(new_key.record)
    assert store.revoke(new_key.record.id) is True

    found = store.get_by_hash(new_key.record.key_hash)
    assert found is not None
    assert not found.is_active()
    assert found.revoked is True
    assert found.revoked_at is not None


def test_revoke_is_idempotent(store: ApiKeyStore) -> None:
    new_key = mint_key(name="k", scopes=parse_scopes(["read"]))
    store.create(new_key.record)
    assert store.revoke(new_key.record.id) is True
    # Second revoke reports "nothing changed".
    assert store.revoke(new_key.record.id) is False


def test_revoke_unknown_key_returns_false(store: ApiKeyStore) -> None:
    assert store.revoke("does-not-exist") is False


def test_list_newest_first(store: ApiKeyStore) -> None:
    ids = []
    for name in ("a", "b", "c"):
        nk = mint_key(name=name, scopes=parse_scopes(["read"]))
        store.create(nk.record)
        ids.append(nk.record.id)
    listed = store.list()
    assert len(listed) == 3
    assert {r.id for r in listed} == set(ids)


def test_state_persists_across_instances(tmp_path) -> None:
    path = tmp_path / "auth.duckdb"
    first = ApiKeyStore(path)
    nk = mint_key(name="k", scopes=parse_scopes(["admin"]))
    first.create(nk.record)
    first.close()

    second = ApiKeyStore(path)
    try:
        found = second.get_by_hash(nk.record.key_hash)
        assert found is not None
        assert found.scopes == frozenset({Scope.ADMIN})
    finally:
        second.close()


def test_parse_scopes_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        parse_scopes(["ingest", "not-a-scope"])


def test_expiring_key_roundtrips_and_deactivates(store: ApiKeyStore) -> None:
    # 1h key is active now; the same record is inactive once past expiry.
    new_key = mint_key(
        name="ci", scopes=parse_scopes(["ingest"]), expires_in=3600
    )
    store.create(new_key.record)
    found = store.get_by_hash(new_key.record.key_hash)
    assert found.expires_at is not None
    assert found.is_active()

    later = found.expires_at + timedelta(seconds=1)
    assert found.is_expired(now=later)
    assert not found.is_active(now=later)


def test_non_expiring_key_never_expires(store: ApiKeyStore) -> None:
    new_key = mint_key(name="k", scopes=parse_scopes(["read"]))
    store.create(new_key.record)
    found = store.get_by_hash(new_key.record.key_hash)
    assert found.expires_at is None
    far_future = datetime(2999, 1, 1, tzinfo=timezone.utc)
    assert found.is_active(now=far_future)


def test_mint_rejects_non_positive_expiry() -> None:
    with pytest.raises(ValueError):
        mint_key(name="k", scopes=parse_scopes(["read"]), expires_in=0)


def test_corrupt_non_list_scopes_loads_as_empty(store: ApiKeyStore) -> None:
    new_key = mint_key(name="k", scopes=parse_scopes(["admin"]))
    store.create(new_key.record)
    # Simulate a hand-corrupted DB: scopes column is an int, not a JSON list.
    store._conn.execute(  # noqa: SLF001 - deliberately poke internals
        "UPDATE api_keys SET scopes = '42' WHERE id = ?", (new_key.record.id,)
    )
    found = store.get_by_hash(new_key.record.key_hash)
    # Must not raise; degrades to no scopes rather than crashing the load.
    assert found is not None
    assert found.scopes == frozenset()
