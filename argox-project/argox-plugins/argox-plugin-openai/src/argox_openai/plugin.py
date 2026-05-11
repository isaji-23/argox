"""ArgoxOpenAIPlugin — integrates the OpenAI Agents SDK with ArgoxManager.

The plugin bridges three responsibilities to the SDK:

- ``instrument``  attaches lifecycle hooks (:class:`_ArgoxAgentHooks`) to the agent so
  tool invocations are recorded into ``AgentRunMetrics.tools_called`` during the run.
- ``extract_tokens`` walks ``RunResult.raw_responses`` and appends one
  :class:`~argox.core.state.ApiCallRecord` per LLM call observed.
- ``extract_output`` returns ``RunResult.final_output`` as a plain string.

The ``Agent`` class from openai-agents is a Pydantic-like model whose fields are
not freely assignable, so the plugin uses ``object.__setattr__`` to write the
``hooks`` attribute. This matches the pattern used in the project's reference
implementation.
"""

from __future__ import annotations

import time
from typing import Any

from agents import Agent
from agents.lifecycle import AgentHooks, RunContextWrapper

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord
from argox.interfaces.plugin import ArgoxPlugin


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
    """

    @property
    def name(self) -> str:
        return "openai"

    def instrument(self, target: Agent, metrics: AgentRunMetrics) -> Agent:
        """Attach Argox lifecycle hooks to the agent.

        Uses ``object.__setattr__`` to bypass Pydantic field validation on
        ``Agent``.
        """
        object.__setattr__(target, "hooks", _ArgoxAgentHooks(metrics))
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
