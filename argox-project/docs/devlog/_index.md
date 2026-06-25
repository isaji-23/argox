# Devlog Index

Chronological record of shipped work, one entry per ticket/PR. Newest first.
Each entry captures **what changed** and **why**, written by `/argox-doc` from
the merged diff. See [`../architecture/_index.md`](../architecture/_index.md)
for the decisions behind these changes and
[`../insights/errors.md`](../insights/errors.md) for debugging knowledge.

| Date | Ticket | Title | PR | Status |
|---|---|---|---|---|
| 2026-06-25 | DASH-07 | Authenticate dashboard policy requests; post demo run records | #186 | in-review |
| 2026-06-24 | COL-20 | Bundle argox-core into the collector image | #178 | in-review |
| 2026-06-24 | DASH-06 | API key management UI in the dashboard | #173 | in-review |
| 2026-06-24 | DASH | Authenticate dashboard API requests | #171 | in-review |
| 2026-06-24 | DASH-05 | Render run-record content in the dashboard | #108 | in-review |
| 2026-06-23 | DASH-04 | Policy editor with Monaco (live YAML editing) | #91 | in-review |
| 2026-06-22 | DASH-03 | Metrics dashboard (cost, latency, success ratio) | #90 | in-review |
| 2026-06-22 | COL-14 | Chain run records into the WORM audit log | #158 | in-review |
| 2026-06-22 | COL-13 | Query API extension for run records | #157 | in-review |
| 2026-06-22 | EXP-09 | Implement HttpRunExporter (ExporterBase to Collector /v1/runs) | #106 | in-review |
| 2026-06-21 | CORE-09 | Instrument a per-run agent copy to stop concurrent-run races | #154 | in-review |
| 2026-06-21 | PLUGIN-06 | Auto-emit a child span per tool call | #152 | in-review |
| 2026-06-21 | COL-17 | Backfill runs.cost_usd from model and token totals | #151 | in-review |
| 2026-06-20 | PLUGIN-05 | Set gen_ai.request.model from Agent.model | #150 | in-review |
| 2026-06-18 | PLUGIN-04 | Implement argox-plugin-azure-foundry | #147 | in-review |
| 2026-06-16 | CORE-08 | Emit run.success and agent.name on the agent.run root span | #146 | in-review |
| 2026-06-16 | COL-11 | /v1/runs ingest endpoint and run-record storage | #141 | in-review |
| 2026-06-14 | COL-10 | OpenAPI contract and typed TS client pipeline | #136 | in-review |
| 2026-06-13 | COL-09 | Auth middleware — API keys + OIDC | #135 | in-review |
| 2026-06-13 | COL-08 | WORM audit log with hash chain | #134 | in-review |
| 2026-06-10 | PROC-01 | IBAN mod-97 validation in PII detector | #133 | in-review |
| 2026-06-10 | COL-07 | Enrichment worker: normalisation, cost, event PII | #132 | merged |
| 2026-06-10 | COL-04 | Harden DuckDB indexing layer | #131 | in-review |
| 2026-06-10 | DEPLOY-01 | Local Docker Compose stack | #130 | in-review |
| 2026-06-10 | COL-16 | Docker azure extra + configurable CORS | #129 | merged |
| 2026-06-10 | COL-06 | Query API for traces and metrics | #127 | in-review |
| 2026-06-10 | COL-05 | Policy CRUD API and bundle endpoint | #126 | in-review |
| 2026-06-09 | DASH-01 | Dashboard initialization | #125 | in-review |
| 2026-06-08 | COL-03 | OTLP/HTTP trace ingest endpoint | #122 | in-review |
| 2026-06-03 | BENCH-01 | SDK benchmarking infrastructure | n/a | in-review |
| 2026-06-01 | CORE-06 | Processor pipeline + OTel run span | #35 | merged |
| 2026-05-25 | EXP-08 | Rename ConsoleSpanExporter → ConsoleSpanLogger | #103 | merged |
| 2026-05-25 | EXP-04 | Implement AzureBlobSpanExporter | #101 | merged |
