# [DEPLOY-02] Local multi-agent demo with RemotePolicyClient

- **Date:** 2026-06-27
- **PR:** (pending)  ·  **Branch:** dev
- **Status:** in-review

## What changed
- New `deploy/local/` demo that drives several `@argox.monitor`-instrumented
  agents through the SDK against a real dashboard, with a front to pick the
  agent and inspect per-run data (tokens, latency, success, policy decision,
  tools called/blocked, trace link). Files:
  - `server.py` — FastAPI backend: four agents (weather, travel-planner,
    math-tutor, research-bot), one shared `RemotePolicyClient` polling
    `/api/v1/policies/bundle`, `OTLPSpanExporter` + `HttpRunExporter`, and an
    in-process `CaptureExporter` (via `ContextVar`) that returns the run's
    `AgentRunMetrics.to_dict()` to the caller of `POST /api/run`.
  - `index.html` — single-page front styled with the dashboard's design tokens;
    agent selector, example prompts, result cards, policy badge (passed / alert
    / blocked), trace link into the dashboard.
  - `run.sh` — two modes: `local` (default) brings up the Docker stack
    (`deploy/docker/compose.yaml --profile local`); `remote` runs only the
    agents against a deployed stack (resolves `ARGOX_DASHBOARD_URL` or the ACA
    dashboard FQDN via `az`). Both mint/reuse an API key and start the backend.
  - `seed_policy.py` + `demo_policy.yaml` — seed/update the demo policy via the
    Collector API (POST, then PUT on 409). Nine rules across all three triggers
    with both `block` and `alert` actions.
  - `requirements.txt`, `.env.example`, `README.md` (mode table, policy/prompt
    test matrix).
- Base patterns reused from `deploy/azure/demo.sh` and `demo_agent.py` (key
  minting, Azure-vs-OpenAI backend selection, OTLP + run-record wiring).

## Why
- Needed a way to exercise the deployed dashboard and collector end to end with
  multiple agents and live policy enforcement, plus a self-contained local
  fallback that needs no Azure account.
- All traffic reaches the Collector through the dashboard's public surface
  (`/api`, `/v1`), keeping the Collector private — matching the deployed
  topology rather than talking to the Collector directly.

## Notes / follow-ups
- Policy seeding defaults ON for `local`, OFF for `remote` (`SEED_POLICY=true`
  to override) so a demo run never mutates a deployed fleet's policies.
- Surfacing alert decisions in the front depends on POL-06 (alerts were dropped
  by the manager before that fix).
