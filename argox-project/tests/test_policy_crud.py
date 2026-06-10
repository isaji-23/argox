"""Tests for the COL-05 policy CRUD API and the merged /bundle endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from argox.policies.parser import PolicyParser
from argox_collector.app import create_app
from argox_collector.settings import CollectorSettings
from argox_collector.storage import LocalStorageBackend
from fastapi.testclient import TestClient

BASE = "/api/v1/policies"


def _rule(rule_id: str = "rule_1", threshold: str = "secret") -> dict:
    return {
        "id": rule_id,
        "trigger": "on_input",
        "condition": {
            "metric": "prompt",
            "operator": "contains",
            "threshold": threshold,
        },
        "action": "block",
    }


def _policy(policy_id: str, status: str = "active", rules: list | None = None) -> dict:
    return {
        "id": policy_id,
        "status": status,
        "rules": rules if rules is not None else [_rule()],
        "created_by": "tests",
    }


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(root=tmp_path / "blobs")


@pytest.fixture
def client(storage: LocalStorageBackend, tmp_path: Path) -> TestClient:
    settings = CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
    )
    return TestClient(create_app(settings, storage=storage))


# ---------------------------------------------------------------------------
# Create + read
# ---------------------------------------------------------------------------


def test_create_policy_returns_v1_document(client: TestClient) -> None:
    response = client.post(BASE, json=_policy("pol_a"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "pol_a"
    assert body["version"] == 1
    assert body["status"] == "active"
    assert body["content_hash"]
    assert body["rules"][0]["id"] == "rule_1"


def test_create_duplicate_policy_conflicts(client: TestClient) -> None:
    assert client.post(BASE, json=_policy("pol_a")).status_code == 201
    assert client.post(BASE, json=_policy("pol_a")).status_code == 409


def test_create_rejects_invalid_policy_id(client: TestClient) -> None:
    response = client.post(BASE, json=_policy("bad/../id"))
    assert response.status_code == 422


def test_get_active_policy_roundtrip(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    response = client.get(f"{BASE}/pol_a")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["rules"][0]["condition"]["threshold"] == "secret"


def test_get_active_policy_404_for_unknown_id(client: TestClient) -> None:
    assert client.get(f"{BASE}/nope").status_code == 404


def test_draft_policy_has_no_active_version(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_d", status="draft"))
    assert client.get(f"{BASE}/pol_d").status_code == 404
    # The specific version is still addressable.
    assert client.get(f"{BASE}/pol_d/v1").status_code == 200


def test_get_specific_version(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    response = client.get(f"{BASE}/pol_a/v1")
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert client.get(f"{BASE}/pol_a/v2").status_code == 404
    assert client.get(f"{BASE}/missing/v1").status_code == 404


# ---------------------------------------------------------------------------
# Update (new version)
# ---------------------------------------------------------------------------


def test_update_creates_next_version(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    response = client.put(
        f"{BASE}/pol_a",
        json={
            "status": "active",
            "rules": [_rule(threshold="token")],
            "created_by": "tests",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2

    # The committed blob carries the version number too — every later GET
    # must return version 2, not a null placeholder.
    active = client.get(f"{BASE}/pol_a").json()
    assert active["version"] == 2
    assert active["rules"][0]["condition"]["threshold"] == "token"

    # History stays addressable.
    assert client.get(f"{BASE}/pol_a/v1").json()["version"] == 1


def test_update_to_draft_clears_active_version(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    response = client.put(
        f"{BASE}/pol_a", json={"status": "draft", "rules": [_rule()]}
    )
    assert response.status_code == 200
    # No active version anymore: serving the old active one would be stale.
    assert client.get(f"{BASE}/pol_a").status_code == 404


def test_update_unknown_policy_404(client: TestClient) -> None:
    response = client.put(
        f"{BASE}/nope", json={"status": "active", "rules": []}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Archive (DELETE)
# ---------------------------------------------------------------------------


def test_archive_creates_archived_version_and_hides_policy(
    client: TestClient,
) -> None:
    client.post(BASE, json=_policy("pol_a"))
    response = client.delete(f"{BASE}/pol_a")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "archived"
    assert body["version"] == 2
    # Rules are preserved in the archived version.
    assert body["rules"][0]["id"] == "rule_1"

    # No longer served as active, but history remains.
    assert client.get(f"{BASE}/pol_a").status_code == 404
    assert client.get(f"{BASE}/pol_a/v1").status_code == 200
    assert client.get(f"{BASE}/pol_a/v2").json()["status"] == "archived"


def test_archive_is_idempotent(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    first = client.delete(f"{BASE}/pol_a").json()
    second = client.delete(f"{BASE}/pol_a")
    assert second.status_code == 200
    # Same head document, no extra version committed.
    assert second.json()["version"] == first["version"]


def test_archive_unknown_policy_404(client: TestClient) -> None:
    assert client.delete(f"{BASE}/nope").status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_policies_sorted_and_paginated(client: TestClient) -> None:
    for policy_id in ("pol_c", "pol_a", "pol_b"):
        client.post(BASE, json=_policy(policy_id))

    response = client.get(BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [p["id"] for p in body["policies"]] == ["pol_a", "pol_b", "pol_c"]

    page = client.get(BASE, params={"skip": 1, "limit": 1}).json()
    assert [p["id"] for p in page["policies"]] == ["pol_b"]
    assert page["total"] == 3


def test_list_validates_pagination_params(client: TestClient) -> None:
    assert client.get(BASE, params={"skip": -1}).status_code == 422
    assert client.get(BASE, params={"limit": 0}).status_code == 422
    assert client.get(BASE, params={"limit": 1000}).status_code == 422


def test_list_reflects_status_transitions(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    client.delete(f"{BASE}/pol_a")
    summary = client.get(BASE).json()["policies"][0]
    assert summary["status"] == "archived"
    assert summary["active_version"] is None
    assert summary["latest_version"] == 2


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


def test_bundle_empty_when_no_policies(client: TestClient) -> None:
    response = client.get(f"{BASE}/bundle")
    assert response.status_code == 200
    document = yaml.safe_load(response.text)
    assert document["id"] == "bundle_active"
    assert document["rules"] == []
    assert response.headers["ETag"]


def test_bundle_merges_only_active_policies(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_b", rules=[_rule("rule_b")]))
    client.post(BASE, json=_policy("pol_a", rules=[_rule("rule_a")]))
    client.post(BASE, json=_policy("pol_draft", status="draft", rules=[_rule("rule_d")]))
    client.post(BASE, json=_policy("pol_gone", rules=[_rule("rule_g")]))
    client.delete(f"{BASE}/pol_gone")

    response = client.get(f"{BASE}/bundle")
    assert response.status_code == 200
    document = yaml.safe_load(response.text)
    # Sorted by policy id, draft and archived excluded.
    assert [rule["id"] for rule in document["rules"]] == ["rule_a", "rule_b"]


def test_bundle_is_parseable_by_sdk_parser(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    response = client.get(f"{BASE}/bundle")
    document = PolicyParser().parse_yaml(response.text)
    assert document.id == "bundle_active"
    assert document.status == "active"
    assert document.rules[0].action == "block"


def test_bundle_etag_stable_and_304(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))

    first = client.get(f"{BASE}/bundle")
    second = client.get(f"{BASE}/bundle")
    etag = first.headers["ETag"]
    # GET has no side effects, so the ETag is stable between requests.
    assert second.headers["ETag"] == etag

    cached = client.get(f"{BASE}/bundle", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.headers["ETag"] == etag

    weak = client.get(f"{BASE}/bundle", headers={"If-None-Match": f"W/{etag}"})
    assert weak.status_code == 304


def test_bundle_etag_changes_when_rules_change(client: TestClient) -> None:
    client.post(BASE, json=_policy("pol_a"))
    etag = client.get(f"{BASE}/bundle").headers["ETag"]

    client.put(
        f"{BASE}/pol_a",
        json={"status": "active", "rules": [_rule(threshold="token")]},
    )
    refreshed = client.get(f"{BASE}/bundle", headers={"If-None-Match": etag})
    assert refreshed.status_code == 200
    assert refreshed.headers["ETag"] != etag


def test_bundle_skips_policy_with_dangling_pointer(
    client: TestClient, storage: LocalStorageBackend
) -> None:
    client.post(BASE, json=_policy("pol_a", rules=[_rule("rule_a")]))
    client.post(BASE, json=_policy("pol_b", rules=[_rule("rule_b")]))

    # Simulate a committed manifest pointer whose blob write was lost.
    hash_a = client.get(f"{BASE}/pol_a").json()["content_hash"]
    storage.delete(f"policies/pol_a/{hash_a}.yaml")

    response = client.get(f"{BASE}/bundle")
    assert response.status_code == 200
    document = yaml.safe_load(response.text)
    # The broken policy is skipped; enforcement keeps working for the rest.
    assert [rule["id"] for rule in document["rules"]] == ["rule_b"]


# ---------------------------------------------------------------------------
# Storage-level consistency
# ---------------------------------------------------------------------------


def test_version_blobs_are_content_addressed(
    client: TestClient, storage: LocalStorageBackend
) -> None:
    created = client.post(BASE, json=_policy("pol_a")).json()
    key = f"policies/pol_a/{created['content_hash']}.yaml"
    stored = yaml.safe_load(storage.get(key).data.decode("utf-8"))
    assert stored["version"] == 1
    assert stored["id"] == "pol_a"


def test_lost_cas_blobs_are_not_reachable_via_api(
    client: TestClient, storage: LocalStorageBackend
) -> None:
    client.post(BASE, json=_policy("pol_a"))
    # An orphan blob (e.g. from a lost CAS race) sits next to real versions.
    storage.put("policies/pol_a/deadbeef.yaml", b"id: rogue\nversion: 99\n")
    # Version lookups go through the manifest only.
    assert client.get(f"{BASE}/pol_a/v99").status_code == 404
