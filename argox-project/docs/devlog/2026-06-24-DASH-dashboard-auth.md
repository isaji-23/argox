# [DASH] Authenticate dashboard API requests

- **Date:** 2026-06-24
- **PR:** #171  ·  **Branch:** feat/DASH-dashboard-auth
- **Status:** in-review

## What changed
- New `argox-dashboard/src/lib/auth.ts`: a credential store backed by
  `localStorage` under `argox.apikey` (mirroring the `argox.theme` /
  `argox.route` convention). Exposes `getToken` / `setToken` / `clearToken`,
  a `signalAuthRequired()` helper, and a module-level `authBus` (`EventTarget`)
  emitting `argox:token-changed` and `argox:auth-required` events.
- `argox-dashboard/src/lib/api.ts`: every request now flows through a single
  `apiFetch` wrapper. It attaches `Authorization: Bearer <token>` **only when a
  key is stored**; on `401`/`403` it calls `signalAuthRequired()` and raises an
  `APIError` with a descriptive message ("Authentication required…" /
  "Access denied: this key lacks the read scope.").
- New `argox-dashboard/src/components/ui/AuthDialog.tsx`: modal to paste,
  reveal, save, and remove the API key, with an auth-error banner when opened
  in reaction to a rejected request.
- `Header.tsx`: a key icon button (`onOpenAuth` / `hasCredential` props) opens
  the dialog and is tinted green when a credential is set.
- `App.tsx`: listens on `authBus` for `argox:auth-required` to auto-open the
  dialog, tracks `hasCredential`, and remounts the screen subtree (via a
  `reloadKey`) on credential change to force a refetch.
- `Icon.tsx`: added `key` and `eyeOff` glyphs.

## Why
Since COL-09 the Collector authenticates every query request via
`Authorization: Bearer <credential>` and `ARGOX_AUTH_ENABLED=true` is the
default. The frontend issued plain `fetch` calls with no header, so on an
authenticated deployment (e.g. the Azure Container Apps stack) every call to
`/api/v1/traces` and `/api/v1/metrics/*` returned `401` and the dashboard
showed no data, with no UI to supply a credential.

The **API-key** option from the issue was chosen over OIDC: an operator pastes
a `read`-scoped key, stored only in the browser. It satisfies the acceptance
criteria with the least surface area and reuses the existing `localStorage`
pattern. No credential is baked into the served bundle, and with no key stored
(auth disabled) requests go out unauthenticated, so behavior is unchanged.

## Notes / follow-ups
- OIDC (Microsoft Entra ID) login remains a future option; the Collector
  already accepts OIDC JWTs on the same `Bearer` header
  (`argox-project/docs/collector/auth.md`), so it could reuse `apiFetch`
  without further API changes.
- Closes #167.
