"""Strategy A: pure SDK overhead benchmarks using a mock runner.

Measures the latency Argox itself adds on top of LLM execution, with a
phase breakdown available via AgentRunMetrics.phase_timings.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


@pytest.mark.benchmark(group="overhead", disable_gc=True)
def test_sdk_overhead_baseline(benchmark, bench_loop, manager_no_extras, fake_agent, fake_llm_response):
    """Baseline: no processors, no policy — pure lifecycle scaffolding cost."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: bench_loop.run_until_complete(
            manager_no_extras.run(fake_agent, "hello", "stub", mock_runner)
        )
    )
    assert result is not None


@pytest.mark.benchmark(group="overhead", disable_gc=True)
def test_sdk_overhead_with_processors(benchmark, bench_loop, manager_with_pii, fake_agent, fake_llm_response):
    """Measures added cost of the PII redaction processor pipeline."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: bench_loop.run_until_complete(
            manager_with_pii.run(fake_agent, "Call me at 555-1234", "stub", mock_runner)
        )
    )
    assert result is not None


@pytest.mark.benchmark(group="overhead", disable_gc=True)
def test_sdk_overhead_with_policy(benchmark, bench_loop, manager_with_policy, fake_agent, fake_llm_response):
    """Measures added cost of policy checks (allow-all stub — no network)."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: bench_loop.run_until_complete(
            manager_with_policy.run(fake_agent, "hello", "stub", mock_runner)
        )
    )
    assert result is not None


@pytest.mark.benchmark(group="overhead", disable_gc=True)
def test_sdk_overhead_phase_breakdown(
    benchmark,
    bench_loop,
    manager_timed,
    fake_agent,
    fake_llm_response,
    capturing_exporter,
):
    """Phase timings are correct and the real SDK scaffold cost stays bounded.

    The runner sleeps 100ms to stand in for LLM latency. The old version asserted
    ``overhead_pct < 5%`` of that sleep, which is satisfied by construction (the
    sleep dwarfs everything) and proves nothing. Instead we assert three things
    that can actually fail if the SDK regresses:

    1. ``agent_exec`` captured the 100ms sleep — i.e. the probe wraps the right
       call, not some other phase.
    2. The *real* SDK overhead — the sum of every non-``agent_exec`` phase, all on
       the same ``perf_counter`` clock — stays under a small **absolute** bound.
       This is independent of the sleep length, so it is a genuine ceiling on
       scaffold cost.
    3. ``agent_exec`` is the dominant phase, sanity-checking the breakdown.
    """

    sleep_s = 0.1

    manager_timed.register_exporter(capturing_exporter)

    async def slow_runner(agent: Any, prompt: str) -> Any:
        await asyncio.sleep(sleep_s)
        return fake_llm_response

    benchmark(
        lambda: bench_loop.run_until_complete(
            manager_timed.run(fake_agent, "hello", "stub", slow_runner)
        )
    )

    timings = capturing_exporter.exports[-1].phase_timings
    for key in ("agent_exec", "processors_input", "processors_output", "export"):
        assert key in timings, f"missing phase timing: {key}"

    agent_exec_ms = timings["agent_exec"]
    sleep_ms = sleep_s * 1000

    # 1. The probe wrapped the LLM call: agent_exec ≈ the 100ms sleep. Generous
    #    upper bound tolerates a loaded host without letting a wrong-phase probe
    #    pass (e.g. if agent_exec accidentally measured a sub-ms scaffold step).
    assert sleep_ms * 0.8 <= agent_exec_ms <= sleep_ms * 2.5, (
        f"agent_exec {agent_exec_ms:.1f}ms did not capture the {sleep_ms:.0f}ms sleep"
    )

    # 2. Real SDK overhead = every phase except the LLM call. Absolute ceiling,
    #    not a ratio against the artificial sleep — this can actually regress.
    overhead_ms = sum(v for k, v in timings.items() if k != "agent_exec")
    assert overhead_ms < 5.0, f"SDK scaffold overhead {overhead_ms:.3f}ms exceeded 5ms"

    # 3. The LLM call dominates the breakdown.
    assert agent_exec_ms == max(timings.values())
