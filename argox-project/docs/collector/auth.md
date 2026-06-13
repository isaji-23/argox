# Collector authentication & authorization (COL-09)

The Collector authenticates every request except the health probes. Two
credential families share a single `Authorization: Bearer <credential>` header:

| Caller | Credential | Used by |
|---|---|---|
| Machine-to-machine | **API key** (`argox_…`) | SDK exporters, policy clients, ingest pipelines |
| Human | **OIDC JWT** | Dashboard, validated against the IdP |

Authorization is scope-based. A request is allowed only when the resolved
principal holds the scope its route requires.

## Scopes

| Scope | Grants |
|---|---|
| `ingest` | `POST /v1/traces` |
| `policy-read` | read policies + `/bundle` |
| `policy-write` | create/update/archive policies |
| `read` | query API (traces, metrics) + audit read/verify |
| `admin` | API key CRUD, audit append; **super-scope** — satisfies every check |

### Route → required scope

| Route | Scope |
|---|---|
| `GET /healthz`, `GET /readyz` | *(public)* |
| `POST /v1/traces` | `ingest` |
| `GET /api/v1/policies`, `/{id}`, `/{id}/v{n}`, `/bundle` | `policy-read` |
| `POST/PUT/DELETE /api/v1/policies` | `policy-write` |
| `GET /api/v1/traces`, `/api/v1/metrics/*` | `read` |
| `GET /api/v1/audit`, `/api/v1/audit/verify` | `read` |
| `POST /api/v1/audit` | `admin` (actor bound to the principal) |
| `* /api/v1/keys` | `admin` |

Unauthenticated requests get `401` (with `WWW-Authenticate: Bearer`); an
authenticated principal lacking the scope gets `403`.

## API keys

Keys are minted as `argox_<base64url-secret>` carrying 256 bits of entropy.
**Only the SHA-256 hash is stored** (in the `api_keys` table of the index DB),
alongside a short non-secret display prefix and the granted scopes. The raw key
is shown **once**, at creation, and is never recoverable afterwards.

> Why SHA-256 and not bcrypt/argon2? Those slow, salted KDFs defend
> *low-entropy* secrets (passwords) against brute force. An API key is
> high-entropy random data, so a single preimage-resistant hash is both
> sufficient and constant-cost on the auth hot path.

### CLI (`argox-collector keys …`)

The `keys` subcommands write straight to the index DB, so the **first** key can
be created offline before the (admin-only) HTTP CRUD is reachable.

```bash
# Mint an ingest key for the SDK
argox-collector keys create --name "prod-sdk" --scope ingest

# Multiple scopes: repeat --scope
argox-collector keys create --name "dashboard-svc" --scope read --scope policy-read

# List (metadata only — never the secret)
argox-collector keys list

# Revoke by id
argox-collector keys revoke <key-id>
```

`keys create` prints the raw key once:

```
Created API key 1f3c… (prod-sdk)
  scopes: ingest
  key (shown once, store it now):
  argox_xK2…
```

### HTTP CRUD (admin only)

```bash
# Create
curl -X POST https://collector/api/v1/keys \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"prod-sdk","scopes":["ingest"]}'
# -> 201 { "id": "...", "key": "argox_...", "scopes": ["ingest"], ... }

# List  -> GET  /api/v1/keys   (never returns the secret)
# Revoke -> DELETE /api/v1/keys/{id}  (204; 404 if unknown/already revoked)
```

Revocation is immediate: the next request with a revoked key gets `401`.

### Using a key (SDK side)

Send the raw key as a bearer token:

```
Authorization: Bearer argox_xK2…
```

## OIDC (dashboard users)

The dashboard runs the standard OAuth2 **authorization-code flow** against the
IdP and forwards the resulting JWT to the Collector as a bearer token. The
Collector verifies the token — signature against the IdP's JWKS, plus `iss`,
`aud` and `exp` — then maps the role claim to scopes (RBAC).

### Role → scope mapping

- Any valid token → `read` + `policy-read` (baseline dashboard access).
- Role equals `ARGOX_OIDC_POLICY_WRITE_ROLE` → add `policy-write`.
- Role equals `ARGOX_OIDC_ADMIN_ROLE` → add `admin`.

### Configuration

OIDC is enabled only when issuer, audience and JWKS URI are all set.

| Setting (env: `ARGOX_…`) | Meaning |
|---|---|
| `OIDC_ISSUER` | Expected `iss` claim |
| `OIDC_AUDIENCE` | Expected `aud` claim (your app/client id) |
| `OIDC_JWKS_URI` | IdP signing-key endpoint |
| `OIDC_ROLE_CLAIM` | Claim holding roles (default `roles`) |
| `OIDC_POLICY_WRITE_ROLE` | Role granting `policy-write` |
| `OIDC_ADMIN_ROLE` | Role granting `admin` |

#### Microsoft Entra ID (default target)

For tenant `<tenant-id>` and an app registration with Application ID
`<client-id>`:

```bash
ARGOX_OIDC_ISSUER="https://login.microsoftonline.com/<tenant-id>/v2.0"
ARGOX_OIDC_AUDIENCE="<client-id>"
ARGOX_OIDC_JWKS_URI="https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys"
ARGOX_OIDC_ROLE_CLAIM="roles"
ARGOX_OIDC_POLICY_WRITE_ROLE="Argox.PolicyEditor"
ARGOX_OIDC_ADMIN_ROLE="Argox.Admin"
```

Define **App roles** (`Argox.PolicyEditor`, `Argox.Admin`) on the app
registration and assign them to users/groups; Entra emits them in the `roles`
claim. Any generic OIDC provider works the same way — point the three
issuer/audience/JWKS settings at it.

## Bootstrap

`ARGOX_BOOTSTRAP_ADMIN_KEY` (optional) is a break-glass admin credential
accepted without a DB lookup. It exists so the first real API key can be minted
over HTTP and so deployments can inject an admin credential declaratively.
Prefer minting a real admin key with the CLI and leaving this unset in
steady state; rotate it if used.

## Disabling auth (development/tests only)

`ARGOX_AUTH_ENABLED=false` turns the gate off — every request resolves to an
all-scopes anonymous principal. **Never** set this for a non-local deployment.
The test suite sets it for the legacy collector tests; the dedicated auth tests
re-enable it.

## Security notes

- **Actor binding.** `POST /api/v1/audit` records the *authenticated* principal
  as the entry `actor`; the client cannot supply it. This gives the audit log
  write-time authenticity, complementing the COL-08 hash chain's tamper-evidence
  (AI Act Art. 12 non-repudiation).
- **No secret leakage.** Key listings and logs expose only ids, names, scopes
  and the display prefix — never the hash or the raw key.
- **Health probes stay public** so orchestrators can scrape liveness/readiness
  without credentials; they disclose no sensitive data.
- **Transport.** Bearer credentials require TLS in any non-local deployment.
