# [DASH-06] API key management UI in the dashboard

- **Date:** 2026-06-24
- **PR:** #173  ·  **Branch:** feat/DASH-06-key-management-ui
- **Status:** in-review

## What changed
- New **API keys** screen (`components/screens/KeysScreen.tsx`) under a "Manage"
  nav group: create, list and revoke Collector API keys from the browser.
  - Create form: name, scope toggles (`read`, `ingest`, `policy-read`,
    `policy-write`, `admin`) and an optional expiry (Never / 30d / 90d / 1y,
    sent as `expires_in` seconds).
  - One-time raw-secret panel with a copy action — the secret is shown once,
    matching the backend contract (only a hash is stored).
  - Table of existing keys (metadata only) with a confirmation-guarded per-row
    revoke.
- `lib/auth.ts`: adds a dedicated admin credential slot (`argox.adminkey` in
  `localStorage`), separate from the `read` key, with `get/set/clearAdminToken`
  and an `ADMIN_TOKEN_CHANGED_EVENT` on the existing bus.
- `lib/api.ts`: adds an `adminFetch` wrapper (admin Bearer token, `POST`/`DELETE`
  bodies, `204` → `null`) plus `listKeys`/`createKey`/`revokeKey` and the key
  types. It deliberately does **not** fire `signalAuthRequired` on `401`/`403`
  (that opens the read-key dialog); the screen handles auth failures inline via
  `APIError.status`.
- `Sidebar` / `App`: new "Manage → API keys" nav entry, `keys` route and header
  crumb.

## Why
Since COL-09 the Collector exposes admin-only key CRUD
(`POST`/`GET`/`DELETE /api/v1/keys`), and DASH (#171) added a `read`-key auth
flow to the dashboard. But minting that key still required the `argox-collector
keys` CLI (needs filesystem access to the DuckDB index — fails inside a running
container with `Permission denied`) or raw `curl` with the break-glass admin
key. On Azure the Collector ingress is internal-only, so key operations already
travel through the dashboard proxy. This adds a first-class UI and closes that
loop. Front-end only — no backend change; it wires the existing endpoints.

## Notes / follow-ups
- The admin credential is persisted in `localStorage` for convenience; this
  grants full key-management power to anyone with browser access. Prefer a
  dedicated `admin`-scoped key over the break-glass bootstrap key. A future
  ticket may move this to the OIDC admin-role flow the Collector already
  supports.
- Lint adds one `react-hooks/set-state-in-effect` on the initial fetch — the
  same rule already triggered by `TracesScreen`, `TraceDetailScreen` and
  `AuthDialog`; kept consistent with those screens.
