"""End-to-end auth tests for the Collector (COL-09).

Exercises the acceptance criteria of issue #94 against a live app with
``auth_enabled=True``:

- Every endpoint rejects unauthenticated requests except ``/healthz``/``/readyz``.
- API keys authenticate and their scopes are enforced (401 vs 403).
- Revoked keys stop working; a bootstrap admin key works.
- Admin-only key CRUD over HTTP, with the raw secret returned once.
- OIDC JWTs validate against a (self-signed) IdP, role claims drive RBAC, and
  bad-signature / expired / wrong-audience tokens are rejected.
- The audit ``actor`` is bound to the authenticated principal, not the body.

The OIDC IdP is simulated with a locally generated RSA keypair: tokens are
signed with the private key and the validator verifies against the public key,
which is exactly what JWKS does end-to-end without a network round-trip.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from argox_collector.app import create_app
from argox_collector.auth import (
    ApiKeyStore,
    Authenticator,
    OidcValidator,
    hash_key,
    mint_key,
    parse_scopes,
)
from argox_collector.settings import CollectorSettings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

ISSUER = "https://idp.example.com/"
AUDIENCE = "argox-collector"
POLICY_WRITE_ROLE = "PolicyEditor"
ADMIN_ROLE = "Admin"
BOOTSTRAP_KEY = "argox_bootstrap-secret-value"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_jwt(
    key: rsa.RSAPrivateKey,
    *,
    sub: str = "user-1",
    roles: list[str] | None = None,
    audience: str = AUDIENCE,
    issuer: str = ISSUER,
    expires_in: int = 300,
    name: str = "Ada Lovelace",
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "name": name,
    }
    if roles is not None:
        claims["roles"] = roles
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def store(tmp_path) -> ApiKeyStore:
    s = ApiKeyStore(tmp_path / "auth.duckdb")
    yield s
    s.close()


@pytest.fixture
def keys(store: ApiKeyStore) -> dict[str, str]:
    """Mint one key per scope and return the raw secrets by scope name."""
    raw: dict[str, str] = {}
    for scope in ("ingest", "policy-read", "policy-write", "read", "admin"):
        new_key = mint_key(name=f"{scope}-key", scopes=parse_scopes([scope]))
        store.create(new_key.record)
        raw[scope] = new_key.raw_key
    return raw


@pytest.fixture
def client(tmp_path, store, rsa_key) -> TestClient:
    settings = CollectorSettings(
        auth_enabled=True,
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
    )
    oidc = OidcValidator(
        issuer=ISSUER,
        audience=AUDIENCE,
        public_key=rsa_key.public_key(),
        policy_write_role=POLICY_WRITE_ROLE,
        admin_role=ADMIN_ROLE,
    )
    authenticator = Authenticator(
        enabled=True,
        key_store=store,
        oidc=oidc,
        bootstrap_admin_key=BOOTSTRAP_KEY,
    )
    app = create_app(settings, api_key_store=store, authenticator=authenticator)
    return TestClient(app)


# -- public endpoints ------------------------------------------------------


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_health_endpoints_are_public(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


# -- unauthenticated rejection ---------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/v1/traces"),
        ("get", "/api/v1/policies"),
        ("get", "/api/v1/policies/bundle"),
        ("post", "/api/v1/policies"),
        ("get", "/api/v1/traces"),
        ("get", "/api/v1/metrics/cost"),
        ("get", "/api/v1/audit"),
        ("get", "/api/v1/audit/verify"),
        ("post", "/api/v1/audit"),
        ("get", "/api/v1/keys"),
        ("post", "/api/v1/keys"),
    ],
)
def test_endpoints_reject_unauthenticated(
    client: TestClient, method: str, path: str
) -> None:
    resp = getattr(client, method)(path)
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_malformed_authorization_header_is_401(client: TestClient) -> None:
    resp = client.get("/api/v1/policies", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401


def test_unknown_api_key_is_401(client: TestClient) -> None:
    resp = client.get("/api/v1/policies", headers=_bearer("argox_not-real"))
    assert resp.status_code == 401


# -- API key happy path + scope enforcement --------------------------------


def test_api_key_grants_its_scope(client: TestClient, keys) -> None:
    resp = client.get("/api/v1/policies", headers=_bearer(keys["policy-read"]))
    assert resp.status_code == 200


def test_api_key_missing_scope_is_403(client: TestClient, keys) -> None:
    # A read key cannot write policies.
    resp = client.post(
        "/api/v1/policies",
        headers=_bearer(keys["read"]),
        json={"id": "p1", "status": "draft", "rules": []},
    )
    assert resp.status_code == 403


def test_ingest_scope_passes_auth_gate(client: TestClient, keys) -> None:
    # No content-type -> handler returns 415, which proves auth was satisfied
    # (an unauthorised request would have been 401/403 before reaching it).
    resp = client.post("/v1/traces", headers=_bearer(keys["ingest"]))
    assert resp.status_code == 415


def test_ingest_key_cannot_read_policies(client: TestClient, keys) -> None:
    resp = client.get("/api/v1/policies", headers=_bearer(keys["ingest"]))
    assert resp.status_code == 403


def test_admin_scope_satisfies_every_check(client: TestClient, keys) -> None:
    # Admin is a super-scope: it can read policies despite lacking policy-read.
    resp = client.get("/api/v1/policies", headers=_bearer(keys["admin"]))
    assert resp.status_code == 200


# -- revocation ------------------------------------------------------------


def test_revoked_key_is_rejected(client: TestClient, store, keys) -> None:
    # Revoke the policy-read key via its stored record.
    record = store.get_by_hash(hash_key(keys["policy-read"]))
    assert store.revoke(record.id) is True
    resp = client.get("/api/v1/policies", headers=_bearer(keys["policy-read"]))
    assert resp.status_code == 401


# -- bootstrap key ---------------------------------------------------------


def test_bootstrap_key_acts_as_admin(client: TestClient) -> None:
    resp = client.get("/api/v1/keys", headers=_bearer(BOOTSTRAP_KEY))
    assert resp.status_code == 200


# -- admin key CRUD over HTTP ----------------------------------------------


def test_admin_can_create_list_and_revoke_keys(client: TestClient, keys) -> None:
    admin = _bearer(keys["admin"])
    created = client.post(
        "/api/v1/keys",
        headers=admin,
        json={"name": "new-ingest", "scopes": ["ingest"]},
    )
    assert created.status_code == 201
    body = created.json()
    # The raw secret is returned exactly once and is usable immediately.
    assert body["key"].startswith("argox_")
    assert body["scopes"] == ["ingest"]
    new_raw = body["key"]
    key_id = body["id"]

    ingest_resp = client.post("/v1/traces", headers=_bearer(new_raw))
    assert ingest_resp.status_code == 415  # authorised, just no body

    listed = client.get("/api/v1/keys", headers=admin).json()
    assert any(k["id"] == key_id for k in listed["keys"])
    # Listing never leaks the secret.
    assert all("key" not in k for k in listed["keys"])

    revoked = client.delete(f"/api/v1/keys/{key_id}", headers=admin)
    assert revoked.status_code == 204
    assert client.post("/v1/traces", headers=_bearer(new_raw)).status_code == 401


def test_non_admin_cannot_manage_keys(client: TestClient, keys) -> None:
    resp = client.get("/api/v1/keys", headers=_bearer(keys["read"]))
    assert resp.status_code == 403


def test_create_key_rejects_unknown_scope(client: TestClient, keys) -> None:
    resp = client.post(
        "/api/v1/keys",
        headers=_bearer(keys["admin"]),
        json={"name": "bad", "scopes": ["not-a-scope"]},
    )
    assert resp.status_code == 422


# -- OIDC ------------------------------------------------------------------


def test_oidc_token_grants_baseline_read(client: TestClient, rsa_key) -> None:
    token = _make_jwt(rsa_key, roles=[])
    # Baseline user: read + policy-read, no write.
    assert client.get("/api/v1/traces", headers=_bearer(token)).status_code == 200
    assert (
        client.get("/api/v1/policies", headers=_bearer(token)).status_code == 200
    )
    write = client.post(
        "/api/v1/policies",
        headers=_bearer(token),
        json={"id": "p1", "status": "draft", "rules": []},
    )
    assert write.status_code == 403


def test_oidc_policy_write_role_grants_write(client: TestClient, rsa_key) -> None:
    token = _make_jwt(rsa_key, roles=[POLICY_WRITE_ROLE])
    resp = client.post(
        "/api/v1/policies",
        headers=_bearer(token),
        json={"id": "p1", "status": "draft", "rules": []},
    )
    assert resp.status_code == 201


def test_oidc_admin_role_grants_admin(client: TestClient, rsa_key) -> None:
    token = _make_jwt(rsa_key, roles=[ADMIN_ROLE])
    resp = client.get("/api/v1/keys", headers=_bearer(token))
    assert resp.status_code == 200


def test_oidc_rejects_bad_signature(client: TestClient) -> None:
    # Signed with a different key the validator does not trust.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_jwt(other, roles=[])
    assert client.get("/api/v1/traces", headers=_bearer(token)).status_code == 401


def test_oidc_rejects_expired_token(client: TestClient, rsa_key) -> None:
    token = _make_jwt(rsa_key, roles=[], expires_in=-10)
    assert client.get("/api/v1/traces", headers=_bearer(token)).status_code == 401


def test_oidc_rejects_wrong_audience(client: TestClient, rsa_key) -> None:
    token = _make_jwt(rsa_key, roles=[], audience="someone-else")
    assert client.get("/api/v1/traces", headers=_bearer(token)).status_code == 401


def test_oidc_rejects_wrong_issuer(client: TestClient, rsa_key) -> None:
    token = _make_jwt(rsa_key, roles=[], issuer="https://evil.example.com/")
    assert client.get("/api/v1/traces", headers=_bearer(token)).status_code == 401


# -- audit actor binding ---------------------------------------------------


def test_audit_actor_is_bound_to_principal(client: TestClient, keys, store) -> None:
    admin = _bearer(keys["admin"])
    # The body has no actor field; the entry records the authenticated subject.
    resp = client.post(
        "/api/v1/audit",
        headers=admin,
        json={"action": "policy.update", "target": "p1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # admin key's principal subject is the key's id.
    admin_record = store.get_by_hash(hash_key(keys["admin"]))
    assert body["actor"] == admin_record.id


def test_audit_read_requires_read_scope(client: TestClient, keys) -> None:
    # ingest key lacks read; admin (super-scope) can list.
    assert (
        client.get("/api/v1/audit", headers=_bearer(keys["ingest"])).status_code
        == 403
    )
    assert (
        client.get("/api/v1/audit", headers=_bearer(keys["admin"])).status_code
        == 200
    )
