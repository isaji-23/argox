"""CORE-08 — argox.run.success and argox.agent.name on the agent.run root span."""

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

from argox.core.context import RunContext
from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.semconv.attributes import (
    ARGOX_AGENT_NAME,
    ARGOX_POLICY_DECISION,
    ARGOX_RUN_SUCCESS,
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
    name = "triage-bot"
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


class _BlockOutputPolicy(PolicyClient):
    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.block(reason="output blocked", rule_id="R2")


class _BlockToolPolicy(PolicyClient):
    def __init__(self, blocked_tool: str) -> None:
        self._blocked = blocked_tool

    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        if tool_name == self._blocked:
            return PolicyResult.block(reason="tool blocked", rule_id="R3")
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.ok()


class _CapturingExporter(ExporterBase):
    def __init__(self) -> None:
        self.exports: list[AgentRunMetrics] = []

    def export(self, metrics: AgentRunMetrics) -> None:
        self.exports.append(metrics)


async def _fake_runner(agent: Any, prompt: str) -> _FakeResponse:
    return _FakeResponse(text=f"echo: {prompt}")


def _find_run_span(exporter: InMemorySpanExporter):
    spans = [s for s in exporter.get_finished_spans() if s.name == SPAN_AGENT_RUN]
    assert len(spans) == 1, f"expected 1 run span, found {len(spans)}"
    return spans[0]


def _make_manager(policy: PolicyClient | None = None) -> ArgoxManager:
    mgr = ArgoxManager(policy=policy)
    mgr.register_plugin(_FakePlugin())
    return mgr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_run_sets_root_attributes(span_exporter: InMemorySpanExporter):
    """A monitored success run emits agent name and run.success=True with no manual setting."""
    mgr = _make_manager()

    await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)

    span = _find_run_span(span_exporter)
    assert span.attributes[ARGOX_AGENT_NAME] == "triage-bot"
    assert span.attributes[ARGOX_RUN_SUCCESS] is True


@pytest.mark.asyncio
async def test_blocked_run_records_success_false(span_exporter: InMemorySpanExporter):
    """A policy-blocked run still carries the agent name and records run.success=False."""
    mgr = _make_manager(policy=_BlockOutputPolicy())

    with pytest.raises(PermissionError):
        await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)

    span = _find_run_span(span_exporter)
    assert span.attributes[ARGOX_AGENT_NAME] == "triage-bot"
    assert span.attributes[ARGOX_RUN_SUCCESS] is False


@pytest.mark.asyncio
async def test_run_metrics_trace_id_matches_span(span_exporter: InMemorySpanExporter):
    """The run's trace_id is stamped from the root span so the Collector's
    by-trace join (runs.trace_id = spans.trace_id) resolves it. Without this the
    run is stored unlinked and GET /v1/runs/by-trace/{trace_id} returns 404."""
    exp = _CapturingExporter()
    mgr = _make_manager()
    mgr.register_exporter(exp)

    await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)

    span = _find_run_span(span_exporter)
    expected = format(span.context.trace_id, "032x")
    assert len(exp.exports) == 1
    metrics = exp.exports[0]
    assert metrics.trace_id == expected
    assert metrics.to_dict()["trace_id"] == expected
    # 32-char lowercase hex, matching the OTLP span id format the Collector stores.
    assert len(metrics.trace_id) == 32
    assert metrics.trace_id == metrics.trace_id.lower()


@pytest.mark.asyncio
async def test_blocked_tool_emits_child_span_with_block_decision(
    span_exporter: InMemorySpanExporter,
):
    """A policy-blocked tool emits its own child span carrying
    argox.policy.decision=block. The tool is stripped before the run, so without
    this span the block is invisible in the trace waterfall and the blocked-tool
    metrics (the Collector indexes policy decisions only from spans)."""
    mgr = _make_manager(policy=_BlockToolPolicy("dangerous"))

    await mgr.run(
        _FakeAgent(), "hello", "fake", _fake_runner,
        tools=["safe", "dangerous"],
    )

    blocked = [
        s
        for s in span_exporter.get_finished_spans()
        if s.attributes.get(ARGOX_POLICY_DECISION) == "block"
        and s.name != SPAN_AGENT_RUN
    ]
    assert len(blocked) == 1
    span = blocked[0]
    assert span.name == "execute_tool dangerous"
    assert span.attributes["gen_ai.tool.name"] == "dangerous"
    # A non-blocked tool must not emit a block span.
    assert all("safe" not in s.name for s in blocked)
