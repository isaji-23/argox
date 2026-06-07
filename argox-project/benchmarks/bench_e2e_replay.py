"""Strategy C: VCR replay E2E benchmarks.

Cassettes recorded from real API calls are replayed deterministically,
removing response-time variance while preserving realistic payload shapes.

To record cassettes:
    cd argox-project
    ARGOX_RECORD_CASSETTES=1 pytest benchmarks/bench_e2e_replay.py --vcr-record=new_episodes -v

Once recorded, cassettes are committed and replayed in CI without a key.
"""

from __future__ import annotations

from typing import Any

import pytest

from argox.core.manager import ArgoxManager


@pytest.mark.vcr
@pytest.mark.benchmark(group="e2e")
def test_full_run_no_tools(benchmark, bench_loop, manager_full, fake_agent, fake_llm_response):
    """Full SDK run replayed from cassette — no tool calls."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: bench_loop.run_until_complete(
            manager_full.run(fake_agent, "What is 2+2?", "stub", mock_runner)
        )
    )
    assert result is not None


@pytest.mark.vcr
@pytest.mark.benchmark(group="e2e")
def test_full_run_with_processors(benchmark, bench_loop, manager_full, fake_agent, fake_llm_response):
    """Full SDK run with PII processor and allow-all policy replayed from cassette."""

    async def mock_runner(agent: Any, prompt: str) -> Any:
        return fake_llm_response

    result = benchmark(
        lambda: bench_loop.run_until_complete(
            manager_full.run(
                fake_agent,
                "My email is test@example.com. What is 2+2?",
                "stub",
                mock_runner,
            )
        )
    )
    assert result is not None
