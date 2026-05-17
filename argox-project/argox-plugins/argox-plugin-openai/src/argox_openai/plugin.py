"""ArgoxOpenAIPlugin — integrates the OpenAI Agents SDK with ArgoxManager.

The plugin bridges three responsibilities to the SDK:

- ``instrument``  attaches lifecycle hooks (:class:`_ArgoxAgentHooks`) to the agent so
  tool invocations are recorded into ``AgentRunMetrics.tools_called`` during the run,
  and, when the Manager supplies a ``tool_args_runner``, wraps every
  :class:`agents.tool.FunctionTool` in ``agent.tools`` so the registered
  ``ArgoxProcessor.process_tool_args`` chain runs against each invocation before the
  framework executes the underlying function.
- ``extract_tokens`` walks ``RunResult.raw_responses`` and appends one
  :class:`~argox.core.state.ApiCallRecord` per LLM call observed.
- ``extract_output`` returns ``RunResult.final_output`` as a plain string.

The ``Agent`` class from openai-agents is a Pydantic-like model whose fields are
not freely assignable, so the plugin uses ``object.__setattr__`` to write the
``hooks`` attribute. This matches the pattern used in the project's reference
implementation.
"""

from __future__ import annotations

import copy
import json
import time
from typing import Any

from agents import Agent
from agents.lifecycle import AgentHooks, RunContextWrapper
from agents.tool import FunctionTool

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord
from argox.interfaces.plugin import ArgoxPlugin, ToolArgsRunner


class _ArgoxAgentHooks(AgentHooks):
    """OpenAI Agents lifecycle hooks that record tool starts/ends into AgentRunMetrics."""

    def __init__(self, metrics: AgentRunMetrics) -> None:
        self._metrics = metrics

    async def on_tool_start(
        self,
        context: RunContextWrapper,
        agent: Agent,
        tool: Any,
    ) -> None:
        self._metrics.tools_called.append(
            ToolCallRecord(name=tool.name, start=time.time())
        )

    async def on_tool_end(
        self,
        context: RunContextWrapper,
        agent: Agent,
        tool: Any,
        result: Any,
    ) -> None:
        for record in reversed(self._metrics.tools_called):
            if record.name == tool.name and record.end is None:
                record.end = time.time()
                record.result = result if isinstance(result, str) else str(result)
                break


class ArgoxOpenAIPlugin(ArgoxPlugin):
    """ArgoxPlugin implementation for the OpenAI Agents SDK.

    Note:
        ``instrument`` mutates ``agent.hooks`` and does not restore it. The
        Manager replaces the hooks on every ``run()`` call, so this is safe for
        manager-driven workflows. Running the agent directly via ``Runner`` outside
        the Manager after a managed run will still trigger the previous run's hooks.

        When ``tool_args_runner`` is supplied, ``agent.tools`` is rewritten to a
        list of cloned :class:`FunctionTool` instances whose ``on_invoke_tool`` is
        a shim that runs the processor chain before delegating. The originals are
        never mutated; ``ArgoxManager._restore_tools`` puts the original list back
        after the run, so subsequent direct ``Runner`` calls observe the untouched
        tools.
    """

    @property
    def name(self) -> str:
        return "openai"

    def instrument(
        self,
        target: Agent,
        metrics: AgentRunMetrics,
        tool_args_runner: ToolArgsRunner | None = None,
    ) -> Agent:
        """Attach Argox lifecycle hooks and (optionally) wrap function tools.

        Uses ``object.__setattr__`` to bypass Pydantic field validation on
        ``Agent``. When ``tool_args_runner`` is provided and the agent exposes
        a ``tools`` list, each :class:`FunctionTool` entry is replaced with a
        copy whose ``on_invoke_tool`` runs the processor chain against the parsed
        arguments before invoking the original. Non-``FunctionTool`` entries
        (hosted tools, file search, computer use, etc.) are passed through
        unchanged because their execution happens server-side.
        """
        object.__setattr__(target, "hooks", _ArgoxAgentHooks(metrics))

        if tool_args_runner is None:
            return target
        if not hasattr(target, "tools"):
            return target

        wrapped_tools = [
            _wrap_function_tool(tool, tool_args_runner)
            if isinstance(tool, FunctionTool)
            else tool
            for tool in target.tools
        ]
        try:
            target.tools = wrapped_tools
        except (AttributeError, TypeError):
            # Some frameworks make `.tools` read-only; bypass Pydantic field validation
            # the same way we do for `hooks`.
            object.__setattr__(target, "tools", wrapped_tools)
        return target

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        """Append one ``ApiCallRecord`` per ``raw_responses`` entry that has usage data."""
        raw_responses = getattr(raw_result, "raw_responses", None) or []
        for i, raw in enumerate(raw_responses, start=1):
            usage = getattr(raw, "usage", None)
            if usage is None:
                continue
            metrics.api_calls.append(
                ApiCallRecord(
                    call_number=i,
                    input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                    total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                )
            )

    def extract_output(self, raw_result: Any) -> str:
        """Return ``raw_result.final_output`` coerced to a string."""
        out = getattr(raw_result, "final_output", "")
        return str(out) if out is not None else ""


def _wrap_function_tool(tool: FunctionTool, runner: ToolArgsRunner) -> FunctionTool:
    """Return a copy of ``tool`` whose ``on_invoke_tool`` runs the processor chain.

    The shim parses the SDK's raw JSON input, hands the dict to ``runner``, then
    re-serialises the mutated dict and delegates to the original
    ``on_invoke_tool``. Empty input is treated as an empty dict to mirror the
    SDK's behaviour; malformed JSON is forwarded unchanged so the SDK can raise
    its standard ``ModelBehaviorError`` instead of having the shim swallow it.
    """
    original_invoke = tool.on_invoke_tool
    wrapped = copy.copy(tool)

    async def _argox_invoke(ctx: Any, raw_input: str) -> Any:
        if raw_input:
            try:
                parsed = json.loads(raw_input)
            except json.JSONDecodeError:
                # Let the SDK's own JSON diagnostics fire — passing the raw
                # string through preserves the original error message.
                return await original_invoke(ctx, raw_input)
            if not isinstance(parsed, dict):
                return await original_invoke(ctx, raw_input)
        else:
            parsed = {}

        tool_name = getattr(ctx, "tool_name", None) or tool.name
        mutated = await runner(tool_name, parsed)
        return await original_invoke(ctx, json.dumps(mutated))

    wrapped.on_invoke_tool = _argox_invoke
    return wrapped
