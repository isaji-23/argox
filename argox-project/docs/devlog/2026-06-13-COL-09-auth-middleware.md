# [COL-09] Auth middleware — API keys + OIDC

- **Date:** 2026-06-13
- **PR:** #135  ·  **Branch:** feat/COL-09-auth-middleware
- **Status:** in-review

## What changed

- New `argox_collector.auth` package:
  - `principal.py` — `Scope` enum (`ingest`, `policy-read`, `policy-write`,
    `read`, `admin`) and `Principal` (subject, kind, scopes); `admin` is a
    super-scope satisfying every check.
  - `keys.py` — API key minting (`argox_` prefix, 256-bit secret), SHA-256
    hashing, and the `ApiKeyRecord`/`NewApiKey` value objects. The raw key is
    surfaced once; only its hash is persisted.
  - `keystore.py` — `ApiKeyStore` over a new `api_keys` table in the index
    DuckDB (create / get-by-hash / list / revoke).
  - `oidc.py` — `OidcValidator`: verifies an IdP-issued JWT (JWKS signature,
    `iss`, `aud`, `exp`) and maps the role claim to scopes for RBAC. Accepts a
    static public key for testing instead of a network JWKS fetch.
  - `authenticator.py` + `dependencies.py` — `Authenticator.authenticate()`
    and the `require_scope` FastAPI dependency that routers gate on.
- Scope guards wired into the trace (`ingest`), policy (`policy-read`/
  `policy-write`), query (`read`), audit (`read` / `admin`) and new keys
  (`admin`) routers. Health/readiness stay public.
- `routers/keys.py` — admin-only API key CRUD; create returns the raw secret
  once, listings expose metadata only.
- `routers/audit.py` — `POST /api/v1/audit` now binds `actor` to the
  authenticated principal; `actor` was removed from the request body.
- `__main__.py` — argparse dispatch: `serve` (default) plus
  `keys create|list|revoke`, writing straight to the index DB for bootstrap.
- `settings.py` — `auth_enabled` (default True), `bootstrap_admin_key`, and
  `oidc_*` fields. Stale "auth not yet in place" bind note removed.
- `app.py` — builds the key store + authenticator, attaches them to
  `app.state`, registers the keys router, and closes a self-opened store on
  shutdown. `create_app` accepts injected `api_key_store`/`authenticator`.
- Deps: `pyjwt[crypto]`, `httpx` added to the collector runtime. Root ruff
  config: `require_scope` added to flake8-bugbear immutable-calls.
- Tests: `test_auth.py` (unauth rejection across endpoints, API key scope
  enforcement, revocation, bootstrap, HTTP key CRUD, OIDC RBAC + bad
  signature/expired/wrong-aud/iss against a self-signed RSA JWKS, actor
  binding) and `test_api_key_store.py`. Conftest defaults
  `ARGOX_AUTH_ENABLED=false` so legacy collector tests need no credentials.

## Why

Authentication was the explicit blocker on every non-local deployment and on
DASH-04. Prior tickets left "needs COL-09" markers — the `0.0.0.0` bind note in
`settings.py` and the security note in `routers/audit.py` warning that `actor`
was forgeable and the read endpoints were open. Both are resolved here: the
audit actor is now the authenticated principal (write-time authenticity that
complements the COL-08 hash chain's tamper-evidence, per AI Act Art. 12), and
the read endpoints require the `read` scope.

The two-flow split (hashed API keys for machines, OIDC JWTs for humans) and the
scope model are locked in ADR-0005.

## Notes / follow-ups

- OIDC end-to-end is validated in CI against a self-signed RSA JWKS standing in
  for the IdP; the dashboard owns the OAuth2 authorization-code flow and Entra
  ID app-role setup is documented in `docs/collector/auth.md`.
- `bootstrap_admin_key` is a break-glass credential; prefer minting a real
  admin key via the CLI and leaving it unset in steady state.
- DASH-04 (policy editor) can now build against `policy-write` RBAC.
