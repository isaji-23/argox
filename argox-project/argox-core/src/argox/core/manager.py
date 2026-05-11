"""ArgoxManager — central SDK entry point orchestrating the agent execution lifecycle."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from argox.core.context import RunContext
from argox.core.state import AgentRunMetrics
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient
from argox.interfaces.processor import ArgoxProcessor
from argox.semconv.attributes import (
    ARGOX_POLICY_DECISION,
    ARGOX_POLICY_RULE_ID,
    ARGOX_PROCESSOR_APPLIED,
    ARGOX_PROCESSOR_NAME,
    ARGOX_PROCESSOR_PHASE,
    ARGOX_PROCESSOR_STRICT,
    ARGOX_RUN_BLOCKED_TOOLS,
    EVENT_PROCESSOR_APPLIED,
    EVENT_PROCESSOR_ERROR,
    SPAN_AGENT_RUN,
)

_GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"


class ArgoxManager:
    """Orchestrates plugin, exporter, processor, and policy lifecycles for agent runs.

    Args:
        policy: Optional policy client. When None, all policy checks pass silently.
    """

    def __init__(self, policy: PolicyClient | None = None) -> None:
        self._policy = policy
        self._plugins: dict[str, ArgoxPlugin] = {}
        self._exporters: list[ExporterBase] = []
        self._processors: list[tuple[ArgoxProcessor, bool]] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_plugin(self, plugin: ArgoxPlugin) -> None:
        """Register a framework plugin by its name."""
        self._plugins[plugin.name] = plugin

    def register_exporter(self, exporter: ExporterBase) -> None:
        """Append an exporter to the export chain."""
        self._exporters.append(exporter)

    def register_processor(self, processor: ArgoxProcessor, strict: bool = False) -> None:
        """Append a processor to the transformation pipeline.

        Processors run in registration order on every supported phase
        (``input``, ``output``). Failure semantics are configured per-processor:

        Args:
            processor: The processor instance to add.
            strict: If True, a raised exception aborts the run (fail-closed).
                    If False (default), the failure is recorded as a span event
                    and the pipeline continues with the value the processor
                    received (fail-open).
        """
        self._processors.append((processor, strict))

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

        The whole call is wrapped in a single OTel span (``argox.agent.run``)
        carrying processor events, token usage, and policy decisions so any
        registered ``SpanExporter`` can observe the run.

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
        applied_processors: list[str] = []
        tracer = trace.get_tracer("argox")

        with tracer.start_as_current_span(SPAN_AGENT_RUN) as span:
            try:
                # 1. Process input
                processed_prompt = await self._run_processors(
                    span, ctx, prompt, "input", applied_processors,
                )

                # 2. Input policy
                if self._policy is not None:
                    result = await self._policy.check_input(processed_prompt)
                    if not result.passed:
                        metrics.input_policy_passed = False
                        metrics.policy_violations.append(result.reason)
                        _record_policy_block(span, result.rule_id, "input policy blocked")
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
                    if metrics.tools_blocked:
                        span.set_attribute(
                            ARGOX_RUN_BLOCKED_TOOLS,
                            [t["name"] for t in metrics.tools_blocked],
                        )
                    _apply_tool_filter(agent, metrics.tools_available)
                else:
                    metrics.tools_available.extend(raw_tools)

                # 4. Instrument agent and execute
                instrumented = plugin.instrument(agent, metrics)
                raw_result = await runner(instrumented, processed_prompt)

                # 5. Extract tokens and raw output
                plugin.extract_tokens(raw_result, metrics)
                output = plugin.extract_output(raw_result)

                if metrics.total_input_tokens:
                    span.set_attribute(_GEN_AI_INPUT_TOKENS, metrics.total_input_tokens)
                if metrics.total_output_tokens:
                    span.set_attribute(_GEN_AI_OUTPUT_TOKENS, metrics.total_output_tokens)

                # 6. Process output
                output = await self._run_processors(
                    span, ctx, output, "output", applied_processors,
                )

                # 7. Output policy
                if self._policy is not None:
                    result = await self._policy.check_output(output)
                    if not result.passed:
                        metrics.output_policy_passed = False
                        metrics.policy_violations.append(result.reason)
                        _record_policy_block(span, result.rule_id, "output policy blocked")
                        raise PermissionError(f"[POLICY:{result.rule_id}] {result.reason}")

                metrics.final_output = output
                metrics.success = True

                return output

            finally:
                if applied_processors:
                    span.set_attribute(
                        ARGOX_PROCESSOR_APPLIED,
                        list(dict.fromkeys(applied_processors)),
                    )
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

    async def _run_processors(
        self,
        span: Span,
        ctx: RunContext,
        value: str,
        phase: str,
        applied: list[str],
    ) -> str:
        """Run every registered processor for ``phase`` with per-processor strictness.

        On success, emits an ``argox.processor.applied`` span event and records
        the processor's class name in ``applied``.

        On failure: in strict mode the exception propagates and the run span is
        marked ERROR; in fail-open mode the failure is captured as an
        ``argox.processor.error`` span event and ``value`` is forwarded
        unchanged to the next processor.
        """
        method_name = f"process_{phase}"
        for processor, strict in self._processors:
            name = type(processor).__name__
            try:
                value = await getattr(processor, method_name)(value, ctx)
            except Exception as exc:
                span.add_event(
                    EVENT_PROCESSOR_ERROR,
                    {
                        ARGOX_PROCESSOR_NAME: name,
                        ARGOX_PROCESSOR_PHASE: phase,
                        ARGOX_PROCESSOR_STRICT: strict,
                        "exception.type": type(exc).__name__,
                        "exception.message": str(exc),
                    },
                )
                if strict:
                    span.set_status(
                        Status(StatusCode.ERROR, f"processor {name} failed in {phase} phase")
                    )
                    raise
                continue

            span.add_event(
                EVENT_PROCESSOR_APPLIED,
                {ARGOX_PROCESSOR_NAME: name, ARGOX_PROCESSOR_PHASE: phase},
            )
            applied.append(name)
        return value


def _record_policy_block(span: Span, rule_id: str, message: str) -> None:
    """Attach policy-block attributes and ERROR status to the run span."""
    span.set_attribute(ARGOX_POLICY_DECISION, "block")
    if rule_id:
        span.set_attribute(ARGOX_POLICY_RULE_ID, rule_id)
    span.set_status(Status(StatusCode.ERROR, message))


def _extract_tool_names(agent: Any) -> list[str]:
    """Pull tool names from an agent object that exposes a ``.tools`` attribute."""
    raw = getattr(agent, "tools", [])
    names: list[str] = []
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
