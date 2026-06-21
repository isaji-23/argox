# [CORE-09] Instrument a per-run agent copy to stop concurrent-run races

- **Date:** 2026-06-21
- **PR:** #154  ·  **Branch:** fix/CORE-09-per-run-agent-clone
- **Status:** in-review

## What changed
- `argox-core/src/argox/core/manager.py`: `ArgoxManager.run` no longer mutates
  the shared `Agent` instance. It now creates a per-run shallow copy
  (`_clone_agent(agent)`) and runs tool filtering (`_apply_tool_filter`) and
  plugin instrumentation (`plugin.instrument`) against that copy; the runner
  receives the copy. The `finally` no longer restores `agent.tools` because the
  shared instance is never touched.
  - Replaced the `_snapshot_tools` / `_restore_tools` helper pair with
    `_clone_agent`, which `copy.copy`s the agent and gives the copy its own
    `tools` list. If the agent cannot be copied, the original is returned so
    behaviour degrades to the previous in-place semantics rather than failing the
    run.
  - `_extract_tool_names` is read from the copy.
- `argox-plugins/argox-plugin-openai/src/argox_openai/plugin.py`: docstring only.
  The `instrument` note now states it mutates `hooks`/`tools` in place on the
  per-run copy the Manager passes (no restore), instead of referencing the
  removed `_restore_tools`.
- `argox-core/src/argox/core/decorator.py`: `@monitor` now documents that the
  instrumented object is **always** distinct from the located closure/global
  agent (it is a per-run copy). The "instrumentation lost" `RuntimeWarning` text
  was reworded to say the Manager instrumented a per-run copy that cannot be
  injected without an `agent` parameter.
- `tests/test_manager.py`: added `test_runner_receives_agent_copy_not_shared_instance`
  (runner sees a clone, not the shared agent) and
  `test_concurrent_runs_do_not_share_agent_tools` (two interleaved runs on one
  shared agent each see their own filtered tool list; the shared agent is left
  untouched). The existing restore-after-run tests still pass because the shared
  agent is never mutated.
- `tests/test_monitor_decorator.py`: `test_agent_param_receives_instrumented_agent`
  now asserts the injected wrapper wraps the per-run copy (`inner is not agent`).
  `test_no_warning_when_plugin_mutates_in_place` became
  `test_warns_without_agent_param_even_for_in_place_plugin` — even an
  in-place-mutating plugin can no longer reach the closure agent, so a
  prompt-only function now warns. Updated the warning-match string to
  "instrumentation is lost".

## Why
The shared-agent in-place mutation raced under the common *singleton agent +
concurrent requests* pattern (the live demo runs `ThreadingHTTPServer` + one
`self._agent` + `asyncio.run` per request thread). Two overlapping `run()` calls
could leave tools wrapped/double-wrapped after a run, and — because `agent.hooks`
binds to one run's `metrics` (last writer wins) — record one request's tool
names/results into another request's `metrics` and export them under the wrong
run (cross-request contamination, a privacy issue in multi-tenant deployments).
PLUGIN-06 (#152) broadened the `tools` race by making wrapping unconditional.

Instrumenting a per-run copy removes the shared mutable state entirely, so the
two concurrent runs cannot interfere. See ADR-0010 for the decision and its
trade-off with the `@monitor` closure pattern. Supersedes the
`_snapshot_tools` / `_restore_tools` safety mechanism described in ADR-0009.

## Notes / follow-ups
- Decorator contract change: a `@monitor`-wrapped function must declare an
  `agent` parameter to receive the instrumented copy. Prompt-only functions
  (closure/global agent) now always warn that instrumentation is lost — this used
  to work for in-place-mutating plugins. The live demo already uses the
  injection pattern, so it is unaffected.
- Out of scope (lower-severity, same root cause): `_ArgoxAgentHooks.on_tool_end`
  pairs an end to a start by a reversed `name == tool.name and end is None` scan.
  Per-run cloning fixes cross-request mixing, but within a single run with
  parallel invocations of the *same* tool the end may still close the wrong
  start, crossing durations. Left for a follow-up.
