"""Strategy A: pure SDK overhead benchmarks using a mock runner.

Measures the latency Argox itself adds on top of LLM execution, with a
phase breakdown available via AgentRunMetrics.phase_timings.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics


@pytest.mark.benchmark(group="overhead", disable_gc=True)
def test_sdk_overhead_baseline(benchmark, manager_no_extras, fake_agent, fake_llm_response):
    """Baseline: no processors, no policy — pure lifecycle scaffolding cost."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: asyncio.run(manager_no_extras.run(fake_agent, "hello", "stub", mock_runner))
    )
    assert result is not None


@pytest.mark.benchmark(group="overhead", disable_gc=True, warmup=True)
def test_sdk_overhead_with_processors(benchmark, manager_with_pii, fake_agent, fake_llm_response):
    """Measures added cost of the PII redaction processor pipeline."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: asyncio.run(
            manager_with_pii.run(fake_agent, "Call me at 555-1234", "stub", mock_runner)
        )
    )
    assert result is not None


@pytest.mark.benchmark(group="overhead", disable_gc=True, warmup=True)
def test_sdk_overhead_with_policy(benchmark, manager_with_policy, fake_agent, fake_llm_response):
    """Measures added cost of policy checks (allow-all stub — no network)."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: asyncio.run(
            manager_with_policy.run(fake_agent, "hello", "stub", mock_runner)
        )
    )
    assert result is not None


@pytest.mark.benchmark(group="overhead", disable_gc=True)
def test_sdk_overhead_phase_breakdown(
    benchmark,
    manager_no_extras,
    fake_agent,
    fake_llm_response,
    capturing_exporter,
):
    """Phase timings populated; overhead % stays within target on 100ms mock LLM."""

    manager_no_extras.register_exporter(capturing_exporter)

    async def slow_runner(agent: Any, prompt: str) -> Any:
        await asyncio.sleep(0.1)
        return fake_llm_response

    benchmark(
        lambda: asyncio.run(manager_no_extras.run(fake_agent, "hello", "stub", slow_runner))
    )

    metrics: AgentRunMetrics = capturing_exporter.exports[-1]
    assert "agent_exec" in metrics.phase_timings
    assert "processors_input" in metrics.phase_timings
    assert "processors_output" in metrics.phase_timings
    assert "export" in metrics.phase_timings

    agent_exec_ms = metrics.phase_timings["agent_exec"]
    total_ms = metrics.duration * 1000
    overhead_ms = total_ms - agent_exec_ms
    overhead_pct = overhead_ms / total_ms * 100
    assert overhead_pct < 5.0, f"SDK overhead {overhead_pct:.1f}% exceeded 5% threshold"
