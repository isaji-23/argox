"""CORE-06 — fail-open/fail-closed processor semantics and span emission in ArgoxManager."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from argox.core.context import RunContext
from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.processor import ArgoxProcessor
from argox.semconv.attributes import (
    ARGOX_PROCESSOR_APPLIED,
    ARGOX_PROCESSOR_NAME,
    ARGOX_PROCESSOR_PHASE,
    ARGOX_PROCESSOR_STRICT,
    EVENT_PROCESSOR_APPLIED,
    EVENT_PROCESSOR_ERROR,
    SPAN_AGENT_RUN,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


_TEST_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _install_in_memory_tracer_provider():
    """Install an in-memory TracerProvider for this module, restore previous state on exit.

    OTel's ``set_tracer_provider`` is set-once globally, so we bypass the guard via private
    attributes (``_TRACER_PROVIDER`` and ``_TRACER_PROVIDER_SET_ONCE._done``) and restore
    them when the module's tests finish. This contains the mutation to this module instead
    of leaking across the test session.
    """
    saved_provider = trace._TRACER_PROVIDER  # type: ignore[attr-defined]
    saved_set_once = trace._TRACER_PROVIDER_SET_ONCE._done  # type: ignore[attr-defined]

    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(_TEST_EXPORTER))
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace.set_tracer_provider(provider)

    yield

    trace._TRACER_PROVIDER = saved_provider  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE._done = saved_set_once  # type: ignore[attr-defined]
    _TEST_EXPORTER.clear()


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    """Yield the in-memory exporter, cleared at the start of each test."""
    _TEST_EXPORTER.clear()
    yield _TEST_EXPORTER
    _TEST_EXPORTER.clear()


class _FakeResponse:
    def __init__(self, text: str = "ok"):
        self.text = text
        self.input_tokens = 7
        self.output_tokens = 11
        self.total_tokens = 18


class _FakeAgent:
    name = "test-agent"
    tools: list = []


class _FakePlugin(ArgoxPlugin):
    @property
    def name(self) -> str:
        return "fake"

    def instrument(
        self,
        target: Any,
        metrics: AgentRunMetrics,
        tool_args_runner: Any = None,
    ) -> Any:
        return target

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        if isinstance(raw_result, _FakeResponse):
            metrics.api_calls.append(
                ApiCallRecord(
                    call_number=1,
                    input_tokens=raw_result.input_tokens,
                    output_tokens=raw_result.output_tokens,
                    total_tokens=raw_result.total_tokens,
                )
            )

    def extract_output(self, raw_result: Any) -> str:
        return raw_result.text


async def _fake_runner(agent: Any, prompt: str) -> _FakeResponse:
    return _FakeResponse(text=f"echo: {prompt}")


class _PassThroughProcessor(ArgoxProcessor):
    async def process_input(self, text: str, ctx: RunContext) -> str:
        return text + "/in"

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        return args

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text + "/out"


class _RaisingProcessor(ArgoxProcessor):
    """Processor that always raises on every phase."""

    async def process_input(self, text: str, ctx: RunContext) -> str:
        raise RuntimeError("input boom")

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        raise RuntimeError("tool_args boom")

    async def process_output(self, text: str, ctx: RunContext) -> str:
        raise RuntimeError("output boom")


def _find_run_span(exporter: InMemorySpanExporter):
    spans = [s for s in exporter.get_finished_spans() if s.name == SPAN_AGENT_RUN]
    assert len(spans) == 1, f"expected 1 run span, found {len(spans)}"
    return spans[0]


# ---------------------------------------------------------------------------
# Fail-open / fail-closed
# ---------------------------------------------------------------------------


class TestProcessorFailureSemantics:
    @pytest.mark.asyncio
    async def test_fail_open_continues_run(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_RaisingProcessor())  # default strict=False
        result = await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        assert result == "echo: hello"

    @pytest.mark.asyncio
    async def test_fail_open_preserves_value_for_next_processor(self, span_exporter):
        captured: list[str] = []

        class _Capture(ArgoxProcessor):
            async def process_input(self, text: str, ctx: RunContext) -> str:
                captured.append(text)
                return text

            async def process_tool_args(self, tool_name, args, ctx):
                return args

            async def process_output(self, text: str, ctx: RunContext) -> str:
                return text

        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_PassThroughProcessor())  # appends "/in"
        mgr.register_processor(_RaisingProcessor())  # raises, fail-open
        mgr.register_processor(_Capture())  # should still see "/in"
        await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        assert captured == ["hello/in"]

    @pytest.mark.asyncio
    async def test_strict_processor_aborts_run(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_RaisingProcessor(), strict=True)
        with pytest.raises(RuntimeError, match="input boom"):
            await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

    @pytest.mark.asyncio
    async def test_cancellation_propagates_in_fail_open_mode(self, span_exporter):
        """CancelledError must propagate even when the processor is registered fail-open."""

        class _CancellingProcessor(ArgoxProcessor):
            async def process_input(self, text: str, ctx: RunContext) -> str:
                raise asyncio.CancelledError()

            async def process_tool_args(self, tool_name, args, ctx):
                return args

            async def process_output(self, text: str, ctx: RunContext) -> str:
                return text

        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_CancellingProcessor())  # strict=False
        with pytest.raises(asyncio.CancelledError):
            await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

    @pytest.mark.asyncio
    async def test_strict_failure_marks_span_error(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_RaisingProcessor(), strict=True)
        with pytest.raises(RuntimeError):
            await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        assert span.status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# Span emission
# ---------------------------------------------------------------------------


class TestSpanEmission:
    @pytest.mark.asyncio
    async def test_run_emits_top_level_span(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        assert span.name == SPAN_AGENT_RUN

    @pytest.mark.asyncio
    async def test_successful_processor_emits_applied_event(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_PassThroughProcessor())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        events = [e for e in span.events if e.name == EVENT_PROCESSOR_APPLIED]
        # one for input phase, one for output phase
        assert len(events) == 2
        phases = {e.attributes[ARGOX_PROCESSOR_PHASE] for e in events}
        assert phases == {"input", "output"}
        names = {e.attributes[ARGOX_PROCESSOR_NAME] for e in events}
        assert names == {"_PassThroughProcessor"}

    @pytest.mark.asyncio
    async def test_failing_processor_emits_error_event(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_RaisingProcessor())  # fail-open
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        error_events = [e for e in span.events if e.name == EVENT_PROCESSOR_ERROR]
        assert len(error_events) == 2  # input + output phases both failed
        e = error_events[0]
        assert e.attributes[ARGOX_PROCESSOR_NAME] == "_RaisingProcessor"
        assert e.attributes[ARGOX_PROCESSOR_STRICT] is False
        assert e.attributes["exception.type"] == "RuntimeError"
        assert "boom" in e.attributes["exception.message"]

    @pytest.mark.asyncio
    async def test_applied_attribute_lists_unique_processor_names(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_PassThroughProcessor())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        applied = span.attributes[ARGOX_PROCESSOR_APPLIED]
        assert list(applied) == ["_PassThroughProcessor"]

    @pytest.mark.asyncio
    async def test_token_attributes_populated(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        assert span.attributes["gen_ai.usage.input_tokens"] == 7
        assert span.attributes["gen_ai.usage.output_tokens"] == 11

    @pytest.mark.asyncio
    async def test_token_attributes_set_when_call_records_zero_tokens(self, span_exporter):
        """A legitimate 0-token API call must still produce token span attributes."""

        class _ZeroTokenPlugin(_FakePlugin):
            def extract_tokens(self, raw_result, metrics):
                metrics.api_calls.append(
                    ApiCallRecord(call_number=1, input_tokens=0, output_tokens=0, total_tokens=0)
                )

        mgr = ArgoxManager()
        mgr.register_plugin(_ZeroTokenPlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        assert span.attributes["gen_ai.usage.input_tokens"] == 0
        assert span.attributes["gen_ai.usage.output_tokens"] == 0

    @pytest.mark.asyncio
    async def test_no_token_attributes_when_no_api_calls(self, span_exporter):
        """Plugins that never record an API call must leave the token attributes unset."""

        class _NoApiPlugin(_FakePlugin):
            def extract_tokens(self, raw_result, metrics):
                pass

        mgr = ArgoxManager()
        mgr.register_plugin(_NoApiPlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        attrs = span.attributes or {}
        assert "gen_ai.usage.input_tokens" not in attrs
        assert "gen_ai.usage.output_tokens" not in attrs

    @pytest.mark.asyncio
    async def test_applied_attribute_set_when_strict_processor_aborts(self, span_exporter):
        """Processors that ran before a strict failure must still appear on the run span."""
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_PassThroughProcessor())  # runs successfully on input
        mgr.register_processor(_RaisingProcessor(), strict=True)  # aborts input phase
        with pytest.raises(RuntimeError):
            await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        applied = span.attributes[ARGOX_PROCESSOR_APPLIED]
        assert list(applied) == ["_PassThroughProcessor"]

    @pytest.mark.asyncio
    async def test_no_processor_applied_attribute_when_none_registered(self, span_exporter):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        span = _find_run_span(span_exporter)
        assert ARGOX_PROCESSOR_APPLIED not in (span.attributes or {})


# ---------------------------------------------------------------------------
# tool_args phase — Manager-level semantics (PLUGIN-02)
# ---------------------------------------------------------------------------


class _ToolArgsCapturingPlugin(_FakePlugin):
    """Plugin that captures the ``tool_args_runner`` so tests can drive it directly."""

    def __init__(self) -> None:
        self.captured_runner: Any = None

    def instrument(
        self,
        target: Any,
        metrics: AgentRunMetrics,
        tool_args_runner: Any = None,
    ) -> Any:
        self.captured_runner = tool_args_runner
        return target


def _make_runner_invoking_tool(
    plugin: _ToolArgsCapturingPlugin,
    tool_name: str,
    args: dict,
    sink: list,
):
    """Build a fake runner that drives the captured tool_args_runner once during the run."""

    async def runner(agent: Any, prompt: str) -> _FakeResponse:
        if plugin.captured_runner is None:
            sink.append(("no-runner", None))
        else:
            try:
                mutated = await plugin.captured_runner(tool_name, args)
                sink.append(("ok", mutated))
            except Exception as exc:
                sink.append(("err", exc))
                raise
        return _FakeResponse(text=f"echo: {prompt}")

    return runner


class _ArgsMutatingProcessor(ArgoxProcessor):
    """Processor that injects a fixed key/value into tool_args, no-ops elsewhere."""

    async def process_input(self, text: str, ctx: RunContext) -> str:
        return text

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        return {**args, "redacted": True}

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text


class _ToolArgsRaisingProcessor(ArgoxProcessor):
    """Processor that raises only on the tool_args phase."""

    async def process_input(self, text: str, ctx: RunContext) -> str:
        return text

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        raise RuntimeError("tool_args boom")

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text


class TestToolArgsPhase:
    @pytest.mark.asyncio
    async def test_manager_passes_runner_to_plugin(self, span_exporter):
        plugin = _ToolArgsCapturingPlugin()
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_PassThroughProcessor())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        assert callable(plugin.captured_runner)

    @pytest.mark.asyncio
    async def test_runner_applies_processor_chain_in_order(self, span_exporter):
        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_ArgsMutatingProcessor())
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "search", {"q": "hi"}, sink),
        )
        assert sink == [("ok", {"q": "hi", "redacted": True})]

    @pytest.mark.asyncio
    async def test_fail_open_returns_unchanged_args(self, span_exporter):
        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_ToolArgsRaisingProcessor())  # default strict=False
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "calc", {"x": 1}, sink),
        )
        assert sink == [("ok", {"x": 1})]

    @pytest.mark.asyncio
    async def test_strict_failure_aborts_run(self, span_exporter):
        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_ToolArgsRaisingProcessor(), strict=True)
        with pytest.raises(RuntimeError, match="tool_args boom"):
            await mgr.run(
                _FakeAgent(), "hi", "fake",
                _make_runner_invoking_tool(plugin, "calc", {"x": 1}, sink),
            )
        span = _find_run_span(span_exporter)
        assert span.status.status_code == StatusCode.ERROR

    @pytest.mark.asyncio
    async def test_successful_tool_args_emits_applied_event_with_phase_and_tool(
        self, span_exporter,
    ):
        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_ArgsMutatingProcessor())
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "search", {"q": "hi"}, sink),
        )
        span = _find_run_span(span_exporter)
        applied_events = [
            e for e in span.events
            if e.name == EVENT_PROCESSOR_APPLIED
            and e.attributes[ARGOX_PROCESSOR_PHASE] == "tool_args"
        ]
        assert len(applied_events) == 1
        e = applied_events[0]
        assert e.attributes[ARGOX_PROCESSOR_NAME] == "_ArgsMutatingProcessor"
        assert e.attributes["argox.processor.tool_name"] == "search"

    @pytest.mark.asyncio
    async def test_fail_open_emits_error_event_with_tool_name(self, span_exporter):
        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_ToolArgsRaisingProcessor())
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "calc", {"x": 1}, sink),
        )
        span = _find_run_span(span_exporter)
        err_events = [
            e for e in span.events
            if e.name == EVENT_PROCESSOR_ERROR
            and e.attributes[ARGOX_PROCESSOR_PHASE] == "tool_args"
        ]
        assert len(err_events) == 1
        e = err_events[0]
        assert e.attributes["argox.processor.tool_name"] == "calc"
        assert e.attributes[ARGOX_PROCESSOR_STRICT] is False
        assert e.attributes["exception.type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_applied_attribute_includes_tool_args_only_processors(
        self, span_exporter,
    ):
        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_ArgsMutatingProcessor())
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "search", {"q": "hi"}, sink),
        )
        span = _find_run_span(span_exporter)
        applied = span.attributes[ARGOX_PROCESSOR_APPLIED]
        assert "_ArgsMutatingProcessor" in list(applied)

    @pytest.mark.asyncio
    async def test_processor_chain_runs_in_registration_order(self, span_exporter):
        class _AddA(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                return {**args, "order": args.get("order", "") + "a"}
            async def process_output(self, text, ctx): return text

        class _AddB(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                return {**args, "order": args.get("order", "") + "b"}
            async def process_output(self, text, ctx): return text

        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_AddA())
        mgr.register_processor(_AddB())
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "t", {}, sink),
        )
        assert sink == [("ok", {"order": "ab"})]

    @pytest.mark.asyncio
    async def test_fail_open_isolates_in_place_mutation_before_raising(
        self, span_exporter,
    ):
        """A fail-open processor that mutates args in place and then raises
        must not leak its partial changes into the next processor or the tool."""

        class _MutateThenBoom(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                args["leaked"] = "should not appear"
                raise RuntimeError("mutate-then-boom")
            async def process_output(self, text, ctx): return text

        observed: list[dict] = []

        class _Observer(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                observed.append(dict(args))
                return args
            async def process_output(self, text, ctx): return text

        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_MutateThenBoom())  # fail-open
        mgr.register_processor(_Observer())
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "t", {"k": "v"}, sink),
        )
        assert observed == [{"k": "v"}]
        assert sink == [("ok", {"k": "v"})]

    @pytest.mark.asyncio
    async def test_fail_open_isolates_nested_in_place_mutation(self, span_exporter):
        """Deep-copy must also protect nested structures, not only top-level keys."""

        class _MutateNestedThenBoom(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                args["nested"]["leaked"] = True
                raise RuntimeError("nested boom")
            async def process_output(self, text, ctx): return text

        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_MutateNestedThenBoom())  # fail-open
        await mgr.run(
            _FakeAgent(), "hi", "fake",
            _make_runner_invoking_tool(plugin, "t", {"nested": {"safe": True}}, sink),
        )
        assert sink == [("ok", {"nested": {"safe": True}})]

    @pytest.mark.asyncio
    async def test_manager_passes_none_runner_when_no_processors(self, span_exporter):
        """When zero processors are registered the Manager must not build a runner,
        so plugins can short-circuit any tool wrapping or JSON round-tripping."""
        plugin = _ToolArgsCapturingPlugin()
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        assert plugin.captured_runner is None

    @pytest.mark.asyncio
    async def test_cancellation_propagates_in_tool_args_fail_open_mode(
        self, span_exporter,
    ):
        class _CancellingToolArgs(ArgoxProcessor):
            async def process_input(self, text, ctx): return text
            async def process_tool_args(self, name, args, ctx):
                raise asyncio.CancelledError()
            async def process_output(self, text, ctx): return text

        plugin = _ToolArgsCapturingPlugin()
        sink: list = []
        mgr = ArgoxManager()
        mgr.register_plugin(plugin)
        mgr.register_processor(_CancellingToolArgs())  # strict=False
        with pytest.raises(asyncio.CancelledError):
            await mgr.run(
                _FakeAgent(), "hi", "fake",
                _make_runner_invoking_tool(plugin, "t", {}, sink),
            )
