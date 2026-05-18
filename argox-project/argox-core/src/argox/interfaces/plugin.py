"""
IFACE-01 — ArgoxPlugin
======================
Contract that every framework plugin (OpenAI, LangChain, etc.) must implement.

A plugin is responsible for three things:
  1. Injecting monitoring into the framework object (instrument).
  2. Extracting token information from the raw result (extract_tokens).
  3. Returning the final output as a plain string (extract_output).

The plugin does NOT instantiate metrics or apply policies — that is the
responsibility of ArgoxManager. The plugin only knows how to talk to its framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

# Deferred import to avoid circular dependency at import time.
# AgentRunMetrics is defined in argox.core.state, which does not depend on interfaces.
from argox.core.state import AgentRunMetrics


ToolArgsRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
"""Callable contract for tool-argument mutation hooks.

The Manager builds an instance of this callable on every run and passes it to
``ArgoxPlugin.instrument``. Plugins invoke it from inside their tool-execution
shim with ``(tool_name, args_dict)``. The Manager runs the registered
``ArgoxProcessor.process_tool_args`` chain (honouring per-processor strict
semantics and emitting span events) and returns the mutated args dict that the
plugin must forward to the framework-native tool implementation.
"""


class ArgoxPlugin(ABC):
    """
    Abstract interface for framework plugins.

    Each integration (OpenAI Agents SDK, LangChain, Anthropic…) implements
    this class in its own installable package (`argox-plugin-<framework>`).

    Minimal implementation example::

        class MyFrameworkPlugin(ArgoxPlugin):

            @property
            def name(self) -> str:
                return "my_framework"

            def instrument(self, target, metrics, tool_args_runner=None):
                # Inject framework hooks/callbacks here
                target.on_tool_call = lambda t: metrics.tools_called.append(...)
                return target

            def extract_tokens(self, raw_result, metrics):
                for call in raw_result.usage_records:
                    metrics.api_calls.append(
                        ApiCallRecord(
                            call_number=len(metrics.api_calls) + 1,
                            input_tokens=call.input,
                            output_tokens=call.output,
                            total_tokens=call.total,
                        )
                    )

            def extract_output(self, raw_result) -> str:
                return raw_result.text
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique plugin identifier, lowercase, no spaces.

        Examples: ``"openai"``, ``"langchain"``, ``"anthropic"``.
        ArgoxManager uses this name as the registration key.
        """
        ...

    # ------------------------------------------------------------------
    # Execution lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def instrument(
        self,
        target: Any,
        metrics: AgentRunMetrics,
        tool_args_runner: ToolArgsRunner | None = None,
    ) -> Any:
        """
        Injects monitoring into the agent or runner of the framework.

        This method is called BEFORE the agent executes. It must configure
        the framework's mechanisms (hooks, callbacks, middleware…) so that
        events are recorded in ``metrics`` during execution. When
        ``tool_args_runner`` is provided, the plugin should additionally
        intercept each tool invocation and await
        ``tool_args_runner(tool_name, args)`` before delegating to the
        framework-native tool implementation. The Manager owns the processor
        chain behind that callable; plugins must not look at the processor
        list directly.

        Args:
            target:  The framework object to instrument (Agent, Chain…).
                     The concrete type depends on the framework; the plugin knows it.
            metrics: The AgentRunMetrics instance that will accumulate data
                     for this execution. The plugin writes to it directly.
            tool_args_runner: Optional callable that runs the registered
                     processor chain against a single tool call's arguments
                     and returns the mutated dict. ``None`` means the plugin
                     should not intercept tool args (no processors registered
                     or older Manager).

        Returns:
            The instrumented ``target``. Can be the same mutated object
            or a wrapper, depending on what the framework allows.
        """
        ...

    @abstractmethod
    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        """
        Extracts token usage from the raw result and persists it in metrics.

        This method is called AFTER the agent has finished executing.
        The ``raw_result`` is the object returned by the framework (RunResult,
        AIMessage, etc.); the plugin knows how to read it.

        Args:
            raw_result: Raw result as returned by the framework.
            metrics:    AgentRunMetrics instance where consumption records
                        should be appended (``metrics.api_calls``).

        Note:
            This method returns nothing. It writes directly into ``metrics``.
        """
        ...

    @abstractmethod
    def extract_output(self, raw_result: Any) -> str:
        """
        Returns the final agent output as a plain string.

        Each framework wraps its response differently. This method normalizes
        that difference so ArgoxManager always receives a str.

        Args:
            raw_result: Raw result as returned by the framework.

        Returns:
            The final text response from the agent.
        """
        ...
