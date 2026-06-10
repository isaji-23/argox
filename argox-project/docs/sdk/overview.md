# Argox SDK — How it works

Argox is an **observability and governance SDK for AI agents**. The user keeps
writing normal agent code (today: OpenAI Agents SDK); Argox wraps the call and
runs a lifecycle of **policies, processors, telemetry and export** around it.

This document is the conceptual reference kept in sync with the code. `/argox-doc`
updates the relevant section whenever public API or behaviour changes. For the
decisions behind the design see [`../architecture/_index.md`](../architecture/_index.md);
for chronological change history see [`../devlog/_index.md`](../devlog/_index.md).

## 1. Public surface

Four names are exported from `argox/__init__.py` — the entire API a user needs:

| Symbol | Type | Purpose |
|---|---|---|
| `argox.monitor` | Decorator | Main entry point. Wraps the function that runs the agent. |
| `argox.ArgoxManager` | Class | Orchestrator the decorator uses underneath. Available for manual wiring. |
| `argox.init_telemetry` | Function | Configures the OpenTelemetry `TracerProvider` in one line. |
| `argox.init_metrics` | Function | Configures the OpenTelemetry `MeterProvider` in one line. |

Minimal integration:

```python
import argox
from argox.core import init_telemetry
from argox.observability import ConsoleSpanLogger
from argox_openai import ArgoxOpenAIPlugin

init_telemetry(exporters=[ConsoleSpanLogger()])

agent = Agent(name="weather-assistant", tools=[get_weather, ...], ...)

@argox.monitor(
    plugin=ArgoxOpenAIPlugin(),
    agent=agent,
    policy=_InlinePolicy(),
    processors=[_PiiRedactingProcessor()],
    exporters=[_PrintMetricsExporter()],
)
async def run_agent(agent: Agent, prompt: str):
    return await Runner.run(agent, prompt)
```

The decorator resolves plugin, agent, prompt and exporters on its own — no
manual `ArgoxManager` wiring.

## 2. The four extension contracts

Anything framework- or client-specific plugs in through one of four interfaces.
The Manager only talks to these abstractions, keeping Argox framework-agnostic.

| Interface | File | Responsibility |
|---|---|---|
| `ArgoxPlugin` | `interfaces/plugin.py` | Knows **one** framework. Methods: `instrument()`, `extract_tokens()`, `extract_output()`. |
| `PolicyClient` | `interfaces/policy.py` | Three evaluation points: `check_input`, `is_tool_allowed`, `check_output`. Returns a `PolicyResult` (ok / block / alert). |
| `ArgoxProcessor` | `interfaces/processor.py` | In-flight data transformer (PII, sanitisation). Phases: `process_input`, `process_tool_args`, `process_output`. |
| `ExporterBase` | `interfaces/exporter.py` | Receives the final `AgentRunMetrics` and ships it somewhere (console, dashboard, audit). |

## 3. Run lifecycle

When the `@argox.monitor`-decorated function is called, `ArgoxManager`
(`core/manager.py`) drives this exact sequence, all inside a single OTel span
`argox.agent.run`:

1. **Processors · `input` phase** — raw prompt is persisted in `metrics`, then
   transformed. Ideal for PII redaction before the LLM sees it.
2. **Policy · `check_input`** — `block` aborts the run with `PermissionError`.
3. **Policy · `is_tool_allowed` (per tool)** — blocked tools are physically
   removed from `agent.tools` before the agent starts; restored in `finally`.
4. **Plugin · `instrument(agent, metrics)`** — plugin wraps the agent with
   framework-specific hooks, then the user's runner executes.
5. **Plugin · `extract_tokens` / `extract_output`** — token usage and the LLM's
   textual answer are pulled from the runner result.
6. **Processors · `output` phase** — final text passes through all processors
   before returning to the caller.
7. **Policy · `check_output`** — last chance to block; violation re-raises
   `PermissionError`.
8. **`finally` · seal & export** — restore `agent.tools`, stamp `end_time`, fill
   the span with OTel GenAI semconv, invoke each `ExporterBase.export(metrics)`.

Phase timing is **opt-in**: construct `ArgoxManager(enable_phase_timings=True)`
(default `False`) and each phase boundary is timed with `time.perf_counter()` and
written to `AgentRunMetrics.phase_timings` (keys: `processors_input`,
`policy_input`, `tool_filter`, `agent_exec`, `processors_output`,
`policy_output`, `export`). When enabled, all keys are pre-seeded to `0.0` at run
start, so a key is always present even when its branch is skipped or the run
raises before reaching it. When disabled the probes are skipped entirely (no
`perf_counter` cost on the hot path) and `phase_timings` stays empty. SDK
overhead percentage is `(total_ms - phase_timings["agent_exec"]) / total_ms * 100`.

## 4. Key behaviours

- **One span per run.** Token totals, policy decisions, blocked-tool lists and
  processor events attach to `argox.agent.run` via OTel GenAI semantic
  conventions (`gen_ai.usage.input_tokens`, etc.). Any compatible
  `SpanExporter` can consume it.
- **Fail-open by default.** Processors registered with `strict=False` log
  errors as span events and pass the value through unchanged. `strict=True`
  aborts the run. `asyncio.CancelledError` always propagates.
- **Tools filtered before start.** Blocked tools are removed from `agent.tools`
  in preflight and restored in `finally` — the agent literally cannot call them
  during that run.
- **Two possible exits.** Policy block (input, tool, or output) →
  `PermissionError`. Anything else → final string returned to the caller. No
  third state.
- **Exporters never crash the run.** A throwing `ExporterBase.export()` is
  caught into `metrics.exporter_errors`; the caller still gets their answer.
- **The plugin rewrites tool args (PLUGIN-02).** `ArgoxOpenAIPlugin` wraps each
  `function_tool` so `process_tool_args` runs on the LLM-emitted arguments
  *before* the tool body runs. The original argument never reaches the tool.

## 5. What the decorator does

`@argox.monitor` (`core/decorator.py`) is ergonomics over `ArgoxManager`:

1. **Resolves the plugin** — instance or entry-point name (`plugin="openai"`)
   discovered via `importlib.metadata`.
2. **Builds the Manager** — registers plugin, processors, exporters, policy.
3. **Locates the agent** — explicit `agent=` kwarg → function closure → module
   globals.
4. **Locates the prompt** — first positional after `self`/`cls`, or `prompt=`.
5. **Injects the instrumented agent** back into the wrapped function if its
   signature declares an `agent` parameter.
6. **Supports sync and async** — clear error if a sync wrapper is invoked inside
   an already-running event loop.

## 6. OTel span exporters

These are standard `SpanExporter` implementations for `init_telemetry(exporters=[...])`.
They are distinct from `ExporterBase` — they receive OTel `ReadableSpan` objects
produced by the `TracerProvider`, not the `AgentRunMetrics` object.

| Class | Import | Output |
|---|---|---|
| `ConsoleSpanLogger` | `argox.observability` | One-line summary per span to stdout: name, duration, status, tokens, cost, policy decision. |
| `JsonlSpanExporter` | `argox.observability` | Appends spans as JSONL lines to a file. |
| `OTLPSpanExporter` | `argox.observability` | Sends spans to the Argox Collector via HTTP/protobuf (thin wrapper over OTel's OTLP exporter). |
| `AzureBlobSpanExporter` | `argox_azure` | Writes each export batch as a JSONL blob to Azure Blob Storage under `spans/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.jsonl`. Initialised with a connection string and container name. |

`argox.exporters` is reserved for `ExporterBase` implementations (which receive
`AgentRunMetrics`). It is currently empty — concrete `ExporterBase` implementations
live in the integration packages (e.g. a future `argox-exporter-dashboard`).

## 7. Available today vs. pending

**Available:** `argox-core` (Manager, decorator, interfaces, state, OTel init,
semconv, policy parser + local cache, `ConsoleSpanLogger`, `JsonlSpanExporter`,
`OTLPSpanExporter`), `argox-plugin-openai` (real plugin),
`argox-plugin-debug` (stub), `argox-exporter-azure` (`AzureBlobSpanExporter`
— fully implemented), end-to-end Azure OpenAI demo.

On the Collector side, policy distribution now exists (COL-05):
`GET /api/v1/policies/bundle` serves a merged, SDK-parseable `PolicyDocument`
YAML with ETag/304 caching — the endpoint `RemotePolicyClient` polls — backed
by versioned policy CRUD under `/api/v1/policies`. The Collector also exposes
a read-only Query API for the dashboard (COL-06): paginated trace summaries
(`GET /api/v1/traces`), per-trace span waterfalls (`GET /api/v1/traces/{id}`)
and trailing-window aggregations (`GET /api/v1/metrics/cost|latency|success`)
served from the DuckDB index. Ingest-time enrichment (COL-07) normalises
variant GenAI attribute shapes (legacy `gen_ai.usage.prompt_tokens`,
OpenInference `llm.*`) onto the canonical keys, computes per-span `run_cost`
from a YAML pricing table (unknown models log a warning and skip), and tags
`argox.pii.residual_detected` when a high-confidence pattern matches span
attributes or event payloads; every stage is idempotent.

**Not yet:** no real `SsePolicyClient` (only the contract + in-process cache),
no durable audit storage or dashboard from the SDK (only the `metrics` object
and OTel spans ready to export).
