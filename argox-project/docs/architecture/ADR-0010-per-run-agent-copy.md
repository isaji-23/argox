# ADR-0010: Instrument a per-run copy of the agent, not the shared instance

- **Status:** accepted
- **Date:** 2026-06-21
- **Ticket:** CORE-09

## Context

`ArgoxManager.run` instrumented the agent by mutating the caller's instance in
place: it snapshotted `agent.tools`, let the plugin rewrite `agent.hooks` and
`agent.tools`, then restored the snapshot in a `finally` (the
`_snapshot_tools` / `_restore_tools` mechanism recorded in ADR-0009).

This is unsafe when one `Agent` object is driven by concurrent `run()` calls —
the common *singleton agent + concurrent requests* pattern, which the live demo
uses (`ThreadingHTTPServer` + a single `self._agent` + `asyncio.run` per request
thread). With runs A and B overlapping on the same instance:

- **Tool-wrapper leak / double-wrap.** A snapshots, wraps; B snapshots (possibly
  capturing A's already-wrapped tools), wraps; the restores cross, leaving tools
  wrapped after the run or emitting nested `execute_tool` spans.
- **Cross-request metrics contamination (privacy).** `agent.hooks` is a single
  `_ArgoxAgentHooks(metrics)` bound to one run's `metrics`; last writer wins, so
  A's tool starts/ends can be recorded into B's `metrics` and exported under B.

PLUGIN-06 (#152) widened the `tools` race by making wrapping unconditional
(previously processor-less runs never touched `agent.tools`).

## Decision

`ArgoxManager.run` instruments a **per-run shallow copy** of the agent rather
than the shared instance:

- `_clone_agent(agent)` returns `copy.copy(agent)` and rebinds the copy's
  `tools` to its own `list(agent.tools)`. A shallow copy is sufficient: the
  Manager and plugins only *rebind* `tools`/`hooks` on the copy (they never
  mutate shared nested objects in place), and the plugin wraps tools onto copies
  of the originals. If the agent cannot be copied, the original is returned so
  behaviour degrades to the previous in-place semantics rather than failing.
- Tool filtering (`_apply_tool_filter`), plugin instrumentation
  (`plugin.instrument`), and the runner all operate on the copy. The shared
  agent is never mutated, so the `finally` no longer restores anything and
  `_snapshot_tools` / `_restore_tools` are removed.

Consequence for the `@monitor` decorator: the instrumented object is now
**always** distinct from the agent located in the function's closure/globals.
A `@monitor`-wrapped function must therefore declare an `agent` parameter to
receive the instrumented copy; the decorator injects it there. A prompt-only
function cannot be threaded the copy and emits the existing "instrumentation is
lost" `RuntimeWarning` — this now fires even for in-place-mutating plugins,
which previously reached the closure agent directly. The live demo already uses
the injection pattern (`async def run_agent(agent, prompt)` + `Runner.run(agent,
...)`), so it is unaffected and gains concurrency safety.

## Triggers for the next refactor

- An agent type that `copy.copy` cannot safely shallow-copy (e.g. shared mutable
  state that instrumentation does mutate in place) — the clone strategy needs a
  per-framework hook or a deep copy of specific fields.
- A plugin that needs to mutate fields beyond `tools`/`hooks` on the instrumented
  agent — confirm those mutations are rebinds, not in-place edits of objects the
  shared agent still references.
- Demand to keep the prompt-only `@monitor` closure pattern instrumented under
  concurrency — impossible with a shared object; would require the decorator to
  build a per-request agent instead.

## What stays out of scope

- **The `on_tool_end` start/end pairing.** `_ArgoxAgentHooks.on_tool_end` pairs
  by a reversed `name == tool.name and end is None` scan. Per-run cloning fixes
  cross-request mixing, but within a single run with parallel invocations of the
  *same* tool the end may still close the wrong start. Separate follow-up.
- **Serializing runs per agent.** A per-agent lock was considered (issue #153,
  option 2) but rejected: it would force the live demo's concurrent requests to
  run sequentially. Cloning keeps them concurrent.
- **The `ArgoxPlugin.instrument` contract.** Unchanged — plugins still receive an
  agent and return an instrumented agent; they simply receive a copy now.
