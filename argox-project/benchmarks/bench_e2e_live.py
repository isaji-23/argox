"""Strategy B: real API E2E benchmarks.

Requires a real API key and ARGOX_LIVE_BENCH=1. LLM response variance
dominates SDK cost (~1ms), so N>=5 rounds minimum for any significance.

Run with:
    ARGOX_LIVE_BENCH=1 pytest benchmarks/bench_e2e_live.py -v \\
        --benchmark-columns=mean,stddev,min,max,rounds
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("ARGOX_LIVE_BENCH"),
    reason="set ARGOX_LIVE_BENCH=1 to run live API benchmarks",
)


@pytest.mark.benchmark(group="live", rounds=5, warmup_rounds=1)
def test_live_bare_openai(benchmark):
    """Baseline: raw openai client call, no SDK wrapping."""
    pytest.skip("not implemented — wire up raw openai client here")


@pytest.mark.benchmark(group="live", rounds=5, warmup_rounds=1)
def test_live_sdk_wrapped(benchmark, manager_full, fake_agent):
    """SDK-wrapped call. Compare mean to test_live_bare_openai to get overhead."""
    pytest.skip("not implemented — wire up real openai runner here")
