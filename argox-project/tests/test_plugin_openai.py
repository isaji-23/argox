"""Tests for ArgoxOpenAIPlugin (PLUGIN-01, PLUGIN-02)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from agents import Agent, function_tool
from agents.tool import FunctionTool

from argox.core.context import RunContext
from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics
from argox.interfaces.processor import ArgoxProcessor
from argox_openai import ArgoxOpenAIPlugin
from argox_openai.plugin import _ArgoxAgentHooks, _wrap_function_tool


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


# ---------------------------------------------------------------------------
# PLUGIN-02 — tool argument processor wiring
# ---------------------------------------------------------------------------


@function_tool
def _echo_tool(text: str) -> str:
    """Return whatever text the caller sends."""
    return text


@function_tool
def _add_tool(x: int, y: int) -> int:
    """Add two integers."""
    return x + y


class _RedactingProcessor(ArgoxProcessor):
    """Injects ``redacted=True`` into every tool args dict."""

    async def process_input(self, text: str, ctx: RunContext) -> str:
        return text

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        return {**args, "redacted": True}

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text


class TestWrapFunctionTool:
    def test_wrap_returns_a_copy_not_the_original(self):
        async def runner(name, args):
            return args

        wrapped = _wrap_function_tool(_echo_tool, runner)
        assert isinstance(wrapped, FunctionTool)
        assert wrapped is not _echo_tool
        assert wrapped.on_invoke_tool is not _echo_tool.on_invoke_tool

    def test_wrap_leaves_original_on_invoke_tool_untouched(self):
        original_invoke = _echo_tool.on_invoke_tool

        async def runner(name, args):
            return args

        _wrap_function_tool(_echo_tool, runner)
        assert _echo_tool.on_invoke_tool is original_invoke

    @pytest.mark.asyncio
    async def test_shim_passes_mutated_args_to_original_invoker(self):
        seen_inputs: list[str] = []

        async def recording_original(ctx, raw_input):
            seen_inputs.append(raw_input)
            return "ok"

        tool = FunctionTool(
            name="t",
            description="d",
            params_json_schema={
                "type": "object", "properties": {},
                "required": [], "additionalProperties": False,
            },
            on_invoke_tool=recording_original,
            strict_json_schema=False,
        )

        async def runner(name, args):
            return {**args, "redacted": True}

        wrapped = _wrap_function_tool(tool, runner)
        ctx = SimpleNamespace(tool_name="t")
        await wrapped.on_invoke_tool(ctx, json.dumps({"text": "hi"}))
        assert seen_inputs == [json.dumps({"text": "hi", "redacted": True})]
        # Original tool is untouched.
        assert tool.on_invoke_tool is recording_original

    @pytest.mark.asyncio
    async def test_shim_treats_empty_input_as_empty_dict(self):
        received_runner_args: list[dict] = []
        received_raw: list[str] = []

        async def recording_original(ctx, raw_input):
            received_raw.append(raw_input)
            return "ok"

        async def runner(name, args):
            received_runner_args.append(args)
            return args

        tool = FunctionTool(
            name="t",
            description="d",
            params_json_schema={
                "type": "object", "properties": {},
                "required": [], "additionalProperties": False,
            },
            on_invoke_tool=recording_original,
            strict_json_schema=False,
        )
        wrapped = _wrap_function_tool(tool, runner)
        ctx = SimpleNamespace(tool_name="t")
        await wrapped.on_invoke_tool(ctx, "")
        assert received_runner_args == [{}]
        assert received_raw == [json.dumps({})]

    @pytest.mark.asyncio
    async def test_shim_forwards_malformed_json_unchanged(self):
        runner_calls: list = []
        forwarded: list[str] = []

        async def recording_original(ctx, raw_input):
            forwarded.append(raw_input)
            return "ok"

        async def runner(name, args):
            runner_calls.append((name, args))
            return args

        tool = FunctionTool(
            name="t",
            description="d",
            params_json_schema={
                "type": "object", "properties": {},
                "required": [], "additionalProperties": False,
            },
            on_invoke_tool=recording_original,
            strict_json_schema=False,
        )
        wrapped = _wrap_function_tool(tool, runner)
        ctx = SimpleNamespace(tool_name="t")
        await wrapped.on_invoke_tool(ctx, "not json")
        # Runner must NOT have been called; raw input passed straight through
        # so the SDK's own JSON diagnostics can fire downstream.
        assert runner_calls == []
        assert forwarded == ["not json"]

    @pytest.mark.asyncio
    async def test_shim_forwards_non_object_json_unchanged(self):
        runner_calls: list = []
        forwarded: list[str] = []

        async def recording_original(ctx, raw_input):
            forwarded.append(raw_input)
            return "ok"

        async def runner(name, args):
            runner_calls.append((name, args))
            return args

        tool = FunctionTool(
            name="t",
            description="d",
            params_json_schema={
                "type": "object", "properties": {},
                "required": [], "additionalProperties": False,
            },
            on_invoke_tool=recording_original,
            strict_json_schema=False,
        )
        wrapped = _wrap_function_tool(tool, runner)
        ctx = SimpleNamespace(tool_name="t")
        await wrapped.on_invoke_tool(ctx, "[1, 2, 3]")
        assert runner_calls == []
        assert forwarded == ["[1, 2, 3]"]


class TestInstrumentWrapsTools:
    def test_instrument_skips_wrapping_when_runner_is_none(self):
        agent = _make_agent()
        object.__setattr__(agent, "tools", [_echo_tool])
        plugin = ArgoxOpenAIPlugin()
        plugin.instrument(agent, AgentRunMetrics(agent_name="t"))
        assert agent.tools == [_echo_tool]  # untouched, same instance

    def test_instrument_wraps_function_tools_when_runner_is_provided(self):
        agent = _make_agent()
        object.__setattr__(agent, "tools", [_echo_tool, _add_tool])

        async def runner(name, args):
            return args

        plugin = ArgoxOpenAIPlugin()
        plugin.instrument(agent, AgentRunMetrics(agent_name="t"), tool_args_runner=runner)
        assert all(isinstance(t, FunctionTool) for t in agent.tools)
        # New list with new instances — originals untouched.
        assert agent.tools[0] is not _echo_tool
        assert agent.tools[1] is not _add_tool
        # Names preserved.
        assert {t.name for t in agent.tools} == {_echo_tool.name, _add_tool.name}

    def test_instrument_passes_through_non_function_tools(self):
        agent = _make_agent()
        sentinel = SimpleNamespace(name="hosted", _kind="hosted")  # not a FunctionTool
        object.__setattr__(agent, "tools", [_echo_tool, sentinel])

        async def runner(name, args):
            return args

        plugin = ArgoxOpenAIPlugin()
        plugin.instrument(agent, AgentRunMetrics(agent_name="t"), tool_args_runner=runner)
        # Non-FunctionTool was passed through identically.
        assert agent.tools[1] is sentinel

    def test_instrument_no_op_when_agent_has_no_tools_attribute(self):
        class _Agentless:
            name = "x"

        async def runner(name, args):
            return args

        target = _Agentless()
        ArgoxOpenAIPlugin().instrument(
            target, AgentRunMetrics(agent_name="t"), tool_args_runner=runner,
        )  # should not raise


def _make_recording_function_tool(name: str, sink: list[str]) -> FunctionTool:
    """Build a FunctionTool whose on_invoke_tool records the raw JSON it receives."""

    async def _record(ctx: Any, raw_input: str) -> str:
        sink.append(raw_input)
        return "ok"

    return FunctionTool(
        name=name,
        description="recording stub",
        params_json_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        on_invoke_tool=_record,
        strict_json_schema=False,
    )


class TestProcessorChainReachesTools:
    @pytest.mark.asyncio
    async def test_redactor_mutates_args_before_original_invoker_runs(self):
        """End-to-end through Manager → plugin shim → recording original."""
        sink: list[str] = []
        recording_tool = _make_recording_function_tool("record", sink)

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            ctx = SimpleNamespace(tool_name=tool.name)
            await tool.on_invoke_tool(ctx, json.dumps({"text": "hello"}))
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        mgr.register_processor(_RedactingProcessor())
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)

        assert sink == [json.dumps({"text": "hello", "redacted": True})]
        # Original tool's on_invoke_tool was never mutated; only the wrapped copy was.
        # (Sanity: the agent.tools list was restored to [recording_tool] in finally.)
        assert agent.tools == [recording_tool]

    @pytest.mark.asyncio
    async def test_strict_tool_args_failure_aborts_before_tool_runs(self):
        sink: list[str] = []
        recording_tool = _make_recording_function_tool("record", sink)

        class _Boom(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                raise RuntimeError("strict boom")
            async def process_output(self, text, ctx): return text

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            ctx = SimpleNamespace(tool_name=tool.name)
            await tool.on_invoke_tool(ctx, json.dumps({"text": "x"}))
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        mgr.register_processor(_Boom(), strict=True)
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        with pytest.raises(RuntimeError, match="strict boom"):
            await mgr.run(agent, "hi", "openai", fake_runner)
        # The recording original was never reached.
        assert sink == []

    @pytest.mark.asyncio
    async def test_fail_open_tool_args_lets_original_args_reach_tool(self):
        sink: list[str] = []
        recording_tool = _make_recording_function_tool("record", sink)

        class _Boom(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                raise RuntimeError("fail-open boom")
            async def process_output(self, text, ctx): return text

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            ctx = SimpleNamespace(tool_name=tool.name)
            await tool.on_invoke_tool(ctx, json.dumps({"text": "x"}))
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        mgr.register_processor(_Boom())  # default strict=False
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)
        # Original args (pre-processor) reached the recording tool.
        assert sink == [json.dumps({"text": "x"})]
