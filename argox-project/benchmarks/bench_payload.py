"""Strategy C: realistic-payload lifecycle overhead.

Runs the full manager lifecycle (allow-all policy + PII output processor) over
realistically-sized LLM outputs, with no network. This replaces the former VCR
"replay" module, which was marked ``@pytest.mark.vcr`` but actually used a mock
runner and empty cassettes — it replayed nothing. Here we instead feed payloads
of representative size and shape so the overhead numbers reflect real output
volumes (the output processor scans the whole response).

Complements the other strategies:
- ``bench_overhead.py`` measures the scaffold on a tiny (~29 char) output.
- ``bench_components.py`` measures the PII processor in isolation.
- this module measures the **full lifecycle** as output size grows, and asserts
  the pipeline actually redacts PII end to end.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

# Representative output sizes (characters). "typical" ~ a short chat answer;
# "large" ~ a long structured response / document summary.
_TYPICAL = "Your account a@b.com was charged. Call 555-1234 for support. " * 8      # ~480 chars
_LARGE = "Contact test@example.com or 555-9876 about invoice 12345. " * 200         # ~11k chars


def _mock_runner_factory(response: Any):
    async def mock_runner(agent: Any, prompt: str) -> Any:
        return response

    return mock_runner


@pytest.mark.benchmark(group="payload")
def test_full_run_typical_output(benchmark, bench_loop, manager_full, fake_agent, make_llm_response):
    """Full lifecycle over a ~480-char output with embedded PII."""
    runner = _mock_runner_factory(make_llm_response(_TYPICAL))

    result = benchmark(
        lambda: bench_loop.run_until_complete(
            manager_full.run(fake_agent, "summarize my account", "stub", runner)
        )
    )
    assert "@" not in result, "PII processor did not redact email in typical output"


@pytest.mark.benchmark(group="payload")
def test_full_run_large_output(benchmark, bench_loop, manager_full, fake_agent, make_llm_response):
    """Full lifecycle over a ~11k-char output — surfaces size-dependent cost."""
    runner = _mock_runner_factory(make_llm_response(_LARGE, output_tokens=3000))

    result = benchmark(
        lambda: bench_loop.run_until_complete(
            manager_full.run(fake_agent, "summarize my invoices", "stub", runner)
        )
    )
    assert "@" not in result, "PII processor did not redact email in large output"


def test_lifecycle_overhead_scales_linearly_not_quadratically(
    bench_loop, manager_full, fake_agent, make_llm_response
):
    """Lifecycle cost scales ~linearly with output size, never quadratically.

    Not a benchmark: a behavioural guarantee. The PII output processor scans the
    whole response, so cost is expected to be O(text length) — a ~24x larger
    output costs roughly ~24x (measured ≈22x). What must NOT happen is
    super-linear growth: an accidental quadratic in the output path (e.g.
    repeated full-string copies or re-scans) would blow a 24x payload up to
    hundreds of x. We cap at 1.5x the linear size ratio: comfortably above honest
    linear cost, far below anything quadratic.
    """
    typical_runner = _mock_runner_factory(make_llm_response(_TYPICAL))
    large_runner = _mock_runner_factory(make_llm_response(_LARGE, output_tokens=3000))

    def _time(runner, prompt: str, repeats: int = 50) -> float:
        start = time.perf_counter()
        for _ in range(repeats):
            bench_loop.run_until_complete(manager_full.run(fake_agent, prompt, "stub", runner))
        return (time.perf_counter() - start) / repeats

    typical_s = _time(typical_runner, "typical")
    large_s = _time(large_runner, "large")

    size_ratio = len(_LARGE) / len(_TYPICAL)  # ~24x
    assert large_s < typical_s * (size_ratio * 1.5), (
        f"large-payload lifecycle {large_s * 1e6:.0f}us vs typical {typical_s * 1e6:.0f}us "
        f"= {large_s / typical_s:.1f}x for a {size_ratio:.0f}x payload — super-linear scaling"
    )
