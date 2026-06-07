"""Strategy D: concurrent load benchmarks.

Measures throughput under N concurrent runs and verifies the SDK does not
serialize them. The mock runner awaits a small fixed latency (`_LLM_LATENCY_S`)
so `asyncio.gather` genuinely overlaps the runs — with an instant mock the
"concurrent" runs would execute back-to-back and the benchmark would measure
nothing about concurrency. With real awaited latency, a processor or manager
step that blocks the event loop shows up as wall time collapsing toward the
sequential bound (N * latency); `test_concurrent_overlap_no_blocking` asserts it
does not.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from argox.core.manager import ArgoxManager

# Simulated per-call LLM latency. Small enough to keep the suite fast, large
# enough that overlapped (N runs in ~_LLM_LATENCY_S) is clearly distinguishable
# from serialized (N runs in ~N * _LLM_LATENCY_S).
_LLM_LATENCY_S = 0.005


async def _run_n_concurrent(manager: ArgoxManager, fake_agent: Any, fake_llm_response: Any, n: int) -> list[str]:
    async def mock_runner(agent: Any, prompt: str) -> Any:
        await asyncio.sleep(_LLM_LATENCY_S)
        return fake_llm_response

    tasks = [
        manager.run(fake_agent, f"prompt-{i}", "stub", mock_runner)
        for i in range(n)
    ]
    return await asyncio.gather(*tasks)


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_10(benchmark, bench_loop, manager_no_extras, fake_agent, fake_llm_response):
    """10 concurrent runs — baseline concurrency cost."""
    results = benchmark(
        lambda: bench_loop.run_until_complete(
            _run_n_concurrent(manager_no_extras, fake_agent, fake_llm_response, 10)
        )
    )
    assert len(results) == 10


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_50(benchmark, bench_loop, manager_no_extras, fake_agent, fake_llm_response):
    """50 concurrent runs — moderate load."""
    results = benchmark(
        lambda: bench_loop.run_until_complete(
            _run_n_concurrent(manager_no_extras, fake_agent, fake_llm_response, 50)
        )
    )
    assert len(results) == 50


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_100(benchmark, bench_loop, manager_no_extras, fake_agent, fake_llm_response):
    """100 concurrent runs — high load."""
    results = benchmark(
        lambda: bench_loop.run_until_complete(
            _run_n_concurrent(manager_no_extras, fake_agent, fake_llm_response, 100)
        )
    )
    assert len(results) == 100


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_with_processors(benchmark, bench_loop, manager_with_pii, fake_agent, fake_llm_response):
    """50 concurrent runs with PII processor — measures pipeline contention."""
    results = benchmark(
        lambda: bench_loop.run_until_complete(
            _run_n_concurrent(manager_with_pii, fake_agent, fake_llm_response, 50)
        )
    )
    assert len(results) == 50


def test_concurrent_overlap_no_blocking(bench_loop, manager_with_pii, fake_agent, fake_llm_response):
    """Concurrent runs overlap — the SDK does not serialize them or block the loop.

    Not a benchmark: a behavioural guarantee. N runs each awaiting
    `_LLM_LATENCY_S` should finish in ~one latency (fully overlapped) plus SDK
    coordination overhead — far below the sequential bound `N * _LLM_LATENCY_S`.
    If any phase (a processor, a policy, the export loop) ran blocking work on
    the event loop, the runs would serialize and wall time would approach the
    sequential bound, failing this assert. Uses the PII processor so the
    processor pipeline is on the path being checked.
    """
    n = 50
    sequential_bound_s = n * _LLM_LATENCY_S

    start = time.perf_counter()
    results = bench_loop.run_until_complete(
        _run_n_concurrent(manager_with_pii, fake_agent, fake_llm_response, n)
    )
    elapsed_s = time.perf_counter() - start

    assert len(results) == n
    # Generous margin (25% of the sequential bound) absorbs host scheduling jitter
    # while still failing hard if the runs serialized (which would be ~100%).
    assert elapsed_s < sequential_bound_s * 0.25, (
        f"{n} concurrent runs took {elapsed_s * 1000:.1f}ms; expected well under "
        f"the {sequential_bound_s * 1000:.0f}ms sequential bound — runs are not "
        f"overlapping (event loop blocked?)"
    )
