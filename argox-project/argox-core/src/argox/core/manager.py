"""ArgoxManager — central SDK entry point orchestrating the agent execution lifecycle."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from argox.core.context import RunContext
from argox.core.state import AgentRunMetrics
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient
from argox.interfaces.processor import ArgoxProcessor


class ArgoxManager:
    """Orchestrates plugin, exporter, processor, and policy lifecycles for agent runs.

    Args:
        policy: Optional policy client. When None, all policy checks pass silently.
    """

    def __init__(self, policy: PolicyClient | None = None) -> None:
        self._policy = policy
        self._plugins: dict[str, ArgoxPlugin] = {}
        self._exporters: list[ExporterBase] = []
        self._processors: list[ArgoxProcessor] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_plugin(self, plugin: ArgoxPlugin) -> None:
        """Register a framework plugin by its name."""
        self._plugins[plugin.name] = plugin

    def register_exporter(self, exporter: ExporterBase) -> None:
        """Append an exporter to the export chain."""
        self._exporters.append(exporter)

    def register_processor(self, processor: ArgoxProcessor) -> None:
        """Append a processor to the transformation pipeline."""
        self._processors.append(processor)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(
        self,
        agent: Any,
        prompt: str,
        plugin_name: str,
        runner: Callable[[Any, str], Awaitable[Any]],
        tools: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Execute a full agent run with policy checks, processors, and export.

        Args:
            agent: Framework agent object passed to the plugin for instrumentation.
            prompt: Raw user prompt.
            plugin_name: Key of a registered plugin to use for this run.
            runner: Coroutine callable ``(instrumented_agent, processed_prompt) -> raw_result``.
            tools: Tool names to evaluate against policy. Falls back to ``agent.tools``
                   if the attribute exists and items expose a ``.name`` field.
            metadata: Extra key-value pairs attached to the RunContext.

        Returns:
            Final output string after output policy and processor transformations.

        Raises:
            KeyError: If ``plugin_name`` is not registered.
            PermissionError: If input or output policy blocks execution.
        """
        plugin = self._plugins[plugin_name]
        metrics = AgentRunMetrics(agent_name=agent.name if hasattr(agent, "name") else plugin_name)
        metrics.prompt = prompt
        ctx = RunContext(run_id=metrics.run_id, agent_name=metrics.agent_name, metadata=metadata or {})

        original_tools = _snapshot_tools(agent)
        try:
            # 1. Process input
            processed_prompt = prompt
            for processor in self._processors:
                processed_prompt = await processor.process_input(processed_prompt, ctx)

            # 2. Input policy
            if self._policy is not None:
                result = await self._policy.check_input(processed_prompt)
                if not result.passed:
                    metrics.input_policy_passed = False
                    metrics.policy_violations.append(result.reason)
                    raise PermissionError(f"[POLICY:{result.rule_id}] {result.reason}")

            # 3. Filter tools via policy
            raw_tools = _extract_tool_names(agent) if tools is None else tools
            if self._policy is not None and raw_tools:
                for tool_name in raw_tools:
                    tool_result = await self._policy.is_tool_allowed(tool_name)
                    if tool_result.passed:
                        metrics.tools_available.append(tool_name)
                    else:
                        metrics.tools_blocked.append({"name": tool_name, "reason": tool_result.reason})
                # Best-effort enforcement: rewrite agent.tools to the allowed set so the
                # framework cannot access blocked tools at runtime. Relies on the framework
                # reading agent.tools at call time rather than at construction.
                _apply_tool_filter(agent, metrics.tools_available)
            else:
                metrics.tools_available.extend(raw_tools)

            # 4. Instrument agent and execute
            instrumented = plugin.instrument(agent, metrics)
            raw_result = await runner(instrumented, processed_prompt)

            # 5. Extract tokens and raw output
            plugin.extract_tokens(raw_result, metrics)
            output = plugin.extract_output(raw_result)

            # 6. Process output
            for processor in self._processors:
                output = await processor.process_output(output, ctx)

            # 7. Output policy
            if self._policy is not None:
                result = await self._policy.check_output(output)
                if not result.passed:
                    metrics.output_policy_passed = False
                    metrics.policy_violations.append(result.reason)
                    raise PermissionError(f"[POLICY:{result.rule_id}] {result.reason}")

            metrics.final_output = output
            metrics.success = True
            return output

        finally:
            _restore_tools(agent, original_tools)
            if metrics.end_time is None:
                metrics.end_time = time.time()
            for exporter in self._exporters:
                try:
                    exporter.export(metrics)
                except Exception as exc:
                    metrics.exporter_errors.append(
                        f"{type(exporter).__name__}: {exc}"
                    )


def _extract_tool_names(agent: Any) -> list[str]:
    """Pull tool names from an agent object that exposes a ``.tools`` attribute."""
    raw = getattr(agent, "tools", [])
    names = []
    for tool in raw:
        if hasattr(tool, "name"):
            names.append(tool.name)
        elif isinstance(tool, str):
            names.append(tool)
    return names


def _snapshot_tools(agent: Any) -> list | None:
    """Return a shallow copy of agent.tools, or None if the attribute is absent."""
    if not hasattr(agent, "tools"):
        return None
    return list(agent.tools)


def _restore_tools(agent: Any, snapshot: list | None) -> None:
    """Restore agent.tools to its pre-run state."""
    if snapshot is not None:
        agent.tools = snapshot


def _apply_tool_filter(agent: Any, allowed: list[str]) -> None:
    """Rewrite agent.tools in-place to only the allowed set.

    No-op if the agent has no ``.tools`` attribute. Enforcement is best-effort:
    frameworks that snapshot tools at construction will not be affected.
    """
    if not hasattr(agent, "tools"):
        return
    allowed_set = set(allowed)
    original = agent.tools
    if all(isinstance(t, str) for t in original):
        agent.tools = [t for t in original if t in allowed_set]
    else:
        agent.tools = [t for t in original if getattr(t, "name", None) in allowed_set]
