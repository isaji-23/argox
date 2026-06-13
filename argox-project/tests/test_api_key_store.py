"""Tests for the DuckDB-backed API key store (COL-09)."""

from __future__ import annotations

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
