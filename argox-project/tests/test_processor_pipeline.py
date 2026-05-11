"""CORE-06 — fail-open/fail-closed processor semantics and span emission in ArgoxManager."""

from __future__ import annotations

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
_TEST_PROVIDER = TracerProvider(resource=Resource.create({"service.name": "test"}))
_TEST_PROVIDER.add_span_processor(SimpleSpanProcessor(_TEST_EXPORTER))
# Bypass OTel's set-once guard so we always install the in-memory provider for this module.
trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
trace.set_tracer_provider(_TEST_PROVIDER)


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    """Yield the module-level in-memory exporter, cleared at the start of each test."""
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

    def instrument(self, target: Any, metrics: AgentRunMetrics) -> Any:
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
