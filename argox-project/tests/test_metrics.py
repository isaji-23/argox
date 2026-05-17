"""OBS-01 — OTel metric instruments emitted by ArgoxManager.

Uses ``InMemoryMetricReader`` to assert recorded counter/histogram values and
attribute sets for every instrument declared in plan.md, without spinning up
a periodic exporter.
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry import metrics as _metrics_api
from opentelemetry.metrics import _internal as _metrics_api_internal  # type: ignore[attr-defined]
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from argox.core.context import RunContext
from argox.core.manager import ArgoxManager
from argox.core.metrics import record_token_usage, reset_instruments
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.core.telemetry import init_metrics
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.interfaces.processor import ArgoxProcessor
from argox.semconv.attributes import (
    ARGOX_AGENT_NAME,
    ARGOX_POLICY_DECISION,
    ARGOX_POLICY_RULE_ID,
    ARGOX_PROCESSOR_NAME,
    ARGOX_PROCESSOR_PHASE,
    ARGOX_PROCESSOR_STATUS,
    ARGOX_RUN_SUCCESS,
    GEN_AI_TOKEN_TYPE,
    METRIC_ARGOX_POLICY_DECISIONS,
    METRIC_ARGOX_PROCESSOR_INVOCATIONS,
    METRIC_GEN_AI_OPERATION_DURATION,
    METRIC_GEN_AI_TOKEN_USAGE,
)


# ---------------------------------------------------------------------------
# Fixtures — fresh MeterProvider + InMemoryMetricReader per test
# ---------------------------------------------------------------------------


@pytest.fixture
def metric_reader():
    """Install a fresh MeterProvider backed by an InMemoryMetricReader.

    OTel's ``set_meter_provider`` is set-once globally, so we reset the
    internal sentinels around each test and restore them on teardown. We also
    clear the instrument cache so they rebind to the new provider.
    """
    saved_provider = _metrics_api_internal._METER_PROVIDER  # type: ignore[attr-defined]
    saved_done = _metrics_api_internal._METER_PROVIDER_SET_ONCE._done  # type: ignore[attr-defined]

    _metrics_api_internal._METER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    _metrics_api_internal._METER_PROVIDER = None  # type: ignore[attr-defined]
    reset_instruments()

    reader = InMemoryMetricReader()
    provider = init_metrics(readers=[reader])

    yield reader

    provider.shutdown()
    _metrics_api_internal._METER_PROVIDER = saved_provider  # type: ignore[attr-defined]
    _metrics_api_internal._METER_PROVIDER_SET_ONCE._done = saved_done  # type: ignore[attr-defined]
    reset_instruments()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str = "ok", input_tokens: int = 7, output_tokens: int = 11):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens


class _FakeAgent:
    name = "metrics-agent"
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


class _StaticPolicy(PolicyClient):
    """Policy that returns canned results for each method."""

    def __init__(
        self,
        input_result: PolicyResult | None = None,
        output_result: PolicyResult | None = None,
        tool_result: PolicyResult | None = None,
    ) -> None:
        self._input = input_result or PolicyResult.ok()
        self._output = output_result or PolicyResult.ok()
        self._tool = tool_result or PolicyResult.ok()

    async def check_input(self, text: str) -> PolicyResult:
        return self._input

    async def check_output(self, text: str) -> PolicyResult:
        return self._output

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return self._tool


class _PassThroughProcessor(ArgoxProcessor):
    async def process_input(self, text: str, ctx: RunContext) -> str:
        return text

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        return args

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text


class _RaisingProcessor(ArgoxProcessor):
    async def process_input(self, text: str, ctx: RunContext) -> str:
        raise RuntimeError("input boom")

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        return args

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect(reader: InMemoryMetricReader) -> dict[str, list]:
    """Index recorded data points by metric name."""
    data = reader.get_metrics_data()
    by_name: dict[str, list] = {}
    if data is None:
        return by_name
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                by_name.setdefault(metric.name, []).extend(metric.data.data_points)
    return by_name


def _attrs(point) -> dict:
    return dict(point.attributes or {})


# ---------------------------------------------------------------------------
# init_metrics behaviour
# ---------------------------------------------------------------------------


class TestInitMetrics:
    def test_returns_meter_provider_and_sets_global(self, metric_reader):
        provider = _metrics_api.get_meter_provider()
        assert isinstance(provider, MeterProvider)

    def test_resource_attributes_present(self, metric_reader):
        # Force at least one record so the reader has data to flush
        record_token_usage(1, token_type="input")
        data = metric_reader.get_metrics_data()
        resource = data.resource_metrics[0].resource
        attrs = dict(resource.attributes)
        assert attrs["service.name"] == "argox-agent"
        assert attrs["telemetry.distro.name"] == "argox"


# ---------------------------------------------------------------------------
# Instruments emitted by ArgoxManager.run
# ---------------------------------------------------------------------------


class TestRunInstruments:
    @pytest.mark.asyncio
    async def test_token_usage_counter_split_by_type(self, metric_reader):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_GEN_AI_TOKEN_USAGE, [])
        by_type = {_attrs(p)[GEN_AI_TOKEN_TYPE]: p.value for p in points}
        assert by_type == {"input": 7, "output": 11}

    @pytest.mark.asyncio
    async def test_run_duration_histogram_records_one_sample(self, metric_reader):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_GEN_AI_OPERATION_DURATION, [])
        assert len(points) == 1
        point = points[0]
        attrs = _attrs(point)
        assert attrs[ARGOX_AGENT_NAME] == "metrics-agent"
        assert attrs[ARGOX_RUN_SUCCESS] is True
        assert point.count == 1
        assert point.sum >= 0

    @pytest.mark.asyncio
    async def test_run_duration_marks_failed_runs(self, metric_reader):
        mgr = ArgoxManager(policy=_StaticPolicy(input_result=PolicyResult.block("no", rule_id="R1")))
        mgr.register_plugin(_FakePlugin())
        with pytest.raises(PermissionError):
            await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_GEN_AI_OPERATION_DURATION, [])
        assert len(points) == 1
        assert _attrs(points[0])[ARGOX_RUN_SUCCESS] is False


class TestPolicyDecisionsCounter:
    @pytest.mark.asyncio
    async def test_ok_decision_recorded_for_input_and_output(self, metric_reader):
        mgr = ArgoxManager(policy=_StaticPolicy())
        mgr.register_plugin(_FakePlugin())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_ARGOX_POLICY_DECISIONS, [])
        decisions = [_attrs(p)[ARGOX_POLICY_DECISION] for p in points]
        # Allow path increments the same counter on input and output
        total = sum(p.value for p in points if _attrs(p)[ARGOX_POLICY_DECISION] == "ok")
        assert total == 2
        assert "block" not in decisions

    @pytest.mark.asyncio
    async def test_tool_decisions_recorded_per_tool(self, metric_reader):
        class _ToolyAgent:
            name = "tooly"
            tools = ["safe", "danger"]

        class _ToolPolicy(_StaticPolicy):
            async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
                if tool_name == "danger":
                    return PolicyResult.block("nope", rule_id="TOOL-1")
                return PolicyResult.ok()

        mgr = ArgoxManager(policy=_ToolPolicy())
        mgr.register_plugin(_FakePlugin())
        await mgr.run(_ToolyAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_ARGOX_POLICY_DECISIONS, [])
        ok_total = sum(
            p.value for p in points if _attrs(p)[ARGOX_POLICY_DECISION] == "ok"
        )
        block_points = [
            p for p in points if _attrs(p)[ARGOX_POLICY_DECISION] == "block"
        ]
        # 2 input/output "ok" + 1 tool "ok" (safe)
        assert ok_total == 3
        assert len(block_points) == 1
        assert _attrs(block_points[0])[ARGOX_POLICY_RULE_ID] == "TOOL-1"

    @pytest.mark.asyncio
    async def test_block_decision_carries_rule_id(self, metric_reader):
        mgr = ArgoxManager(
            policy=_StaticPolicy(input_result=PolicyResult.block("blocked", rule_id="RULE-9"))
        )
        mgr.register_plugin(_FakePlugin())
        with pytest.raises(PermissionError):
            await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_ARGOX_POLICY_DECISIONS, [])
        block_points = [
            p for p in points if _attrs(p)[ARGOX_POLICY_DECISION] == "block"
        ]
        assert len(block_points) == 1
        assert _attrs(block_points[0])[ARGOX_POLICY_RULE_ID] == "RULE-9"


class TestProcessorInvocationsCounter:
    @pytest.mark.asyncio
    async def test_applied_status_per_phase(self, metric_reader):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_PassThroughProcessor())
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_ARGOX_PROCESSOR_INVOCATIONS, [])
        by_phase_status = {
            (_attrs(p)[ARGOX_PROCESSOR_PHASE], _attrs(p)[ARGOX_PROCESSOR_STATUS]): p.value
            for p in points
        }
        assert by_phase_status == {
            ("input", "applied"): 1,
            ("output", "applied"): 1,
        }
        assert all(
            _attrs(p)[ARGOX_PROCESSOR_NAME] == "_PassThroughProcessor" for p in points
        )

    @pytest.mark.asyncio
    async def test_error_status_recorded_fail_open(self, metric_reader):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_RaisingProcessor())  # fail-open (default)
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)

        points = _collect(metric_reader).get(METRIC_ARGOX_PROCESSOR_INVOCATIONS, [])
        # Input raises, output processor returns text unchanged (applied)
        statuses = sorted(
            (_attrs(p)[ARGOX_PROCESSOR_PHASE], _attrs(p)[ARGOX_PROCESSOR_STATUS])
            for p in points
        )
        assert statuses == [("input", "error"), ("output", "applied")]
