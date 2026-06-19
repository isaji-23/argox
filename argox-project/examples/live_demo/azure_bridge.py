"""HTTP bridge that fires a single Azure OpenAI agent run on demand.

The live dashboard (``index.html``) is a static page that can only *poll* the
Collector's read-only Query API; it has no way to *start* an agent run. This
bridge fills that gap: it exposes one small HTTP endpoint the page can POST to,
runs the real Azure OpenAI agent wrapped in ``@argox.monitor`` once per request,
ships the resulting span to the Collector over OTLP, posts the matching run
summary to ``POST /v1/runs`` (so the dashboard's success-rate and cost light up
exactly like the synthetic generator does), and returns the agent's answer.

It is deliberately *not* ``demo_azure_openai.py``: that script runs a baseline
vs. monitored comparison once and exits. This bridge stays up and runs a fresh
monitored query each time the button is pressed — nothing else.

Run from ``argox-project/`` with the Collector already listening and
``examples/.env`` populated with ``AZURE_OPENAI_*``::

    python examples/live_demo/azure_bridge.py --collector http://localhost:8000

Then press the "Ask Azure" button on the dashboard. Endpoint contract:

    POST /ask   {"prompt": "..."}  ->  {"answer": "...", "trace_id": "...",
                                        "success": true}

Cost is not returned here: the bridge tags the span with the model and the SDK
records token usage, so the Collector's enricher prices the run at ingest and
the dashboard's cost card fills in on its next poll. The run's model must match
a key in the Collector's pricing.yaml (set AZURE_OPENAI_MODEL if the Azure
deployment name differs from the model id, e.g. "gpt-4o").
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from agents import (
    Agent,
    Runner,
    function_tool,
    set_default_openai_client,
    set_tracing_disabled,
)
from dotenv import load_dotenv
from openai import AsyncOpenAI
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

import argox
from argox.core import init_telemetry
from argox.core.state import AgentRunMetrics
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.policy import PolicyResult
from argox.observability import OTLPSpanExporter
from argox.policies import LocalPolicyClient
from argox.processors import PiiRedactionProcessor
from argox_openai import ArgoxOpenAIPlugin

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent
_POLICY_PATH = _EXAMPLES_DIR / "policies" / "demo_policy.yaml"

# Tracer used to open a child span per tool call. get_tracer returns a proxy
# that resolves the global provider lazily, so it is safe to build at import
# time (before init_telemetry installs the provider in the bridge __init__).
# Each tool runs inside Runner.run while the argox.agent.run span is current,
# so these spans attach to it as children and the dashboard waterfall shows the
# real tool-call breakdown instead of a single root span.
_tracer = trace.get_tracer("argox-azure-demo")

# Holds the OTel context captured at the start of each run (the context in which
# the argox.agent.run span is current). Tools read it to parent their child span
# explicitly, so the tool span lands in the same trace even if the agents SDK
# runs the tool in a worker thread or a task that lost the ambient context.
# A ContextVar (not a global) keeps this correct under concurrent requests:
# each run/task — and each thread spawned via asyncio.to_thread, which copies
# the context — sees its own value.
_run_ctx_var: contextvars.ContextVar = contextvars.ContextVar(
    "argox_run_ctx", default=None
)

# Per-run list of tools the policy blocked, recorded by _RecordingPolicy as the
# SDK evaluates each tool. A ContextVar (reset at the start of every ask) keeps
# it correct under the threaded HTTP server: each request's asyncio.run copies
# the context, so concurrent runs never share a list.
_blocked_tools_var: contextvars.ContextVar = contextvars.ContextVar(
    "argox_blocked_tools", default=None
)

# A prompt that exercises every tool in one run: weather (allowed), activity log
# (allowed, with a PII e-mail the redaction processor scrubs) and the current
# date/time (blocked by policy DEMO-TOOL-01). Shown in the dashboard input and
# used when the box is left empty.
_DEFAULT_PROMPT = (
    "Log that user@example.com just checked the forecast, tell me the weather "
    "in Madrid, and what is the current date and time?"
)


@function_tool
def get_weather(city: str) -> str:
    """Return the current weather for a city (fake data)."""
    with _tracer.start_as_current_span(
        "tool.get_weather", context=_run_ctx_var.get()
    ) as span:
        span.set_attribute("tool.name", "get_weather")
        span.set_attribute("tool.arg.city", city)
        print(f"[tool:get_weather] received: city={city!r}")
        # Roughly half the time, simulate a slow upstream so the dashboard
        # waterfall shows a visibly long bar for this tool span. Synchronous
        # sleep is fine: the agents SDK runs sync tools in a worker thread.
        if random.random() < 0.5:
            delay = random.uniform(1.5, 2.5)
            span.set_attribute("tool.slow", True)
            time.sleep(delay)
        result = f"It is sunny and 24C in {city}."
        span.set_attribute("tool.result", result)
        return result


@function_tool
def log_user_activity(email: str, action: str) -> str:
    """Persist a user activity record (fake sink — prints what it received)."""
    with _tracer.start_as_current_span(
        "tool.log_user_activity", context=_run_ctx_var.get()
    ) as span:
        span.set_attribute("tool.name", "log_user_activity")
        span.set_attribute("tool.arg.email", email)
        span.set_attribute("tool.arg.action", action)
        print(f"[tool:log_user_activity] received: email={email!r} action={action!r}")
        result = f"logged action={action!r} for {email}"
        span.set_attribute("tool.result", result)
        return result


@function_tool
def get_current_datetime() -> str:
    """Return the current date and time (blocked by policy in this demo)."""
    # The policy (DEMO-TOOL-01) blocks this tool, so the SDK strips it before the
    # run and the model never reaches this body. It returns a refusal just in
    # case a framework keeps the tool callable; the visible "blocked" span in the
    # waterfall is emitted from the recorded policy decision (see run_agent).
    return "[blocked by policy] get_current_datetime is not permitted"


class _RecordingPolicy(LocalPolicyClient):
    """Local policy that also records which tools it blocks for the current run.

    Behaviour is identical to ``LocalPolicyClient`` — the real rules in
    ``demo_policy.yaml`` decide everything — but each blocking tool decision is
    appended to the per-run list in ``_blocked_tools_var`` so the run can render
    a "blocked" span for it in the dashboard waterfall.
    """

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        result = await super().is_tool_allowed(tool_name)
        if not result.passed:
            blocked = _blocked_tools_var.get()
            if blocked is not None:
                blocked.append(
                    {
                        "name": tool_name,
                        "rule_id": result.rule_id,
                        "reason": result.reason,
                    }
                )
        return result


class _CapturingExporter(ExporterBase):
    """Keeps the most recent run's metrics so we can post the run summary."""

    def __init__(self) -> None:
        self.last: Optional[AgentRunMetrics] = None

    def export(self, metrics: AgentRunMetrics) -> None:
        self.last = metrics


class AzureAgentBridge:
    """Wires the monitored Azure agent once and runs it per request.

    The OpenAI client, telemetry pipeline and ``@argox.monitor`` decoration are
    built a single time at construction; ``ask`` then executes one fresh run
    against that fixed wiring, captures the run's ``trace_id`` and metrics, and
    posts the run summary so the Collector can join span to run.
    """

    def __init__(self, collector_base: str) -> None:
        base = collector_base.rstrip("/")
        self._runs_url = f"{base}/v1/runs"
        traces_url = f"{base}/v1/traces"

        # Bare call: walk up from the CWD (run from argox-project/) so the same
        # .env demo_azure_openai.py uses is picked up automatically.
        load_dotenv()
        set_tracing_disabled(True)
        set_default_openai_client(
            AsyncOpenAI(
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
            )
        )

        self._agent = Agent(
            name="weather-assistant",
            instructions=(
                "Use the available tools to answer the user's request. Call "
                "get_weather once for a weather question and log_user_activity "
                "once to record an activity (with the email and a short action "
                "string). Call each tool at most once. If the user asks for "
                "something no available tool can provide (for example the "
                "current date or time), briefly say you cannot and finish — do "
                "NOT retry tools. Then give a short final answer."
            ),
            model=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
            # get_current_datetime is intentionally included so the policy can
            # block it: it is stripped before the run and surfaces as a blocked
            # span in the dashboard waterfall.
            tools=[get_weather, log_user_activity, get_current_datetime],
        )

        # Model name the Collector's cost enricher (COL-07) prices the run by.
        # It must match a key in the Collector's pricing.yaml (e.g. "gpt-4o").
        # Azure deployment names often differ from the model id, so allow an
        # explicit override via AZURE_OPENAI_MODEL; otherwise fall back to the
        # deployment name.
        self._model = (
            os.environ.get("AZURE_OPENAI_MODEL")
            or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        )

        # Capturing exporter feeds the /v1/runs summary; OTLP exporter ships the
        # span to the Collector so the trace row appears in the dashboard.
        self._captured: dict = {}
        capturing = _CapturingExporter()
        self._capturing = capturing
        agent = self._agent
        captured = self._captured
        model = self._model

        self._provider = init_telemetry(
            service_name="argox-azure-demo",
            exporters=[OTLPSpanExporter(endpoint=traces_url)],
        )

        @argox.monitor(
            plugin=ArgoxOpenAIPlugin(),
            agent=agent,
            policy=_RecordingPolicy(_POLICY_PATH),
            processors=[PiiRedactionProcessor()],
            exporters=[capturing],
        )
        async def run_agent(agent: Agent, prompt: str):
            # The Manager opens the argox.agent.run span before calling this
            # runner, so it is the current span here. Set the attributes the
            # Collector promotes into queryable span columns / enriches on:
            #   * argox.agent.name   -> per-row agent name in the dashboard
            #   * gen_ai.request.model -> the Collector's cost enricher (COL-07)
            #     prices the run from this + the token usage the SDK records, so
            #     the cost card is populated by the Collector, not faked here.
            #   * argox.run.success  -> the success-rate card; set True once the
            #     run returns (a tool/runner failure raises and leaves it unset,
            #     so it is excluded from the rate rather than counted as success).
            # The trace_id is captured so the /v1/runs summary joins back.
            span = trace.get_current_span()
            captured["trace_id"] = format(span.get_span_context().trace_id, "032x")
            # Capture this context so the tools parent their child spans to this
            # exact run span (see _run_ctx_var).
            _run_ctx_var.set(otel_context.get_current())
            span.set_attribute("argox.agent.name", agent.name)
            span.set_attribute("argox.agent.version", "1.0.0")
            if model:
                span.set_attribute("gen_ai.request.model", model)

            # The Manager has already evaluated every tool against the policy by
            # the time this runner is called (tools are filtered before the
            # agent executes), so _blocked_tools_var now lists what was blocked.
            # Emit a short child span per blocked tool, tagged with the policy
            # decision the Collector promotes into the queryable policy_decision
            # column, so the dashboard waterfall shows it as a red, blocked row.
            for blocked in _blocked_tools_var.get() or []:
                with _tracer.start_as_current_span(
                    f"tool.{blocked['name']}", context=_run_ctx_var.get()
                ) as bspan:
                    bspan.set_attribute("tool.name", blocked["name"])
                    bspan.set_attribute("tool.blocked", True)
                    bspan.set_attribute("argox.policy.decision", "block")
                    if blocked["rule_id"]:
                        bspan.set_attribute("argox.policy.rule_id", blocked["rule_id"])
                    if blocked["reason"]:
                        bspan.set_attribute("argox.policy.reason", blocked["reason"])
                    bspan.set_status(
                        Status(StatusCode.ERROR, blocked["reason"] or "blocked by policy")
                    )

            # Cap the agent loop: the blocked tool is stripped before the run,
            # so the model cannot satisfy a date/time request and would
            # otherwise burn turns retrying the allowed tools up to the default
            # of 10. A small ceiling keeps the demo run fast and predictable.
            result = await Runner.run(agent, prompt, max_turns=4)
            span.set_attribute("argox.run.success", True)
            return result

        self._run_agent = run_agent

    async def ask(self, prompt: str) -> dict:
        """Run one monitored Azure query and ship its trace + run summary."""
        self._captured.clear()
        # Fresh per-run list the recording policy appends blocked tools to.
        _blocked_tools_var.set([])
        answer: str
        success: bool
        try:
            answer = str(await self._run_agent(prompt))
            success = True
        except PermissionError as exc:
            # Output/tool policy blocked the run; the SDK still recorded it.
            answer = f"[blocked by policy] {exc}"
            success = False

        # Push the span out now instead of waiting for the batch timer. The
        # Collector enriches the span's cost from the model + token usage at
        # ingest, so the cost card fills in on the dashboard's next poll.
        self._provider.force_flush()

        metrics = self._capturing.last
        trace_id = self._captured.get("trace_id")
        if metrics is not None:
            # Mirror the SDK's run-summary export (EXP-09): powers the trace
            # detail's per-span outcome join. cost_usd is left unset — the
            # Collector prices the run, we do not fabricate it here.
            self._post_run(metrics, trace_id)

        return {
            "answer": answer,
            "trace_id": trace_id,
            "success": success,
        }

    def _post_run(
        self, metrics: AgentRunMetrics, trace_id: Optional[str]
    ) -> None:
        """POST a run summary to the Collector, committed synchronously."""
        payload = metrics.to_dict()
        if trace_id:
            payload["trace_id"] = trace_id
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._runs_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Argox-Durable": "true",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except urllib.error.URLError as exc:
            print(f"  ! run summary POST failed: {exc}", file=sys.stderr)


def _make_handler(bridge: AzureAgentBridge, allow_origin: str):
    class Handler(BaseHTTPRequestHandler):
        # Quieter logs: one line per run is enough for a demo.
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
            return

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/ask":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                prompt = (json.loads(raw or b"{}").get("prompt") or "").strip()
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON body"})
                return
            prompt = prompt or _DEFAULT_PROMPT

            print(f"[ask] {prompt}")
            try:
                result = asyncio.run(bridge.ask(prompt))
            except Exception as exc:  # surface a clean error to the browser
                print(f"  ! run failed: {exc}", file=sys.stderr)
                self._json(500, {"error": str(exc)})
                return
            flag = "ok   " if result["success"] else "BLOCK"
            print(f"  [{flag}] trace={str(result['trace_id'])[:12]}")
            self._json(200, result)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collector",
        default=os.environ.get("ARGOX_COLLECTOR_BASE", "http://localhost:8000"),
        help="Collector base URL (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AZURE_BRIDGE_PORT", "8002")),
        help="Port for this bridge to listen on (default: 8002).",
    )
    parser.add_argument(
        "--bind",
        default=os.environ.get("AZURE_BRIDGE_BIND", "127.0.0.1"),
        help="Address to bind (default: 127.0.0.1; use 0.0.0.0 to expose).",
    )
    parser.add_argument(
        "--allow-origin",
        default=os.environ.get("AZURE_BRIDGE_ALLOW_ORIGIN", "*"),
        help="CORS Access-Control-Allow-Origin value (default: *).",
    )
    args = parser.parse_args()

    # Touch the package so a misconfigured environment fails loudly and early.
    _ = argox.__name__

    bridge = AzureAgentBridge(args.collector)
    handler = _make_handler(bridge, args.allow_origin)
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"Azure bridge listening on http://{args.bind}:{args.port}/ask")
    print(f"Posting traces + run summaries -> {args.collector}")
    print("Press Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
