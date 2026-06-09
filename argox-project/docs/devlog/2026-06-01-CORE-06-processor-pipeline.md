# [CORE-06] Processor pipeline + OTel run span

- **Date:** 2026-06-01
- **PR:** #35  ·  **Branch:** feat/CORE-06-pipeline-manager
- **Status:** merged

> Seed entry illustrating the devlog format. Generated retroactively from
> `plan.md`; future entries are produced by `/argox-doc` from the merged diff.

## What changed

- `ArgoxManager.run()` now drives the full run lifecycle inside a single
  `argox.agent.run` OTel span (`argox-core/src/argox/core/manager.py`).
- Registered processors are invoked in registration order for the `input` and
  `output` phases; `process_tool_args` is reserved for the plugin touchpoint.
- Per-processor `strict` flag: `strict=False` (default) is fail-open — errors
  become `argox.processor.error` span events and the value flows unchanged;
  `strict=True` is fail-closed and marks the run span ERROR.
- Span attributes populated for token usage, policy decisions and blocked tools
  using OTel GenAI semantic conventions (`argox/semconv/attributes.py`).

## Why

Centralising the processor chain and failure semantics in the Manager keeps it
the single source of truth, so every plugin inherits consistent behaviour.
See ADR-0001 ([plugin-interface-evolution](../architecture/plugin-interface-evolution.md))
for the contract that grew out of this.

## Notes / follow-ups

- `process_tool_args` was defined here but not wired until PLUGIN-02.
- `asyncio.CancelledError` always propagates regardless of `strict`.
