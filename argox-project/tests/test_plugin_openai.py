"""Tests for ArgoxOpenAIPlugin (PLUGIN-01)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from agents import Agent

from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics
from argox_openai import ArgoxOpenAIPlugin
from argox_openai.plugin import _ArgoxAgentHooks


def _make_agent() -> Agent:
    """Construct a minimal Agent that does not hit any API."""
    return Agent(name="test-agent", instructions="test", model="gpt-4o-mini")


def _make_usage(input_tokens: int, output_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


def _make_run_result(final_output: str, *usages: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        final_output=final_output,
        raw_responses=[SimpleNamespace(usage=u) for u in usages],
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestIdentity:
    def test_name_is_openai(self):
        assert ArgoxOpenAIPlugin().name == "openai"


# ---------------------------------------------------------------------------
# instrument
# ---------------------------------------------------------------------------


class TestInstrument:
    def test_instrument_attaches_argox_hooks(self):
        agent = _make_agent()
        metrics = AgentRunMetrics(agent_name="test")
        result = ArgoxOpenAIPlugin().instrument(agent, metrics)
        assert isinstance(agent.hooks, _ArgoxAgentHooks)
        assert result is agent

    def test_instrument_replaces_existing_hooks(self):
        agent = _make_agent()
        object.__setattr__(agent, "hooks", object())
        ArgoxOpenAIPlugin().instrument(agent, AgentRunMetrics(agent_name="t"))
        assert isinstance(agent.hooks, _ArgoxAgentHooks)


# ---------------------------------------------------------------------------
# Tool tracking through hooks
# ---------------------------------------------------------------------------


class TestToolTracking:
    @pytest.mark.asyncio
    async def test_on_tool_start_appends_record(self):
        metrics = AgentRunMetrics(agent_name="t")
        hooks = _ArgoxAgentHooks(metrics)
        await hooks.on_tool_start(None, _make_agent(), SimpleNamespace(name="search"))
        assert len(metrics.tools_called) == 1
        assert metrics.tools_called[0].name == "search"
        assert metrics.tools_called[0].end is None

    @pytest.mark.asyncio
    async def test_on_tool_end_completes_latest_open_record(self):
        metrics = AgentRunMetrics(agent_name="t")
        hooks = _ArgoxAgentHooks(metrics)
        tool = SimpleNamespace(name="search")
        await hooks.on_tool_start(None, _make_agent(), tool)
        await hooks.on_tool_end(None, _make_agent(), tool, "found 5 results")
        record = metrics.tools_called[0]
        assert record.end is not None
        assert record.result == "found 5 results"

    @pytest.mark.asyncio
    async def test_on_tool_end_coerces_non_string_result(self):
        metrics = AgentRunMetrics(agent_name="t")
        hooks = _ArgoxAgentHooks(metrics)
        tool = SimpleNamespace(name="calc")
        await hooks.on_tool_start(None, _make_agent(), tool)
        await hooks.on_tool_end(None, _make_agent(), tool, {"value": 42})
        assert metrics.tools_called[0].result == "{'value': 42}"

    @pytest.mark.asyncio
    async def test_on_tool_end_only_closes_open_records_of_same_name(self):
        metrics = AgentRunMetrics(agent_name="t")
        hooks = _ArgoxAgentHooks(metrics)
        tool_a = SimpleNamespace(name="a")
        tool_b = SimpleNamespace(name="b")
        await hooks.on_tool_start(None, _make_agent(), tool_a)
        await hooks.on_tool_start(None, _make_agent(), tool_b)
        await hooks.on_tool_end(None, _make_agent(), tool_b, "b-result")
        assert metrics.tools_called[0].end is None  # "a" still open
        assert metrics.tools_called[1].end is not None  # "b" closed


# ---------------------------------------------------------------------------
# extract_tokens
# ---------------------------------------------------------------------------


class TestExtractTokens:
    def test_appends_one_record_per_raw_response(self):
        result = _make_run_result("hi", _make_usage(10, 20), _make_usage(5, 7))
        metrics = AgentRunMetrics(agent_name="t")
        ArgoxOpenAIPlugin().extract_tokens(result, metrics)
        assert len(metrics.api_calls) == 2
        assert metrics.total_input_tokens == 15
        assert metrics.total_output_tokens == 27
        assert metrics.total_tokens == 42

    def test_call_numbers_are_one_based(self):
        result = _make_run_result("hi", _make_usage(1, 1), _make_usage(1, 1))
        metrics = AgentRunMetrics(agent_name="t")
        ArgoxOpenAIPlugin().extract_tokens(result, metrics)
        assert [c.call_number for c in metrics.api_calls] == [1, 2]

    def test_skips_responses_without_usage(self):
        result = SimpleNamespace(
            final_output="x",
            raw_responses=[SimpleNamespace(usage=None), SimpleNamespace(usage=_make_usage(3, 4))],
        )
        metrics = AgentRunMetrics(agent_name="t")
        ArgoxOpenAIPlugin().extract_tokens(result, metrics)
        assert len(metrics.api_calls) == 1
        assert metrics.api_calls[0].input_tokens == 3

    def test_no_raw_responses_attribute(self):
        metrics = AgentRunMetrics(agent_name="t")
        ArgoxOpenAIPlugin().extract_tokens(SimpleNamespace(), metrics)
        assert metrics.api_calls == []

    def test_empty_raw_responses(self):
        metrics = AgentRunMetrics(agent_name="t")
        ArgoxOpenAIPlugin().extract_tokens(_make_run_result("hi"), metrics)
        assert metrics.api_calls == []


# ---------------------------------------------------------------------------
# extract_output
# ---------------------------------------------------------------------------


class TestExtractOutput:
    def test_returns_string_unchanged(self):
        assert ArgoxOpenAIPlugin().extract_output(SimpleNamespace(final_output="hi")) == "hi"

    def test_handles_none(self):
        assert ArgoxOpenAIPlugin().extract_output(SimpleNamespace(final_output=None)) == ""

    def test_coerces_non_string(self):
        assert ArgoxOpenAIPlugin().extract_output(SimpleNamespace(final_output=42)) == "42"


# ---------------------------------------------------------------------------
# End-to-end through ArgoxManager
# ---------------------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_manager_drives_run_through_plugin(self):
        async def fake_runner(agent: Any, prompt: str):
            return _make_run_result(f"echo: {prompt}", _make_usage(5, 7))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        out = await mgr.run(_make_agent(), "hello", "openai", fake_runner)
        assert out == "echo: hello"

    @pytest.mark.asyncio
    async def test_tool_calls_recorded_through_hooks_during_run(self):
        plugin = ArgoxOpenAIPlugin()
        captured_metrics: list[AgentRunMetrics] = []

        async def fake_runner(agent: Any, prompt: str):
            # Simulate the SDK invoking the registered hooks during the run.
            tool = SimpleNamespace(name="search")
            await agent.hooks.on_tool_start(None, agent, tool)
            await agent.hooks.on_tool_end(None, agent, tool, "found")
            return _make_run_result("done", _make_usage(2, 3))

        class _Capture:
            def export(self, metrics: AgentRunMetrics) -> None:
                captured_metrics.append(metrics)

        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_exporter(_Capture())
        await mgr.run(_make_agent(), "find x", "openai", fake_runner)
        metrics = captured_metrics[0]
        assert len(metrics.tools_called) == 1
        assert metrics.tools_called[0].name == "search"
        assert metrics.tools_called[0].result == "found"
        assert metrics.tools_called[0].end is not None
