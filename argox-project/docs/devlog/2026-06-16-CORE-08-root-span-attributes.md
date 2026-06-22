# [CORE-08] Emit run.success and agent.name on the agent.run root span

- **Date:** 2026-06-16
- **PR:** #146  ·  **Branch:** feat/CORE-08-root-span-attributes
- **Status:** in-review

## What changed
- `argox-core/src/argox/core/manager.py`: on the `argox.agent.run` root span,
  `ArgoxManager.run` now sets two attributes itself:
  - `argox.agent.name` (`ARGOX_AGENT_NAME`), set early near span open from
    `metrics.agent_name`, so it is present even if the run raises before
    completion.
  - `argox.run.success` (`ARGOX_RUN_SUCCESS`), set in the run `finally` from
    `metrics.success`, so every exit path records a value. `metrics.success`
    stays `False` on any error path, including a policy block, so a blocked run
    records `success = False`.
- Added `tests/test_run_root_attributes.py`: asserts both attributes on the root
  span for a success run and for a policy-blocked run.

## Why
The Collector promotes both attributes into queryable columns
(`spans.run_success`, the per-row agent name) via `ingest/otlp.py`. The SDK
never set them, so any real monitored run left the success-rate card empty and
showed the service name instead of the agent name; only the synthetic
`trace_generator.py` and the live-demo `azure_bridge.py` glue populated them by
hand. The SDK now emits them itself, so the live demo's success-rate card and
per-row agent name populate without manual attribute setting.

## Notes / follow-ups
- Cost enrichment still needs `gen_ai.request.model` from the plugin (separate
  plugin ticket).
- Run-summary export to `/v1/runs` is #106 (EXP-09); this ticket is only about
  the two root-span attributes the SDK emits itself.
