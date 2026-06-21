# ADR-0009: The plugin owns tool-call spans via unconditional FunctionTool wrapping

- **Status:** accepted
- **Date:** 2026-06-21
- **Ticket:** PLUGIN-06

## Context

A monitored run emitted a single root span (`argox.agent.run`). Tool invocations
were recorded into `AgentRunMetrics.tools_called` by the agent lifecycle hooks
but produced no OTel child span, so the dashboard waterfall showed one flat span
with no per-tool breakdown. The only way to get tool-level spans was for the user
to hand-instrument every tool body with `tracer.start_as_current_span(...)` — the
live demo's `azure_bridge.py` did exactly this, plus a `_run_ctx_var` ContextVar
to re-parent spans because it instrumented the *synchronous* tool body, which the
agents SDK runs in a worker thread that loses the ambient OTel context.

`ArgoxOpenAIPlugin` already wrapped `FunctionTool` entries — but only when the
Manager supplied a `tool_args_runner` (i.e. only when processors were
registered), and solely to run the argument-redaction chain. Span emission needs
to happen on *every* run, processors or not.

## Decision

`ArgoxOpenAIPlugin.instrument` **always** replaces each `agents.tool.FunctionTool`
in `agent.tools` with a wrapped copy; the `tool_args_runner` becomes an optional
input to the wrapper rather than the gate for wrapping. The wrapper
(`_wrap_function_tool(tool, runner)`) opens an OTel child span around each
invocation:

- span name `execute_tool {tool.name}`, attributes
  `gen_ai.operation.name=execute_tool` and `gen_ai.tool.name` (GenAI semconv);
- when the invocation raises past the shim, span status `ERROR` + `error.type`
  (the exception class name only), then re-raise. The span is opened with
  `record_exception=False` / `set_status_on_exception=False` so the context
  manager does not auto-write the exception message or stack trace — those
  routinely echo the tool's arguments (PII);
- raw tool arguments are never placed on the span (PII);
- when `runner` is set, the shim runs the redaction chain before delegating;
  when `runner is None`, the raw JSON is forwarded byte-for-byte.

Because the shim is `async` and awaited by the SDK runner in the **same task** as
the active `argox.agent.run` span, `start_as_current_span` parents the tool span
automatically — no ContextVar handling (unlike the demo's old sync-body
approach). Always-wrapping is safe because `ArgoxManager._snapshot_tools` /
`_restore_tools` already snapshot `agent.tools` before `instrument()` and restore
the original list in the run's `finally`, so the mutation never leaks past a run.

Span emission is thus the **plugin's** responsibility, not the tool author's: a
monitored run emits one child span per function-tool call with zero user
instrumentation.

## Triggers for the next refactor

- A second SDK plugin needs the same tool-span behaviour — promote the span shape
  (name, attributes, error handling) into a shared helper so each plugin does not
  re-implement the semconv.
- The SDK starts invoking function tools outside the run task (e.g. a thread pool
  that does not copy the OTel context) — the automatic parenting assumption
  breaks and explicit context capture returns.
- Hosted/server-side tool execution becomes observable to the SDK — today those
  non-`FunctionTool` entries pass through unwrapped.

## What stays out of scope

- **Blocked-tool spans.** Policy-blocked tools are stripped from `agent.tools`
  before the run and never invoked, so the plugin never sees them; emitting a
  span for a blocked tool stays the caller's concern (the live demo still does
  this by hand).
- **Recording tool arguments/results on the span.** Deliberately omitted for PII;
  if ever added, only the redacted form may be recorded.
- **Soft-handled tool failures.** A default `@function_tool` keeps its
  `failure_error_function`, so the SDK catches the body's exception inside
  `on_invoke_tool` and returns an error string to the model; the shim never sees
  it, so the span is not marked `ERROR` (the call is still recorded in
  `tools_called`). Span `ERROR` covers only failures that propagate past the
  shim (`failure_error_function=None`, a re-raising invoker, or a failing
  argument-processor chain).
- **Non-OpenAI plugins.** This decision is implemented in `argox-plugin-openai`
  only; the `ArgoxPlugin.instrument` contract is unchanged.
