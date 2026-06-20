# [PLUGIN-05] Set gen_ai.request.model from Agent.model

- **Date:** 2026-06-20
- **PR:** #150  ·  **Branch:** feat/PLUGIN-05-request-model-attribute
- **Status:** in-review

## What changed
- `argox-plugins/argox-plugin-openai/src/argox_openai/plugin.py`:
  `ArgoxOpenAIPlugin.instrument` now tags the active `argox.agent.run` span with
  `gen_ai.request.model`, resolved from `Agent.model`. Because `instrument` runs
  inside the Manager's run span, it sets the attribute via
  `trace.get_current_span()`.
  - New helper `_resolve_request_model(model)`: a plain string id is used
    directly; a `Model` instance is read via its `.model` attribute; `None`,
    empty, or an object without a usable id yields `None` so the attribute is
    left unset (the agent then relies on the SDK default).
- Added tests in `tests/test_plugin_openai.py`: `_resolve_request_model` cases
  (string / `Model` instance / `None` / empty / no id) and a span-level check
  that `instrument` emits `gen_ai.request.model` from `Agent.model` and leaves
  it unset when unresolvable.

## Why
The Collector's cost enricher (COL-07) prices a run from `gen_ai.request.model`
matched against `pricing.yaml`. The plugin reported token usage but never set
the model, so `enrich_cost` returned early, `spans.run_cost` stayed `NULL`, and
the dashboard cost card was empty for every real run. Only the live-demo
`azure_bridge.py` glue worked around this by setting the attribute by hand. The
plugin now emits it itself, so a real OpenAI/Azure run prices without manual
attribute setting. Companion to CORE-08 (#143), which made the SDK emit
`argox.run.success` and `argox.agent.name`.

## Notes / follow-ups
- Azure caveat: deployment names often differ from the priced model id. The
  plugin reports whatever the agent exposes; mapping a deployment name to a
  `pricing.yaml` key (or `ARGOX_PRICING_TABLE_PATH`) stays the operator's
  responsibility. Documented in the `instrument` docstring.
- Run-summary export to `/v1/runs` is #106 (EXP-09).
