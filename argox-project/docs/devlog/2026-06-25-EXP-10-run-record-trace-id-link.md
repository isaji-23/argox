# [EXP-10] Link run records to their trace for by-trace lookup

- **Date:** 2026-06-25
- **PR:** #185  ·  **Branch:** fix/run-record-trace-id-link
- **Status:** in-review

## What changed
- `argox-core/src/argox/core/state.py`: added a `trace_id: str | None` field to
  `AgentRunMetrics` and serialized it in `to_dict()` (top-level, right after
  `run_id`), so the payload `HttpRunExporter` POSTs to `/v1/runs` now carries the
  trace id.
- `argox-core/src/argox/core/manager.py`: in `ArgoxManager.run`, stamp
  `metrics.trace_id` from the active `argox.agent.run` root span
  (`format(span.get_span_context().trace_id, "032x")`) — the same 32-char
  lowercase hex id the OTLP span exporter ships for that span. Guarded against a
  zero trace id from a sampled-out / non-recording span.
- `tests/test_run_root_attributes.py`: regression test asserting the captured
  run's `trace_id` equals its span's and round-trips through `to_dict()`.

## Why
The Collector resolves `GET /api/v1/runs/by-trace/{trace_id}` purely on the
`runs.trace_id` column (`WHERE trace_id = ?`, see ADR-0007). But the run payload
never carried a trace id — `AgentRunMetrics` had no such field and `to_dict()`
omitted it — so every run was stored unlinked and the endpoint returned **404
for every trace**, including freshly ingested ones. The dashboard Run Record
panel was therefore always empty under real auth. This fulfils the join contract
that ADR-0007 and the `EXP-09` exporter assumed: the SDK now stamps the join key
from the root span. The Collector needed no change.

## Notes / follow-ups
- Pairs with #186, which makes the demo agent actually post run records and
  fixes the separate Policies-screen 401.
