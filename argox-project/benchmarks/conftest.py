"""Shared fixtures for Argox benchmarks.

All fixtures avoid real API calls. Use manager_full + VCR cassettes for
realistic response shapes without network variance.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from argox.core.context import RunContext
from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.interfaces.processor import ArgoxProcessor
from argox.processors.pii import PiiRedactionProcessor


# ---------------------------------------------------------------------------
# Fake objects
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    text: str = "This is a benchmark response."
    input_tokens: int = 10
    output_tokens: int = 20

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class FakeAgent:
    name: str = "bench-agent"
    tools: list = field(default_factory=list)


class StubPlugin(ArgoxPlugin):
    @property
    def name(self) -> str:
        return "stub"

    def instrument(self, target: Any, metrics: AgentRunMetrics, tool_args_runner: Any = None) -> Any:
        return target

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        if isinstance(raw_result, FakeLLMResponse):
            metrics.api_calls.append(
                ApiCallRecord(
                    call_number=len(metrics.api_calls) + 1,
                    input_tokens=raw_result.input_tokens,
                    output_tokens=raw_result.output_tokens,
                    total_tokens=raw_result.total_tokens,
                )
            )

    def extract_output(self, raw_result: Any) -> str:
        if isinstance(raw_result, FakeLLMResponse):
            return raw_result.text
        return str(raw_result)


class AllowAllPolicy(PolicyClient):
    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.ok()


class CapturingExporter(ExporterBase):
    def __init__(self) -> None:
        self.exports: list[AgentRunMetrics] = []

    def export(self, metrics: AgentRunMetrics) -> None:
        self.exports.append(metrics)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def bench_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """A single persistent event loop reused across every timed round.

    Benchmarks must drive coroutines with ``bench_loop.run_until_complete(...)``
    rather than ``asyncio.run(...)``. ``asyncio.run`` builds and tears down a
    fresh loop on every call — tens of microseconds of work plus heavy
    allocation — which would dominate the very SDK overhead these benchmarks try
    to measure and inflate variance. Reusing one loop keeps the timed region to
    the coroutine itself, so absolute numbers and the baseline-vs-feature delta
    stay honest.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture
def fake_agent() -> FakeAgent:
    return FakeAgent()


@pytest.fixture
def fake_llm_response() -> FakeLLMResponse:
    return FakeLLMResponse()


@pytest.fixture
def make_llm_response():
    """Factory for `FakeLLMResponse` with custom output text / token counts.

    Lets benchmarks build realistically-sized payloads (large outputs, embedded
    PII) instead of the fixed 29-char default.
    """
    def _make(text: str, input_tokens: int = 10, output_tokens: int = 20) -> FakeLLMResponse:
        return FakeLLMResponse(text=text, input_tokens=input_tokens, output_tokens=output_tokens)

    return _make


@pytest.fixture
def run_context() -> RunContext:
    return RunContext(run_id="bench-run", agent_name="bench-agent")


@pytest.fixture
def stub_plugin() -> StubPlugin:
    return StubPlugin()


@pytest.fixture
def capturing_exporter() -> CapturingExporter:
    return CapturingExporter()


@pytest.fixture
def manager_no_extras(stub_plugin: StubPlugin) -> ArgoxManager:
    mgr = ArgoxManager()
    mgr.register_plugin(stub_plugin)
    return mgr


@pytest.fixture
def manager_timed(stub_plugin: StubPlugin) -> ArgoxManager:
    """Bare manager with phase timings enabled, for the phase-breakdown bench."""
    mgr = ArgoxManager(enable_phase_timings=True)
    mgr.register_plugin(stub_plugin)
    return mgr


@pytest.fixture
def manager_with_pii(stub_plugin: StubPlugin) -> ArgoxManager:
    mgr = ArgoxManager()
    mgr.register_plugin(stub_plugin)
    mgr.register_processor(PiiRedactionProcessor())
    return mgr


@pytest.fixture
def manager_with_policy(stub_plugin: StubPlugin) -> ArgoxManager:
    mgr = ArgoxManager(policy=AllowAllPolicy())
    mgr.register_plugin(stub_plugin)
    return mgr


@pytest.fixture
def manager_full(stub_plugin: StubPlugin) -> ArgoxManager:
    mgr = ArgoxManager(policy=AllowAllPolicy())
    mgr.register_plugin(stub_plugin)
    mgr.register_processor(PiiRedactionProcessor())
    return mgr
