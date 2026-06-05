"""Strategy D: concurrent load benchmarks.

Measures throughput and P95 latency under N concurrent runs.
Surfaces OTel global-state contention and event-loop blocking in processors.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from argox.core.manager import ArgoxManager


async def _run_n_concurrent(manager: ArgoxManager, fake_agent: Any, fake_llm_response: Any, n: int) -> list[str]:
    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    tasks = [
        manager.run(fake_agent, f"prompt-{i}", "stub", mock_runner)
        for i in range(n)
    ]
    return await asyncio.gather(*tasks)


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_10(benchmark, manager_no_extras, fake_agent, fake_llm_response):
    """10 concurrent runs — baseline concurrency cost."""
    results = benchmark(
        lambda: asyncio.run(_run_n_concurrent(manager_no_extras, fake_agent, fake_llm_response, 10))
    )
    assert len(results) == 10


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_50(benchmark, manager_no_extras, fake_agent, fake_llm_response):
    """50 concurrent runs — moderate load."""
    results = benchmark(
        lambda: asyncio.run(_run_n_concurrent(manager_no_extras, fake_agent, fake_llm_response, 50))
    )
    assert len(results) == 50


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_100(benchmark, manager_no_extras, fake_agent, fake_llm_response):
    """100 concurrent runs — high load; surface event-loop blocking."""
    results = benchmark(
        lambda: asyncio.run(_run_n_concurrent(manager_no_extras, fake_agent, fake_llm_response, 100))
    )
    assert len(results) == 100


@pytest.mark.benchmark(group="concurrent")
def test_concurrent_with_processors(benchmark, manager_with_pii, fake_agent, fake_llm_response):
    """50 concurrent runs with PII processor — measures pipeline contention."""
    results = benchmark(
        lambda: asyncio.run(
            _run_n_concurrent(manager_with_pii, fake_agent, fake_llm_response, 50)
        )
    )
    assert len(results) == 50
