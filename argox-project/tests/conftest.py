"""Shared pytest fixtures for the Argox monorepo test suite.

All fixtures simulate agent runs without making real API calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest

from argox.core.context import RunContext
from argox_collector.settings import CollectorSettings
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.interfaces.processor import ArgoxProcessor


# ---------------------------------------------------------------------------
# Fake OpenAI Agents SDK objects — no real network calls
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMResponse:
    """Simulates an LLM response without touching any real API."""

    text: str = "This is a fake LLM response."
    input_tokens: int = 10
    output_tokens: int = 20

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class FakeOpenAIAgent:
    """Minimal stand-in for an OpenAI Agents SDK Agent object."""

    name: str = "test-agent"
    instructions: str = "You are a test agent."
    tools: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stub Argox interface implementations
# ---------------------------------------------------------------------------


class StubPlugin(ArgoxPlugin):
    """Minimal plugin that records calls without touching any real framework."""

    @property
    def name(self) -> str:
        return "stub"

    def instrument(
        self,
        target: Any,
        metrics: AgentRunMetrics,
        tool_args_runner: Any = None,
    ) -> Any:
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


class StubProcessor(ArgoxProcessor):
    """Pass-through processor that returns data unchanged."""

    async def process_input(self, text: str, ctx: RunContext) -> str:
        return text

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        return args

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text


class StubPolicyClient(PolicyClient):
    """Allow-all policy client — no real network calls."""

    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.ok()


class CapturingExporter(ExporterBase):
    """In-memory exporter that stores exported metrics for test assertions."""

    def __init__(self) -> None:
        self.exports: list[AgentRunMetrics] = []

    def export(self, metrics: AgentRunMetrics) -> None:
        self.exports.append(metrics)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_argox_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``CollectorSettings`` deterministic across machines.

    Ambient ``ARGOX_*`` environment variables or a developer ``.env`` in the
    working directory would otherwise leak into every test (e.g.
    ``ARGOX_STORAGE_BACKEND=azure`` flipping the backend). Strip the env vars
    and disable ``.env`` loading for the whole suite; ``monkeypatch`` restores
    both afterwards.
    """
    for key in list(os.environ):
        if key.startswith("ARGOX_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(CollectorSettings.model_config, "env_file", None)


@pytest.fixture
def fake_llm_response() -> FakeLLMResponse:
    """A canned LLM response that never touches the network."""
    return FakeLLMResponse()


@pytest.fixture
def fake_agent() -> FakeOpenAIAgent:
    """A minimal fake OpenAI Agents SDK agent object."""
    return FakeOpenAIAgent()


@pytest.fixture
def agent_metrics() -> AgentRunMetrics:
    """A fresh AgentRunMetrics instance for each test."""
    return AgentRunMetrics(agent_name="test-agent")


@pytest.fixture
def stub_plugin() -> StubPlugin:
    """A minimal ArgoxPlugin that records calls without touching any framework."""
    return StubPlugin()


@pytest.fixture
def stub_processor() -> StubProcessor:
    """A pass-through ArgoxProcessor for testing processor pipelines."""
    return StubProcessor()


@pytest.fixture
def stub_policy() -> StubPolicyClient:
    """An allow-all PolicyClient that never calls a real policy service."""
    return StubPolicyClient()


@pytest.fixture
def capturing_exporter() -> CapturingExporter:
    """An in-memory ExporterBase that stores metrics for assertions."""
    return CapturingExporter()
