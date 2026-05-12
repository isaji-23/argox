"""Tests for the public ``@argox.monitor`` decorator."""

from __future__ import annotations

import warnings
from typing import Any

import pytest

import argox
from argox.core.decorator import monitor
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient, PolicyResult


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, text: str = "ok", input_tokens: int = 3, output_tokens: int = 4) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens


class _FakeAgent:
    def __init__(self, name: str = "agent-a", tools: list | None = None) -> None:
        self.name = name
        self.tools = tools if tools is not None else []


class _RecordingPlugin(ArgoxPlugin):
    @property
    def name(self) -> str:
        return "recording"

    def instrument(self, target: Any, metrics: AgentRunMetrics) -> Any:
        return target

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        if isinstance(raw_result, _FakeResult):
            metrics.api_calls.append(
                ApiCallRecord(
                    call_number=1,
                    input_tokens=raw_result.input_tokens,
                    output_tokens=raw_result.output_tokens,
                    total_tokens=raw_result.total_tokens,
                )
            )

    def extract_output(self, raw_result: Any) -> str:
        return raw_result.text if isinstance(raw_result, _FakeResult) else str(raw_result)


class _CapturingExporter(ExporterBase):
    def __init__(self) -> None:
        self.exports: list[AgentRunMetrics] = []

    def export(self, metrics: AgentRunMetrics) -> None:
        self.exports.append(metrics)


class _BlockingPolicy(PolicyClient):
    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.block(reason="blocked", rule_id="R-IN")

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.ok()


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_monitor_exposed_on_argox_namespace(self) -> None:
        assert argox.monitor is monitor


# ---------------------------------------------------------------------------
# Wrapping sync and async callables
# ---------------------------------------------------------------------------


class TestSyncWrapping:
    def test_sync_wrap_returns_final_output(self) -> None:
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent)
        def run(prompt: str) -> _FakeResult:
            return _FakeResult(text=f"sync:{prompt}")

        assert run("hello") == "sync:hello"

    def test_sync_wrap_routes_through_manager_exporter(self) -> None:
        exp = _CapturingExporter()
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent, exporters=[exp])
        def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        run("hi")
        assert len(exp.exports) == 1
        assert exp.exports[0].agent_name == "agent-a"
        assert exp.exports[0].success is True


class TestAsyncWrapping:
    @pytest.mark.asyncio
    async def test_async_wrap_returns_final_output(self) -> None:
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent)
        async def run(prompt: str) -> _FakeResult:
            return _FakeResult(text=f"async:{prompt}")

        assert await run("hello") == "async:hello"

    @pytest.mark.asyncio
    async def test_async_wrap_exporter_invoked(self) -> None:
        exp = _CapturingExporter()
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent, exporters=[exp])
        async def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        await run("x")
        assert len(exp.exports) == 1


# ---------------------------------------------------------------------------
# Agent resolution
# ---------------------------------------------------------------------------


class TestAgentResolution:
    def test_resolves_agent_from_closure(self) -> None:
        agent = _FakeAgent(name="closure-agent")

        @monitor(plugin=_RecordingPlugin())
        def run(prompt: str) -> _FakeResult:
            assert agent.name == "closure-agent"
            return _FakeResult(text="ok")

        assert run("hi") == "ok"

    def test_missing_agent_raises(self) -> None:
        @monitor(plugin=_RecordingPlugin())
        def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        with pytest.raises(LookupError, match="could not locate an agent"):
            run("hi")

    def test_explicit_agent_overrides_closure(self) -> None:
        closure_agent = _FakeAgent(name="closure-agent")  # noqa: F841 - exercised in closure
        explicit = _FakeAgent(name="explicit-agent")
        exp = _CapturingExporter()

        @monitor(plugin=_RecordingPlugin(), agent=explicit, exporters=[exp])
        def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        run("hi")
        assert exp.exports[0].agent_name == "explicit-agent"


# ---------------------------------------------------------------------------
# Policy + shared manager
# ---------------------------------------------------------------------------


class TestPolicyAndManager:
    def test_policy_blocks_input(self) -> None:
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent, policy=_BlockingPolicy())
        def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        with pytest.raises(PermissionError, match="POLICY:R-IN"):
            run("anything")

    def test_no_policy_runs_clean(self) -> None:
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent)
        def run(prompt: str) -> _FakeResult:
            return _FakeResult(text="clean")

        assert run("hi") == "clean"

    def test_multiple_decorations_share_manager(self) -> None:
        agent = _FakeAgent()
        decorate = monitor(plugin=_RecordingPlugin(), agent=agent)

        @decorate
        def run_a(prompt: str) -> _FakeResult:
            return _FakeResult(text="a")

        @decorate
        def run_b(prompt: str) -> _FakeResult:
            return _FakeResult(text="b")

        assert run_a.argox_manager is run_b.argox_manager

    def test_separate_factories_have_separate_managers(self) -> None:
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent)
        def run_a(prompt: str) -> _FakeResult:
            return _FakeResult()

        @monitor(plugin=_RecordingPlugin(), agent=agent)
        def run_b(prompt: str) -> _FakeResult:
            return _FakeResult()

        assert run_a.argox_manager is not run_b.argox_manager


# ---------------------------------------------------------------------------
# Plugin entry-point lookup
# ---------------------------------------------------------------------------


class _WrappingAgent:
    """Wrapper used by plugins that do not mutate the target in place."""

    def __init__(self, inner: _FakeAgent) -> None:
        self.inner = inner
        self.name = inner.name
        self.tools = inner.tools


class _WrappingPlugin(_RecordingPlugin):
    """Plugin that returns a brand-new wrapper instead of mutating."""

    @property
    def name(self) -> str:
        return "wrapping"

    def instrument(self, target: Any, metrics: AgentRunMetrics) -> Any:
        return _WrappingAgent(target)


class TestAgentInjection:
    def test_agent_param_receives_instrumented_agent(self) -> None:
        agent = _FakeAgent()
        plugin = _WrappingPlugin()
        seen: list[Any] = []

        @monitor(plugin=plugin, agent=agent)
        def run(agent: Any, prompt: str) -> _FakeResult:
            seen.append(agent)
            return _FakeResult(text="ok")

        assert run("hi") == "ok"
        assert len(seen) == 1
        assert isinstance(seen[0], _WrappingAgent)
        assert seen[0].inner is agent

    def test_agent_param_with_async_function(self) -> None:
        import asyncio as _asyncio

        agent = _FakeAgent()
        plugin = _WrappingPlugin()
        seen: list[Any] = []

        @monitor(plugin=plugin, agent=agent)
        async def run(agent: Any, prompt: str) -> _FakeResult:
            seen.append(agent)
            return _FakeResult(text="ok")

        assert _asyncio.run(run("hi")) == "ok"
        assert isinstance(seen[0], _WrappingAgent)

    def test_warns_when_plugin_wraps_and_signature_has_no_agent(self) -> None:
        agent = _FakeAgent()
        plugin = _WrappingPlugin()

        @monitor(plugin=plugin, agent=agent)
        def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        with pytest.warns(RuntimeWarning, match="instrumentation lost"):
            run("hi")

    def test_no_warning_when_plugin_mutates_in_place(self) -> None:
        agent = _FakeAgent()

        @monitor(plugin=_RecordingPlugin(), agent=agent)
        def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            run("hi")  # must not raise — no warning expected

    def test_agent_param_does_not_warn_even_when_wrapping(self) -> None:
        agent = _FakeAgent()
        plugin = _WrappingPlugin()

        @monitor(plugin=plugin, agent=agent)
        def run(agent: Any, prompt: str) -> _FakeResult:
            return _FakeResult()

        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            run("hi")


class TestMethodSupport:
    def test_instance_method_resolves_prompt_after_self(self) -> None:
        agent = _FakeAgent()

        class Service:
            @monitor(plugin=_RecordingPlugin(), agent=agent)
            def run(self, prompt: str) -> _FakeResult:
                return _FakeResult(text=f"method:{prompt}")

        assert Service().run("hi") == "method:hi"

    def test_instance_method_with_agent_injection(self) -> None:
        agent = _FakeAgent()
        plugin = _WrappingPlugin()
        seen: list[Any] = []

        class Service:
            @monitor(plugin=plugin, agent=agent)
            def run(self, agent: Any, prompt: str) -> _FakeResult:
                seen.append((self, agent))
                return _FakeResult(text="ok")

        service = Service()
        assert service.run("hi") == "ok"
        assert seen[0][0] is service
        assert isinstance(seen[0][1], _WrappingAgent)

    def test_classmethod_resolves_prompt_after_cls(self) -> None:
        agent = _FakeAgent()

        class Service:
            @classmethod
            @monitor(plugin=_RecordingPlugin(), agent=agent)
            def run(cls, prompt: str) -> _FakeResult:
                return _FakeResult(text=f"cls:{prompt}")

        assert Service.run("hi") == "cls:hi"


class TestPluginLookup:
    def test_unknown_plugin_name_raises(self) -> None:
        with pytest.raises(LookupError, match="No Argox plugin registered"):
            monitor(plugin="definitely-not-installed")

    def test_plugin_instance_passes_through(self) -> None:
        plugin = _RecordingPlugin()
        agent = _FakeAgent()

        @monitor(plugin=plugin, agent=agent)
        def run(prompt: str) -> _FakeResult:
            return _FakeResult()

        assert run.argox_manager._plugins["recording"] is plugin
