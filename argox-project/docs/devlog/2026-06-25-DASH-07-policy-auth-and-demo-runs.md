# [DASH-07] Authenticate dashboard policy requests; post demo run records

- **Date:** 2026-06-25
- **PR:** #186  ·  **Branch:** fix/dashboard-policy-auth-and-demo-runs
- **Status:** in-review

## What changed
- `argox-dashboard/src/lib/api.ts`: added a `policyFetch` wrapper and routed all
  seven policy methods (`listPolicies`, `getPolicy`, `getPolicyVersion`,
  `getPolicyVersionYaml`, `createPolicy`, `updatePolicy`, `validatePolicy`)
  through it. The wrapper attaches the stored read key
  (`Authorization: Bearer <token>`), supports a request body and a custom
  `Accept` (the YAML view), returns the raw `Response` for `.json()`/`.text()`,
  and mirrors `apiFetch`'s `401`/`403` handling (`signalAuthRequired` + typed
  `APIError`). Previously these calls used a bare `fetch()` with no auth header.
- `deploy/azure/demo_agent.py`: wired `HttpRunExporter` into
  `@argox.monitor(exporters=[...])` via a `_build_run_exporter()` helper that
  derives the Collector base URL from `ARGOX_COLLECTOR_ENDPOINT` (strips the
  `/v1/traces` suffix), reuses `ARGOX_COLLECTOR_API_KEY`, and sets
  `durable=True` so the run commits before the short-lived script exits.
- `deploy/azure/demo.sh`: mint the demo key with `policy-read` in addition to
  `read` and `ingest`, so the one key drives the agent (ingest), trace/run reads
  (read), and the Policies screen (policy-read).

## Why
Two failures surfaced once the deployed Collector had auth enabled:
- **Policies 401.** The policy methods were the only API client calls that sent
  no `Authorization` header, so `GET /api/v1/policies` returned 401 (it worked
  only with auth disabled). The scope/credential path was fine — traces loaded —
  the request simply carried no key.
- **Empty Run Record.** The demo agent shipped only OTLP spans, never the run
  summary, so `/v1/runs` had nothing to serve. `HttpRunExporter` is the run-side
  exporter (`EXP-09`) and must be registered on the manager to post it.
- `policy-read` is a distinct scope from `read` (Scope enum); the demo key
  lacked it, so even an authenticated key could not read the Policies screen.

## Notes / follow-ups
- Depends on #185 (EXP-10) for the posted run to resolve by trace; without it the
  run stores unlinked and `by-trace` still 404s.
- The minted demo key is not printed by `demo.sh`; for the dashboard UI, mint a
  dedicated key (`read`,`policy-read`) and paste it into the AuthDialog.
