# ADR-0005: Collector auth — hashed API keys for machines, OIDC JWTs for humans

- **Status:** accepted
- **Date:** 2026-06-13
- **Ticket:** COL-09

## Context

The Collector exposed ingest, policy, query and audit endpoints with no
authentication. Earlier tickets shipped with explicit "needs COL-09" markers:
the service binds `0.0.0.0`, and the audit endpoint trusted a client-supplied
`actor`, leaving entries forgeable and the audit trail readable by anyone. Auth
blocked every non-local deployment and DASH-04 (the policy editor).

Two caller classes have genuinely different needs. SDK clients are long-lived
machines that cannot run an interactive login and want a stable, revocable
credential. Dashboard users are humans who already authenticate to a corporate
IdP (Microsoft Entra ID), where role assignment lives.

## Decision

Authenticate every endpoint except `/healthz` and `/readyz` via a single
`Authorization: Bearer <credential>` header, with two credential families and a
shared scope model.

**Scopes** (`argox_collector.auth.principal.Scope`): `ingest`, `policy-read`,
`policy-write`, `read`, `admin`. `admin` is a super-scope — holding it satisfies
every `Principal.has_scope` check. Routes declare their requirement with the
`require_scope(scope)` FastAPI dependency; the resolved `Principal` (subject,
kind, scopes) is what handlers see.

**API keys (machine-to-machine).** Minted as `argox_<256-bit base64url secret>`.
Only the SHA-256 hash is stored, in an `api_keys` table in the index DuckDB,
with the granted scopes and a non-secret display prefix. The raw key is returned
exactly once. Plain SHA-256 (not bcrypt/argon2) is deliberate: the secret is
high-entropy random data, so a single preimage-resistant, constant-cost hash is
sufficient on the auth hot path. Keys are revoked by setting `revoked_at`.

**OIDC JWTs (human).** The dashboard runs the OAuth2 authorization-code flow
against the IdP and forwards the JWT. The Collector's `OidcValidator` verifies
the signature against the IdP JWKS plus `iss`, `aud` and `exp`, then maps the
configurable role claim to scopes: any valid token gets `read` + `policy-read`;
the configured policy-write role adds `policy-write`; the admin role adds
`admin`.

**Bootstrap.** An optional `bootstrap_admin_key` is accepted as an admin
credential without a DB lookup, and the `argox-collector keys` CLI writes
straight to the index DB — either path solves the chicken-and-egg of the
admin-only key CRUD.

**Actor binding.** `POST /api/v1/audit` records the authenticated principal's
subject as `actor`; the field was removed from the request body. This gives the
audit log write-time authenticity that the COL-08 hash chain (tamper-evidence
only) cannot provide.

`auth_enabled` (default True) is the single switch; when off, every request
resolves to an all-scopes anonymous principal.

## Triggers for the next refactor

- A third credential class (e.g. mTLS service identities) — generalise
  `Authenticator._resolve` beyond the API-key/JWT dispatch.
- Per-key rate limiting or last-used tracking — currently omitted to keep
  authentication a read-only hot path with no write on each request.
- Multiple OIDC providers at once — `OidcValidator` is single-issuer today.
- Finer RBAC than role→scope (e.g. per-policy ownership) — would move
  authorization out of the flat scope set.

## What stays out of scope

- The dashboard's OAuth2 code flow and token storage (client-side; the
  Collector only validates bearer JWTs).
- Token issuance/refresh — the Collector never mints JWTs, only verifies them.
- Key encryption at rest beyond hashing, and HSM-backed secrets.
- Transport security (TLS termination) — an infrastructure concern.
