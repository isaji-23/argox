# Plugin Interface Evolution

This document captures the design decisions taken during PLUGIN-02 around the
`ArgoxPlugin.instrument` contract, and the refactors we deliberately deferred.
Future contributors extending the plugin layer should read this before adding
new plugin-side hooks so the interface evolves consistently instead of
accumulating drift.

## Current shape (PLUGIN-02)

```python
def instrument(
    self,
    target: Any,
    metrics: AgentRunMetrics,
    tool_args_runner: ToolArgsRunner | None = None,
) -> Any:
    ...
```

`ToolArgsRunner` is a callable supplied by `ArgoxManager` on every run. Plugins
invoke it from inside their tool-execution shim with `(tool_name, args_dict)`
and receive a mutated `dict` to forward to the framework-native tool. The
manager owns the processor chain behind the callable, including:

- per-processor `strict` semantics (fail-open vs. fail-closed),
- `EVENT_PROCESSOR_APPLIED` / `EVENT_PROCESSOR_ERROR` span events,
- `ARGOX_PROCESSOR_PHASE = "tool_args"` and `ARGOX_PROCESSOR_TOOL_NAME` attribution.

Plugins are deliberately ignorant of the processor list. That keeps the manager
as the single source of truth for processor failure semantics and OTel event
emission, so every future plugin gets consistent behaviour for free.

## Why a kwarg and not a `PluginInstrumentContext` dataclass

Today there is one optional channel (`tool_args_runner`). Adding it as a kwarg
costs less than introducing a context object that exists to hold a single
field. The cost of refactoring to a context object once a second hook lands is
lower than the cost of building speculative abstraction now.

## Triggers for the next refactor

### When to introduce a `PluginInstrumentContext`

Refactor `instrument(target, metrics, **hooks)` into
`instrument(target, ctx: PluginInstrumentContext)` once **either** of these
happens:

1. A second optional hook lands (e.g. `tool_result_runner`, `prompt_inspector`,
   `streaming_chunk_runner`). Two kwargs is still tolerable; at three the
   signature becomes noisy and every test plugin re-types the same defaults.
2. A hook needs to grow context that is not a callable — for example, a
   `RunContext` reference, a tracer handle, or a feature-flag bundle. Stuffing
   non-callables alongside callables in kwargs makes the contract harder to
   read.

The expected shape:

```python
@dataclass(frozen=True)
class PluginInstrumentContext:
    metrics: AgentRunMetrics
    tool_args_runner: ToolArgsRunner | None = None
    tool_result_runner: ToolResultRunner | None = None
    # ...future hooks
```

This is a breaking change for every plugin and every test stub. Do it once and
update everything in the same PR.

### When to add a `cleanup(target)` lifecycle hook

PLUGIN-02 uses `copy.copy(FunctionTool)` so the original tools in
`agent.tools` are never mutated. `ArgoxManager._restore_tools` then puts the
original list back, and the in-memory copies are garbage-collected. This works
because `FunctionTool` is a non-frozen `@dataclass` and `__copy__` is cheap.

That assumption breaks for plugins where:

- Tool objects hold expensive state (DB clients, network sessions) and copying
  is wasteful or unsafe.
- The framework forbids shallow copies (e.g. it relies on identity comparison).
- Restoration needs side effects beyond swapping a list — closing a handle,
  unsubscribing from an event bus, flushing a buffer.

When the first plugin hits one of those, add an optional `cleanup` method to
`ArgoxPlugin` (default no-op) and call it from the `finally` block of
`ArgoxManager.run`. Until then we are not building it speculatively.

### When to extend `ArgoxProcessor`

`ArgoxProcessor` defines `process_input`, `process_tool_args`, and
`process_output`. Any new phase (for example `process_tool_result`) requires
adding both a `process_*` method on `ArgoxProcessor` **and** a sibling helper
on `ArgoxManager` analogous to `_run_tool_args_processors`. The pattern is:

1. Add the method to `ArgoxProcessor` with a clear `(value, ctx) -> value`
   signature, defaulting to identity in a base implementation if the project
   wants gradual rollout. PLUGIN-02 chose strict abstract methods for clarity;
   that is the recommended default.
2. Add a `_run_<phase>_processors(span, ctx, value, applied)` helper on
   `ArgoxManager`. Reuse the strict-flag + span-event pattern from the
   existing helpers verbatim — drift here causes operational confusion.
3. Add a phase string to the `ARGOX_PROCESSOR_PHASE` docstring and a
   `ARGOX_PROCESSOR_*` attribute constant if the new phase has extra
   correlation data (as `ARGOX_PROCESSOR_TOOL_NAME` does today).
4. Expose a runner callable on `PluginInstrumentContext` (or a new kwarg until
   the dataclass refactor lands) when plugins need to invoke the chain from
   their shim.

## Per-plugin concerns that should stay local

The following are framework-specific and should **not** leak into the
`ArgoxPlugin` interface:

- **Tool-collection access**: `agent.tools` (OpenAI Agents SDK, LangChain,
  CrewAI), `agent.functions`, `runnable.tools`. Each plugin knows its own
  framework's convention.
- **Serialisation format**: OpenAI Agents passes tool args as JSON strings;
  LangChain passes them as Python dicts; Pydantic AI parses to typed models.
  Plugins handle the boundary conversion before calling the runner.
- **Wrap vs. monkey-patch + restore**: `copy.copy` happens to be the right
  choice for the OpenAI plugin because `FunctionTool.__copy__` is cheap and
  the manager's `_restore_tools` cleans up. Plugins on other frameworks may
  prefer subclassing or in-place patch + cleanup hook.
- **Hosted/server-side tool detection**: every framework has tools whose
  execution happens server-side and cannot be intercepted client-side. Each
  plugin filters by `isinstance` (or equivalent) on entries it cannot wrap.

## SDK version pinning

The OpenAI plugin's shim relies on
`agents.tool.FunctionTool.on_invoke_tool` accepting `(ToolContext, str)` and
the SDK delegating to it from `invoke_function_tool` (`agents/tool.py:1672`).
This contract has been stable through the `openai-agents` 0.x series, but the
plugin's `pyproject.toml` should track a compatible range. When a new major
version of `openai-agents` ships, re-verify:

1. `FunctionTool.on_invoke_tool` still receives a JSON string.
2. `copy.copy(FunctionTool)` still produces an isolated instance with a
   working `__post_init__`.
3. `ToolContext.tool_name` still carries the LLM-facing tool name at the
   call site.

If any of those changes, the wrap strategy needs a corresponding update — not
the `ArgoxPlugin` interface.
