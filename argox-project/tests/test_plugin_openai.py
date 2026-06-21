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
from argox_openai.plugin import (
    _ArgoxAgentHooks,
    _resolve_request_model,
    _wrap_function_tool,
)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode


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
# PLUGIN-05 — gen_ai.request.model span attribute
# ---------------------------------------------------------------------------


class TestResolveRequestModel:
    def test_string_is_returned_directly(self):
        assert _resolve_request_model("gpt-4o-mini") == "gpt-4o-mini"

    def test_none_returns_none(self):
        assert _resolve_request_model(None) is None

    def test_empty_string_returns_none(self):
        assert _resolve_request_model("") is None

    def test_model_object_read_via_model_attribute(self):
        assert _resolve_request_model(SimpleNamespace(model="gpt-4o")) == "gpt-4o"

    def test_model_object_without_id_returns_none(self):
        assert _resolve_request_model(SimpleNamespace(other="x")) is None


class TestRequestModelSpanAttribute:
    """``instrument`` tags the active run span with ``gen_ai.request.model``."""

    @staticmethod
    def _instrument_within_span(agent: Agent) -> Any:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("argox.agent.run"):
            ArgoxOpenAIPlugin().instrument(agent, AgentRunMetrics(agent_name="t"))
        return exporter.get_finished_spans()[0]

    def test_sets_request_model_from_agent_model(self):
        span = self._instrument_within_span(_make_agent())
        assert span.attributes["gen_ai.request.model"] == "gpt-4o-mini"

    def test_attribute_absent_when_model_unresolvable(self):
        # No explicit model => Agent.model is None => attribute left unset.
        agent = Agent(name="no-model", instructions="test", model=None)
        span = self._instrument_within_span(agent)
        assert "gen_ai.request.model" not in span.attributes


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
    def test_instrument_wraps_function_tools_even_without_runner(self):
        # PLUGIN-06: wrapping is unconditional so every tool call emits a span,
        # independent of whether processors (and thus a runner) are present.
        agent = _make_agent()
        object.__setattr__(agent, "tools", [_echo_tool])
        plugin = ArgoxOpenAIPlugin()
        plugin.instrument(agent, AgentRunMetrics(agent_name="t"))
        assert agent.tools[0] is not _echo_tool  # wrapped copy
        assert isinstance(agent.tools[0], FunctionTool)
        assert agent.tools[0].name == _echo_tool.name

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
    async def test_no_processors_still_wraps_but_forwards_raw(self):
        """When no processors are registered the Manager passes None as the
        runner. PLUGIN-06: the OpenAI plugin still wraps each FunctionTool (so a
        span is emitted) but, with no runner, forwards the raw JSON byte-for-byte
        with no parse/serialize round-trip."""
        sink: list[str] = []
        recording_tool = _make_recording_function_tool("record", sink)

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            # Wrapped copy, not the original — wrapping is unconditional.
            assert tool is not recording_tool
            ctx = SimpleNamespace(tool_name=tool.name)
            await tool.on_invoke_tool(ctx, '{"text":"hi"}')
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        # No processors registered.
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)
        # Raw JSON reached the tool unchanged — no parse/serialize round-trip.
        assert sink == ['{"text":"hi"}']
        # agent.tools restored to the original after the run.
        assert agent.tools == [recording_tool]

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


# ---------------------------------------------------------------------------
# PLUGIN-06 — per-tool-call child spans
# ---------------------------------------------------------------------------


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    """Install a global SDK TracerProvider (once) and return a fresh exporter.

    The plugin emits tool spans through ``trace.get_tracer("argox")``, which
    resolves to the global provider, so the test installs an SDK provider
    globally and attaches its own in-memory exporter for assertions.
    """
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def _tool_spans(exporter: InMemorySpanExporter) -> list[Any]:
    return [s for s in exporter.get_finished_spans() if s.name.startswith("execute_tool ")]


def _run_span(exporter: InMemorySpanExporter) -> Any:
    return next(s for s in exporter.get_finished_spans() if s.name == "argox.agent.run")


class TestToolCallSpans:
    @pytest.mark.asyncio
    async def test_one_child_span_per_tool_call(self, span_exporter):
        sink: list[str] = []
        recording_tool = _make_recording_function_tool("record", sink)

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            ctx = SimpleNamespace(tool_name=tool.name)
            for _ in range(3):
                await tool.on_invoke_tool(ctx, '{"text":"hi"}')
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)

        spans = _tool_spans(span_exporter)
        assert len(spans) == 3
        for span in spans:
            assert span.name == "execute_tool record"
            assert span.attributes["gen_ai.operation.name"] == "execute_tool"
            assert span.attributes["gen_ai.tool.name"] == "record"

    @pytest.mark.asyncio
    async def test_tool_span_is_child_of_run_span(self, span_exporter):
        recording_tool = _make_recording_function_tool("record", [])

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            ctx = SimpleNamespace(tool_name=tool.name)
            await tool.on_invoke_tool(ctx, '{"text":"hi"}')
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)

        run_span = _run_span(span_exporter)
        tool_span = _tool_spans(span_exporter)[0]
        assert tool_span.parent is not None
        assert tool_span.parent.span_id == run_span.context.span_id
        assert tool_span.context.trace_id == run_span.context.trace_id

    @pytest.mark.asyncio
    async def test_failing_tool_records_exception_and_error_status(self, span_exporter):
        async def _boom(ctx: Any, raw_input: str) -> str:
            raise ValueError("tool exploded")

        failing_tool = FunctionTool(
            name="boom",
            description="always fails",
            params_json_schema={
                "type": "object", "properties": {},
                "required": [], "additionalProperties": False,
            },
            on_invoke_tool=_boom,
            strict_json_schema=False,
        )

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "boom")
            ctx = SimpleNamespace(tool_name=tool.name)
            with pytest.raises(ValueError, match="tool exploded"):
                await tool.on_invoke_tool(ctx, "{}")
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        agent = _make_agent()
        object.__setattr__(agent, "tools", [failing_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)

        tool_span = _tool_spans(span_exporter)[0]
        assert tool_span.status.status_code == StatusCode.ERROR
        assert any(e.name == "exception" for e in tool_span.events)

    @pytest.mark.asyncio
    async def test_span_emitted_without_any_processors(self, span_exporter):
        # Acceptance: wrapping (and thus span emission) happens even with no
        # processors registered, i.e. when the Manager passes runner=None.
        recording_tool = _make_recording_function_tool("record", [])

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            ctx = SimpleNamespace(tool_name=tool.name)
            await tool.on_invoke_tool(ctx, '{"text":"hi"}')
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())  # no processors
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)

        assert len(_tool_spans(span_exporter)) == 1

    @pytest.mark.asyncio
    async def test_wrapping_does_not_leak_after_run(self, span_exporter):
        recording_tool = _make_recording_function_tool("record", [])

        async def fake_runner(agent: Any, prompt: str):
            tool = next(t for t in agent.tools if t.name == "record")
            ctx = SimpleNamespace(tool_name=tool.name)
            await tool.on_invoke_tool(ctx, '{"text":"hi"}')
            return _make_run_result("done", _make_usage(1, 1))

        mgr = ArgoxManager()
        mgr.register_plugin(ArgoxOpenAIPlugin())
        agent = _make_agent()
        object.__setattr__(agent, "tools", [recording_tool])
        await mgr.run(agent, "hi", "openai", fake_runner)
        # agent.tools is identical (by value) before and after the run.
        assert agent.tools == [recording_tool]
