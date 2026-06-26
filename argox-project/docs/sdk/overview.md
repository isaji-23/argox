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
   removed from the per-run agent copy before the agent starts.
4. **Plugin · `instrument(agent, metrics)`** — the Manager passes a per-run copy
   of the agent (`_clone_agent`, ADR-0010), never the caller's shared instance;
   the plugin wraps that copy with framework-specific hooks and wraps every
   `FunctionTool` so each call emits an `execute_tool {name}` child span
   (PLUGIN-06), then the user's runner executes.
5. **Plugin · `extract_tokens` / `extract_output`** — token usage and the LLM's
   textual answer are pulled from the runner result.
6. **Processors · `output` phase** — final text passes through all processors
   before returning to the caller.
7. **Policy · `check_output`** — last chance to block; violation re-raises
   `PermissionError`.
8. **`finally` · seal & export** — stamp `end_time`, fill the span with OTel
   GenAI semconv, invoke each `ExporterBase.export(metrics)`. No tool restore is
   needed: the shared agent was never mutated, only its per-run copy.

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

- **One root span per run, one child span per tool call.** Token totals, policy
  decisions, blocked-tool lists and processor events attach to the
  `argox.agent.run` root via OTel GenAI semantic conventions
  (`gen_ai.usage.input_tokens`, etc.). `ArgoxOpenAIPlugin` additionally emits one
  `execute_tool {name}` child span per function-tool call
  (`gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`; `ERROR` status +
  `error.type` — type only, no PII — when the tool raises past the shim), so the
  dashboard waterfall shows the tool breakdown with no user instrumentation
  (PLUGIN-06, ADR-0009). Any compatible
  `SpanExporter` can consume them. The root span also carries `argox.agent.name`
  (set early from the run's agent name) and `argox.run.success` (set in
  `finally` from the run outcome, so a policy block records `false`); the
  Collector promotes both into queryable columns. The SDK emits them itself —
  no manual attribute setting in the runner is needed. `ArgoxOpenAIPlugin` also
  tags the same span with `gen_ai.request.model` from `Agent.model` (PLUGIN-05),
  which the Collector's cost enricher needs to compute `run_cost`; if the agent
  has no resolvable model the attribute is left unset.
- **Fail-open by default.** Processors registered with `strict=False` log
  errors as span events and pass the value through unchanged. `strict=True`
  aborts the run. `asyncio.CancelledError` always propagates.
- **Tools filtered before start.** Blocked tools are removed from the per-run
  agent copy in preflight — the agent literally cannot call them during that run,
  and the caller's shared instance is left untouched (ADR-0010).
- **Instrumentation never touches the shared agent.** Each run instruments its
  own shallow copy of the agent, so the same `Agent` object can be driven by
  concurrent runs without their tool wrappers or per-run `hooks`/`metrics` racing
  (ADR-0010).
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
   signature declares an `agent` parameter. Because the Manager instruments a
   per-run copy (ADR-0010), this injection is the only way the run reaches the
   instrumented agent: a prompt-only function keeps using the original closure
   agent and emits a `RuntimeWarning` that instrumentation is lost.
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
`argox-plugin-azure-foundry` (integration with Azure AI Foundry Agent Service),
`argox-plugin-debug` (stub), `argox-exporter-azure` (`AzureBlobSpanExporter`
— fully implemented), end-to-end Azure OpenAI demo.

On the Collector side, policy distribution now exists (COL-05):
`GET /api/v1/policies/bundle` serves a merged, SDK-parseable `PolicyDocument`
YAML with ETag/304 caching — the endpoint `RemotePolicyClient` polls — backed
by versioned policy CRUD under `/api/v1/policies`. The Collector also exposes
a read-only Query API for the dashboard (COL-06): paginated trace summaries
(`GET /api/v1/traces`), per-trace span waterfalls (`GET /api/v1/traces/{id}`)
and trailing-window aggregations (`GET /api/v1/metrics/cost|latency|success`)
served from the DuckDB index. The Query API also reads run content (COL-13):
`GET /api/v1/runs` lists lightweight run rows (no prompt/output payload) with
`agent`/`from`/`to`/`success`/`page`/`page_size` filters, sorted and windowed on
the collector-assigned `ingested_at`; `GET /api/v1/runs/{run_id}` and
`GET /api/v1/runs/by-trace/{trace_id}` return the full record byte-for-byte from
the immutable blob (falling back to the index row when the blob is unavailable).
Alongside the lightweight span path, a parallel
run-summary ingest path (COL-11) accepts full run content the spans omit:
`POST /v1/runs` takes one or a batch of `AgentRunMetrics`-shaped records, stores
each as an immutable blob (`runs/{YYYY-MM-DD}/{run_id}.json`) and projects a
queryable summary into a DuckDB `runs` table whose indexed `trace_id` joins a
span back to its run (see ADR-0007; the SDK exporter that posts these is the
EXP-09 follow-up). The join key is supplied by the SDK: `ArgoxManager` stamps
`AgentRunMetrics.trace_id` from the `argox.agent.run` root span so the posted
record carries the same trace id its spans do (EXP-10) — without it
`by-trace` resolves nothing. The `runs.cost_usd` column, left NULL at ingest, is
backfilled (COL-17) via a separate `UPDATE` from the run's `model` and token
totals — falling back to the model its spans carry (`gen_ai.request.model`)
joined by `trace_id` — priced against a committed snapshot of the LiteLLM price
table (`pricing.yaml`, regenerated by `argox-collector refresh-pricing`; unknown
models log a warning and stay NULL). Ingest-time enrichment (COL-07) normalises
variant GenAI attribute shapes (legacy `gen_ai.usage.prompt_tokens`,
OpenInference `llm.*`) onto the canonical keys, computes per-span `run_cost`
from a YAML pricing table (unknown models log a warning and skip), and tags
`argox.pii.residual_detected` when a high-confidence pattern matches span
attributes or event payloads; every stage is idempotent. A tamper-evident
audit log (COL-08) records governance events as append-only JSONL segments
(`audit-log/{YYYY}/{MM}/{seq_start}-{seq_end}.jsonl`) linked into a SHA-256
hash chain: `POST /api/v1/audit` appends, `GET /api/v1/audit/verify` walks the
chain and reports the first broken link, and the log exposes no delete
operation (AI Act Art. 12 retention). It is a single **unified chain** (COL-14):
every record carries a hashed `kind` discriminator (`run` | `span_batch` |
`event`), and a run record persisted by `/v1/runs` is appended with
`kind="run"` and the digest of its immutable blob right after the blob write,
so the Art. 12/13 content it carries (prompt, output, tokens, violations) is
tamper-evident. `verify` reports the broken record's `kind`, `target`
(`run_id` / `trace_id`) and zero-based offset. Every Collector endpoint except the
health probes is now authenticated (COL-09): SDK clients send a scoped,
revocable API key as `Authorization: Bearer argox_…` (ingest needs the
`ingest` scope, `RemotePolicyClient` polling needs `policy-read`), while
dashboard users present an OIDC JWT whose role claim drives policy-write/admin
RBAC. Keys are stored hashed in the index DB and managed via admin-only CRUD
or the `argox-collector keys` CLI; see `docs/collector/auth.md`. The SDK clients
that talk to authenticated endpoints accept the key directly: `HttpRunExporter`,
`RemotePolicyClient` and `OTLPSpanExporter` all take an `api_key` constructor
argument and send it as `Authorization: Bearer …` on every request (POL-05),
warning when a key is configured over a non-HTTPS endpoint. For
`OTLPSpanExporter` the argument is a thin convenience over the upstream OTel
exporter — equivalent to passing `headers={"Authorization": …}` or setting
`OTEL_EXPORTER_OTLP_HEADERS`; an explicit `Authorization` header wins over
`api_key`.

**Not yet:** no real `SsePolicyClient` (only
the contract + in-process cache),
and the SDK itself does not write to the audit log yet (it is a Collector-side
API) nor render a dashboard (only the `metrics` object and OTel spans ready to
export).
