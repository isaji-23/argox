"""Overhead benchmark: Argox-monitored agent vs. the same agent unmonitored.

Runs the *same* agent ``N`` times with and without the Argox SDK and reports
the mean (plus stdev / min / max) wall-clock time of each, so the per-run cost
of policy evaluation, processor mutation, and span/metrics export is visible
over a sample rather than a single noisy call.

Caveat: LLM latency dominates and varies per call, so this is indicative, not a
microbenchmark. Runs are *alternated* (baseline, monitored, baseline, ...) to
spread network drift evenly across both groups, and a warm-up run is discarded.

Requires the same environment as ``demo_azure_openai.py`` (load via ``.env`` at
the ``argox-project`` directory):

- ``AZURE_OPENAI_API_KEY``
- ``AZURE_OPENAI_ENDPOINT``
- ``AZURE_OPENAI_DEPLOYMENT``

Run from ``argox-project/``::

    python examples/benchmark_overhead.py [N]      # N defaults to 5

The repetition count can also be set via the ``ARGOX_BENCH_RUNS`` env var; the
positional CLI argument takes precedence when both are present.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from agents import (
    Agent,
    Runner,
    function_tool,
    set_default_openai_client,
    set_tracing_disabled,
)
from dotenv import load_dotenv
from openai import AsyncOpenAI
import argox
from argox.core import init_telemetry
from argox.core.state import AgentRunMetrics
from argox.interfaces.exporter import ExporterBase
from argox.observability import ConsoleSpanLogger, JsonlSpanExporter
from argox.policies import LocalPolicyClient
from argox.processors import PiiRedactionProcessor

from argox_openai import ArgoxOpenAIPlugin

_EXAMPLES_DIR = Path(__file__).resolve().parent
_POLICY_PATH = _EXAMPLES_DIR / "policies" / "demo_policy.yaml"
_SPANS_PATH = _EXAMPLES_DIR / "run_artifacts" / "benchmark_spans.jsonl"

_DEFAULT_RUNS = 5
_PROMPT = (
    "Log that user@example.com just checked the forecast, "
    "and tell me the weather in Madrid."
)


load_dotenv()
set_tracing_disabled(True)
set_default_openai_client(
    AsyncOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
    )
)


# Quiet variants of the demo tools — no per-call prints, so stdout I/O does not
# skew the timing between the two groups.
@function_tool
def get_weather(city: str) -> str:
    """Return the current weather for a city (fake data)."""
    return f"It is sunny and 24C in {city}."


@function_tool
def get_current_datetime() -> str:
    """Return the current date and time."""
    return datetime.now().isoformat()


@function_tool
def log_user_activity(email: str, action: str) -> str:
    """Persist a user activity record (fake sink)."""
    return f"logged action={action!r} for {email}"


class _SilentMetricsExporter(ExporterBase):
    """Real exporter whose export is a no-op.

    Kept in the monitored path so the metrics-collection cost is counted, while
    avoiding per-run console output that would pollute the benchmark.
    """

    def export(self, metrics: AgentRunMetrics) -> None:
        return None


# Span export still happens (so its cost is counted), but the human-readable
# console logger is pointed at the null device to avoid per-run spam.
init_telemetry(
    exporters=[
        ConsoleSpanLogger(out=open(os.devnull, "w")),
        JsonlSpanExporter(_SPANS_PATH),
    ],
)

agent = Agent(
    name="weather-assistant",
    instructions=(
        "Use the available tools to answer the user's request. "
        "When the user asks you to record or log an activity, you MUST call "
        "the log_user_activity tool with the email and a short action string. "
        "When the user asks for weather, you MUST call get_weather."
    ),
    model=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
    tools=[get_weather, get_current_datetime, log_user_activity],
)


@argox.monitor(
    plugin=ArgoxOpenAIPlugin(),
    agent=agent,
    policy=LocalPolicyClient(_POLICY_PATH),
    processors=[PiiRedactionProcessor()],
    exporters=[_SilentMetricsExporter()],
)
async def run_agent_monitored(agent: Agent, prompt: str):
    return await Runner.run(agent, prompt)


async def run_agent_baseline(prompt: str):
    """Run the same agent directly, bypassing the Argox SDK."""
    return await Runner.run(agent, prompt)


async def _timed(coro) -> float:
    """Await ``coro`` and return its wall-clock duration in seconds."""
    start = time.perf_counter()
    await coro
    return time.perf_counter() - start


def _resolve_runs() -> int:
    """Resolve the repetition count from argv, then env, then the default."""
    if len(sys.argv) > 1:
        return max(1, int(sys.argv[1]))
    return max(1, int(os.environ.get("ARGOX_BENCH_RUNS", _DEFAULT_RUNS)))


def _summarize(label: str, samples: list[float]) -> None:
    """Print mean/stdev/min/max for a group of run times."""
    mean = statistics.mean(samples)
    stdev = statistics.stdev(samples) if len(samples) > 1 else 0.0
    print(
        f"[{label:<10}] n={len(samples)} "
        f"mean={mean:.2f}s stdev={stdev:.2f}s "
        f"min={min(samples):.2f}s max={max(samples):.2f}s"
    )


async def main() -> None:
    runs = _resolve_runs()

    # Warm-up run (discarded) to absorb client/connection cold-start cost.
    print("Warming up...")
    await run_agent_baseline(_PROMPT)

    baseline_times: list[float] = []
    monitored_times: list[float] = []

    print(f"Benchmarking {runs} run(s) per group (alternating)...")
    for i in range(1, runs + 1):
        # Alternate so any network drift is shared evenly across both groups.
        baseline_times.append(await _timed(run_agent_baseline(_PROMPT)))
        monitored_times.append(await _timed(run_agent_monitored(_PROMPT)))
        print(
            f"  run {i}/{runs}: "
            f"baseline={baseline_times[-1]:.2f}s "
            f"monitored={monitored_times[-1]:.2f}s"
        )

    print("\n=== Results ===")
    _summarize("baseline", baseline_times)
    _summarize("monitored", monitored_times)

    overhead = statistics.mean(monitored_times) - statistics.mean(baseline_times)
    baseline_mean = statistics.mean(baseline_times)
    pct = (overhead / baseline_mean * 100) if baseline_mean else 0.0
    print(f"[overhead  ] mean={overhead:+.2f}s ({pct:+.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
