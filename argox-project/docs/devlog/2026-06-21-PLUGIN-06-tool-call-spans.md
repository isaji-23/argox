# [PLUGIN-06] Auto-emit a child span per tool call

- **Date:** 2026-06-21
- **PR:** #152  ·  **Branch:** feat/PLUGIN-06-tool-call-spans
- **Status:** in-review

## What changed
- `argox-plugins/argox-plugin-openai/src/argox_openai/plugin.py`:
  `ArgoxOpenAIPlugin.instrument` now **always** wraps every
  `agents.tool.FunctionTool` in `agent.tools`, independent of whether a
  `tool_args_runner` is supplied. Previously wrapping happened only when the
  Manager passed a runner (i.e. when processors were registered); the
  `tool_args_runner is None` early return is gone.
  - `_wrap_function_tool(tool, runner)` takes an **optional** runner. The shim
    opens an OTel child span named `execute_tool {tool.name}` around the
    invocation, carrying GenAI semconv attributes `gen_ai.operation.name=execute_tool`
    and `gen_ai.tool.name`. When the invocation *raises past the shim* the span
    is marked `ERROR` and tagged with `error.type` (the exception class name
    only — never the message or stack trace, which would re-introduce argument
    PII), then re-raised. The span is opened with `record_exception=False` /
    `set_status_on_exception=False` so the context manager does not auto-record
    the message on the way out.
  - With a runner present the shim still parses args, runs the processor
    redaction chain, re-serialises and delegates (unchanged behaviour). With
    `runner is None` the raw JSON is forwarded byte-for-byte — only the span is
    added. Raw tool arguments are never placed on the span (PII).
  - The shim is awaited by the SDK runner in the same task as the active
    `argox.agent.run` span, so `start_as_current_span` parents the tool span
    automatically — no ContextVar handling needed. Module-level
    `_tracer = trace.get_tracer("argox")`.
- `examples/live_demo/azure_bridge.py`: removed the manual
  `tracer.start_as_current_span` instrumentation from `get_weather` /
  `log_user_activity` and the `_run_ctx_var` ContextVar workaround (and the now
  unused `otel_context` import). The plugin covers executed tools; only the
  blocked-tool spans remain hand-emitted (blocked tools are stripped before the
  run and never invoked), and they now parent via the ambient run-span context.
- `tests/test_plugin_openai.py`: new `TestToolCallSpans` (in-memory span
  exporter) asserts one child span per call, correct parent/trace under the run
  span, `ERROR` + `error.type` with no PII on a raising tool, the same path
  reached through a real `@function_tool(failure_error_function=None)`, no error
  marking on success, span emission with no processors registered, and that
  `agent.tools` is restored after the run. The `span_exporter` fixture attaches a
  single exporter per module and clears it per test (no cross-test span leak).
  Updated the two tests that assumed conditional wrapping
  (`test_instrument_wraps_function_tools_even_without_runner`,
  `test_no_processors_still_wraps_but_forwards_raw`).

## Why
A monitored run produced a single root span; tool invocations were recorded into
`AgentRunMetrics.tools_called` but emitted no OTel child span, so the dashboard
waterfall showed one flat span with no breakdown of the agent's tool usage. The
only way to get tool-level spans was for the user to hand-instrument every tool
body — boilerplate that is the plugin's job, not the tool author's. The plugin
now emits these spans with zero user code. Always-wrapping is safe because
`ArgoxManager` already snapshots `agent.tools` before `instrument()` and restores
the original list in its `finally` (see ADR-0009). Companion to CORE-08 (#143,
root-span outcome attributes) and PLUGIN-05 (#144, `gen_ai.request.model`).

## Notes / follow-ups
- Error-span boundary (from PR review): a default `@function_tool` keeps its
  `failure_error_function`, so the SDK catches the body's exception *inside*
  `on_invoke_tool` and returns an error string to the model — the shim never
  sees it and the span stays unmarked (the call is still recorded in
  `tools_called`). The `ERROR` span fires only when the exception propagates
  past the shim: `failure_error_function=None`, a re-raising invoker, or a
  failing argument-processor chain. Documented in the `_wrap_function_tool`
  docstring and ADR-0009.
- Blocked-tool spans in the live demo are still emitted by hand because the SDK
  strips blocked tools before the run, so the plugin never sees them.
- Non-`FunctionTool` entries (hosted/server-side tools) pass through unchanged —
  their execution happens server-side, outside the shim.
