"""Synthetic trace generator for the live dashboard demo.

Drives the Argox SDK (``ArgoxManager``) in a loop with a fake plugin/runner so
no real LLM provider or credentials are needed. Each iteration:

  1. Runs one agent execution, which the SDK wraps in an ``argox.agent.run``
     OTel span and ships to the Collector over OTLP/HTTP (``POST /v1/traces``).
  2. Posts the matching run summary to ``POST /v1/runs`` so the Query API's
     success-rate, cost and per-span ``run_success`` fields are populated and
     the trace can be joined back to its run via ``trace_id``.

The span exporter is force-flushed after every run so traces appear in the
front almost instantly instead of waiting for the batch timer.

Run from ``argox-project/`` with the Collector already listening (auth off):

    python examples/live_demo/trace_generator.py --endpoint http://localhost:8000

See ``demo_live.sh`` for the orchestrated version that boots everything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

from opentelemetry import trace

import argox
from argox.core import init_telemetry
from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.observability import OTLPSpanExporter

# Rough per-token prices (USD) used only to fabricate a believable cost on the
# demo run records. Not tied to any real provider tariff.
_PRICE_INPUT = 0.000005
_PRICE_OUTPUT = 0.000015

# A small cast of agents/prompts so the live list shows variety.
_AGENTS = ["triage-bot", "support-agent", "research-assistant", "billing-helper"]
_PROMPTS = [
    "Summarize the latest support ticket.",
    "What is the refund policy for enterprise plans?",
    "Draft a reply to the customer complaint.",
    "Look up the order status for account 4821.",
    "Explain the difference between the Pro and Team tiers.",
]


class _FakeResponse:
    """Stand-in for a framework's raw result object."""

    def __init__(self, text: str, input_tokens: int, output_tokens: int) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens


class _FakeAgent:
    """Minimal agent object exposing the ``name``/``tools`` the SDK reads."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: list = []


class _FakePlugin(ArgoxPlugin):
    """No-op plugin that reports the fake response's token usage."""

    @property
    def name(self) -> str:
        return "fake"

    def instrument(
        self, target: Any, metrics: AgentRunMetrics, tool_args_runner: Any = None
    ) -> Any:
        return target

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        if isinstance(raw_result, _FakeResponse):
            metrics.api_calls.append(
                ApiCallRecord(
                    call_number=1,
                    input_tokens=raw_result.input_tokens,
                    output_tokens=raw_result.output_tokens,
                    total_tokens=raw_result.total_tokens,
                )
            )

    def extract_output(self, raw_result: Any) -> str:
        return raw_result.text if isinstance(raw_result, _FakeResponse) else str(raw_result)


class _DecidedPolicy(PolicyClient):
    """Blocks the output iff the run was pre-decided to fail.

    The success/failure of each demo run is chosen up front so the run span can
    be tagged accordingly; this policy just turns that decision into a real
    output-policy block (ERROR status + ``argox.policy.decision=block``) for the
    runs meant to fail, keeping the dashboard's success rate visibly < 100%.
    """

    def __init__(self, block: bool) -> None:
        self._block = block

    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        if self._block:
            return PolicyResult.block(reason="output flagged by demo policy", rule_id="DEMO-1")
        return PolicyResult.ok()


class _CapturingExporter(ExporterBase):
    """Keeps the most recent run's metrics so we can post the run summary."""

    def __init__(self) -> None:
        self.last: Optional[AgentRunMetrics] = None

    def export(self, metrics: AgentRunMetrics) -> None:
        self.last = metrics


def _make_runner(captured: dict, agent_name: str, succeed: bool) -> Any:
    """Build a runner that tags the active ``argox.agent.run`` span.

    The Manager opens the span before calling the runner, so inside the runner
    that span is current. The Collector promotes a handful of span attributes
    into the queryable index, so setting them here is what makes the dashboard's
    list and metrics light up without any post-processing:

      * ``argox.agent.name``  -> per-row agent name (else the service name)
      * ``argox.run.success`` -> success-rate metric and per-span outcome
      * ``argox.run.cost``    -> cost metric and per-row cost

    The span's trace_id is also captured so the run summary posted to
    ``/v1/runs`` can be joined back to this trace.
    """

    async def _runner(agent: Any, prompt: str) -> _FakeResponse:
        span = trace.get_current_span()
        captured["trace_id"] = format(span.get_span_context().trace_id, "032x")

        input_tokens = random.randint(40, 400)
        output_tokens = random.randint(20, 600)
        cost = round(input_tokens * _PRICE_INPUT + output_tokens * _PRICE_OUTPUT, 6)
        captured["cost"] = cost

        span.set_attribute("argox.agent.name", agent_name)
        span.set_attribute("argox.agent.version", "1.0.0")
        span.set_attribute("argox.run.success", succeed)
        span.set_attribute("argox.run.cost", cost)

        # Simulate work so latency metrics are non-zero and visibly varied.
        await asyncio.sleep(random.uniform(0.05, 0.4))
        return _FakeResponse(
            text=f"response to: {prompt}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    return _runner


def _post_run(
    runs_url: str, metrics: AgentRunMetrics, trace_id: Optional[str], cost: float
) -> None:
    """POST a run summary to the Collector, committed synchronously (durable)."""
    payload = metrics.to_dict()
    if trace_id:
        payload["trace_id"] = trace_id
    payload["cost_usd"] = cost
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        runs_url,
        data=data,
        headers={"Content-Type": "application/json", "X-Argox-Durable": "true"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    except urllib.error.URLError as exc:
        print(f"  ! run summary POST failed: {exc}", file=sys.stderr)


async def _run_once(provider, runs_url: str, block_rate: float) -> None:
    """Execute one synthetic agent run and ship its trace + run summary."""
    agent = _FakeAgent(random.choice(_AGENTS))
    prompt = random.choice(_PROMPTS)
    succeed = random.random() >= block_rate

    capturing = _CapturingExporter()
    manager = ArgoxManager(policy=_DecidedPolicy(block=not succeed))
    manager.register_plugin(_FakePlugin())
    manager.register_exporter(capturing)

    captured: dict = {}
    try:
        await manager.run(agent, prompt, "fake", _make_runner(captured, agent.name, succeed))
    except PermissionError:
        # Policy block: the SDK already recorded the failed run in `capturing`.
        pass

    # Push the span out now instead of waiting for the batch timer.
    provider.force_flush()

    metrics = capturing.last
    if metrics is not None:
        _post_run(runs_url, metrics, captured.get("trace_id"), captured.get("cost", 0.0))
        flag = "ok   " if succeed else "BLOCK"
        print(
            f"  [{flag}] {agent.name:<18} "
            f"in={metrics.total_input_tokens:<4} out={metrics.total_output_tokens:<4} "
            f"${captured.get('cost', 0.0):<8} trace={captured.get('trace_id', '-')[:12]}"
        )


async def _main_async(args: argparse.Namespace) -> None:
    base = args.endpoint.rstrip("/")
    traces_url = f"{base}/v1/traces"
    runs_url = f"{base}/v1/runs"

    provider = init_telemetry(
        service_name="argox-live-demo",
        exporters=[OTLPSpanExporter(endpoint=traces_url)],
    )

    print(f"Generating traces -> {traces_url}")
    print(f"Posting run summaries -> {runs_url}")
    print("Press Ctrl-C to stop.\n")

    emitted = 0
    try:
        while args.count == 0 or emitted < args.count:
            await _run_once(provider, runs_url, args.block_rate)
            emitted += 1
            await asyncio.sleep(args.interval)
    finally:
        provider.force_flush()
        print(f"\nDone. Emitted {emitted} run(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("ARGOX_COLLECTOR_BASE", "http://localhost:8000"),
        help="Collector base URL (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="Seconds to wait between runs (default: 1.5).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of runs to emit; 0 means run forever (default: 0).",
    )
    parser.add_argument(
        "--block-rate",
        type=float,
        default=0.2,
        help="Fraction of runs blocked by policy, 0..1 (default: 0.2).",
    )
    args = parser.parse_args()

    # Touch the package so a misconfigured environment fails loudly and early.
    _ = argox.__name__

    try:
        asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
