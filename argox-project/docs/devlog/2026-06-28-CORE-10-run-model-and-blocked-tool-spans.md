# [CORE-10] Carry model on the run record and emit blocked-tool spans

- **Date:** 2026-06-28
- **PR:** (pending)  ·  **Branch:** fix/CORE-10-run-model-and-blocked-tool-spans
- **Status:** in-review

## What changed
- `AgentRunMetrics` gains a `model` field, serialized by `to_dict`
  (`argox-core/src/argox/core/state.py`). The OpenAI plugin now mirrors the
  resolved model onto `metrics.model` alongside the existing
  `gen_ai.request.model` span attribute
  (`argox-plugins/argox-plugin-openai/src/argox_openai/plugin.py`). So
  `HttpRunExporter` ships the model in the `/v1/runs` payload, the Collector
  already reads `payload.model` into the run record, and `enrich_run_cost`
  backfills `cost_usd` instead of leaving it NULL.
- Policy-blocked tools now emit a zero-duration child span named
  `execute_tool {name}` carrying `argox.policy.decision=block`,
  `argox.policy.rule_id`, and the GenAI tool attributes
  (`_record_blocked_tool_span` in `core/manager.py`). A blocked tool is stripped
  before the run, so it never produced an `execute_tool` span of its own; the
  block was therefore invisible to anything that reads spans.
- Tests: blocked-tool span emission (`tests/test_run_root_attributes.py`),
  `model` in `to_dict` (`tests/test_core_data_model.py`), and the plugin mirror
  onto `metrics.model` (`tests/test_plugin_openai.py`).

## Why
- The redesigned dashboard SPA reads model + cost from the run record
  (`run.model`, `run.cost_usd`) and derives policy blocks from spans
  (`spans.policy_decision = 'block'`). None of these were populated:
  `AgentRunMetrics` never carried `model` (so the run cost stayed NULL), and tool
  blocks were only recorded as a metric counter plus the root span's
  `argox.run.blocked_tools` attribute — never as a per-span decision. As a
  result the trace detail showed Model/Cost as "—" and counted zero policy
  blocks for tool blocks.
- The Collector's blocked-tool metric (`top_blocked_tools`) and the trace-detail
  block UI both query `spans.policy_decision = 'block'`, so emitting the span is
  the single change that lights up both.

## Notes / follow-ups
- Azure deployment names still must match a `pricing.yaml` key (or
  `ARGOX_PRICING_TABLE_PATH`) for cost to compute; the SDK reports whatever the
  agent exposes (documented on `instrument`).
- Input/output blocks set `policy_decision=block` on the root span, so
  `top_blocked_tools` can still list `argox.agent.run` for those; a dedicated
  per-decision span name for input/output is a possible later refinement.
