"""Local multi-agent demo backend for the Argox stack.

Runs several ``@argox.monitor``-instrumented agents behind a tiny HTTP API and
serves a single-page front (``index.html``) coherent with the real dashboard.
Pick an agent in the UI, send it a prompt, and the run is:

  * routed through one shared :class:`RemotePolicyClient` that polls the
    Collector's merged policy bundle (``/api/v1/policies/bundle``) — so the same
    policies enforced fleet-wide gate every call here,
  * shipped to the Collector as OTel spans (OTLP ``/v1/traces``) and as a run
    record (``/v1/runs``), exactly like the deployed SDK path, and
  * captured in-process so the front can show the per-run metrics (tokens,
    latency, policy decisions, tools, trace id) right after the call.

Everything talks to the Collector through the dashboard's public surface
(``ARGOX_DASHBOARD_URL``, default ``http://localhost:8080``), the same single
entry point the deployed demo uses. ``run.sh`` brings up the Docker stack, mints
the API key, seeds the demo policy, and starts this server.

LLM backend (pick one via environment / .env):
  * Azure OpenAI: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT
  * OpenAI:       OPENAI_API_KEY [, OPENAI_MODEL=gpt-4o-mini]

Collector wiring (exported by run.sh):
  ARGOX_DASHBOARD_URL        public dashboard URL (proxies /api and /v1)
  ARGOX_COLLECTOR_API_KEY    key with read + ingest + policy-read scopes
"""

from __future__ import annotations

import asyncio
import contextvars
import os
from pathlib import Path
from typing import Any, Optional

try:
    import uvicorn
    from agents import (
        Agent,
        Runner,
        function_tool,
        set_default_openai_client,
        set_tracing_disabled,
    )
    from dotenv import load_dotenv
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse
    from openai import AsyncOpenAI
    from pydantic import BaseModel

    import argox
    from argox.core import init_telemetry
    from argox.core.state import AgentRunMetrics
    from argox.exporters import HttpRunExporter
    from argox.interfaces.exporter import ExporterBase
    from argox.observability import ConsoleSpanLogger, OTLPSpanExporter
    from argox.policies.remote_client import RemotePolicyClient
    from argox_openai import ArgoxOpenAIPlugin
except ModuleNotFoundError as exc:  # pragma: no cover - demo guard
    raise SystemExit(
        f"Missing dependency: {exc.name}. Install the SDK and demo extras:\n"
        "  pip install -e argox-project/argox-core "
        "-e argox-project/argox-plugins/argox-plugin-openai\n"
        "  pip install -r deploy/local/requirements.txt"
    ) from exc

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

DASHBOARD_URL = os.environ.get("ARGOX_DASHBOARD_URL", "http://localhost:8080").rstrip("/")
API_KEY = os.environ.get("ARGOX_COLLECTOR_API_KEY")
POLICY_REFRESH_S = int(os.environ.get("ARGOX_POLICY_REFRESH_S", "15"))
HOST = os.environ.get("DEMO_HOST", "127.0.0.1")
PORT = int(os.environ.get("DEMO_PORT", "8090"))


# --------------------------------------------------------------------------- #
# LLM backend (mirrors deploy/azure/demo_agent.py)
# --------------------------------------------------------------------------- #
def _make_client_and_model() -> tuple[AsyncOpenAI, str]:
    """Pick the LLM backend from the environment. Azure OpenAI preferred."""
    if os.environ.get("AZURE_OPENAI_API_KEY"):
        client = AsyncOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
        )
        return client, os.environ["AZURE_OPENAI_DEPLOYMENT"]
    if os.environ.get("OPENAI_API_KEY"):
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]), model
    raise SystemExit(
        "No LLM backend configured. Set AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT "
        "/ AZURE_OPENAI_DEPLOYMENT, or OPENAI_API_KEY (+ optional OPENAI_MODEL)."
    )


set_tracing_disabled(True)  # Argox owns the spans, silence the SDK's own tracer
_client, _model = _make_client_and_model()
set_default_openai_client(_client)


# --------------------------------------------------------------------------- #
# Tools shared by the demo agents
# --------------------------------------------------------------------------- #
@function_tool
def get_weather(city: str) -> str:
    """Return the current weather for a city (fake data)."""
    print(f"[tool:get_weather] city={city!r}")
    return f"It is sunny and 24C in {city}."


@function_tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert an amount between currencies (fake fixed rates)."""
    print(f"[tool:convert_currency] {amount} {from_currency}->{to_currency}")
    rate = 1.08 if from_currency.upper() == "EUR" else 0.92
    return f"{amount} {from_currency.upper()} = {round(amount * rate, 2)} {to_currency.upper()}"


@function_tool
def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression (digits and + - * / . () only)."""
    print(f"[tool:calculate] {expression!r}")
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        return "Refused: expression contains unsupported characters."
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307 - sandboxed chars
    except Exception as exc:  # pragma: no cover - demo guard
        return f"Could not evaluate: {exc}"


@function_tool
def get_secret(name: str) -> str:
    """Return a stored secret value. Demo of a tool a policy can block."""
    print(f"[tool:get_secret] name={name!r}")
    return f"The secret {name!r} is hunter2."


@function_tool
def search_docs(query: str) -> str:
    """Search an internal knowledge base (fake results)."""
    print(f"[tool:search_docs] query={query!r}")
    return f"Top result for {query!r}: Argox monitors agent runs end to end."


# --------------------------------------------------------------------------- #
# Agent catalog. Each entry becomes a selectable agent in the front.
# --------------------------------------------------------------------------- #
AGENTS: dict[str, dict[str, Any]] = {
    "weather-assistant": {
        "name": "Weather Assistant",
        "description": "Answers weather questions for any city.",
        "agent": Agent(
            name="weather-assistant",
            instructions="When the user asks for weather, you MUST call get_weather.",
            model=_model,
            tools=[get_weather],
        ),
        "examples": [
            "What's the weather in Madrid?",  # output alert: reply says "sunny"
            "Is it warm in Tokyo right now?",
            "nuke-the-prod weather in Madrid",  # input BLOCK (LOCAL-IN-01)
        ],
    },
    "travel-planner": {
        "name": "Travel Planner",
        "description": "Plans trips using weather and currency conversion tools.",
        "agent": Agent(
            name="travel-planner",
            instructions=(
                "Help plan trips. Use get_weather for conditions and "
                "convert_currency for budgets. Always call a tool when relevant."
            ),
            model=_model,
            tools=[get_weather, convert_currency],
        ),
        "examples": [
            "I'm flying to Lisbon. What's the weather and what is 200 EUR in USD?",
            "Convert 500 USD to EUR for my Paris trip.",
            "Plan a Rome trip on my salary; convert 1000 EUR to USD.",  # input alert (salary)
        ],
    },
    "math-tutor": {
        "name": "Math Tutor",
        "description": "Solves arithmetic step by step using a calculator tool.",
        "agent": Agent(
            name="math-tutor",
            instructions="Solve math problems. Use the calculate tool for arithmetic.",
            model=_model,
            tools=[calculate],
        ),
        "examples": [
            "What is (128 * 7) + 42?",
            "Compute 3600 / 15.",
            "What is 10% of my salary, 50000?",  # input alert (salary)
            "drop table users; what is 2 + 2?",  # input BLOCK (LOCAL-IN-02)
        ],
    },
    "research-bot": {
        "name": "Research Bot",
        "description": (
            "Searches the knowledge base. Also exposes get_secret to demo a "
            "tool the policy engine can block."
        ),
        "agent": Agent(
            name="research-bot",
            instructions=(
                "Answer questions using search_docs. Only use get_secret if "
                "explicitly asked for a secret."
            ),
            model=_model,
            tools=[search_docs, get_secret],
        ),
        "examples": [
            "What does Argox do?",  # tool alert: search_docs is flagged (LOCAL-TOOL-02)
            "Get me the secret named db_password.",  # tool BLOCK: get_secret stripped
            "What is my account password reset policy?",  # input alert (password)
        ],
    },
}


# --------------------------------------------------------------------------- #
# Telemetry, policy client, exporters
# --------------------------------------------------------------------------- #
def _build_span_exporters() -> list:
    """Console logger + OTLP exporter pointed at the dashboard's /v1/traces."""
    endpoint = f"{DASHBOARD_URL}/v1/traces"
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else None
    print(f"[otlp] shipping spans to {endpoint}")
    return [ConsoleSpanLogger(), OTLPSpanExporter(endpoint=endpoint, headers=headers)]


_tracer_provider = init_telemetry(exporters=_build_span_exporters())

# One RemotePolicyClient shared by every agent: it polls the merged bundle from
# the Collector and evaluates every input/output/tool call with zero hot-path I/O.
policy_client = RemotePolicyClient(
    endpoint_url=f"{DASHBOARD_URL}/api/v1/policies/bundle",
    refresh_interval_s=POLICY_REFRESH_S,
    api_key=API_KEY,
)

# Posts the run summary (prompt, output, tokens, tools) to the Collector's
# /v1/runs so the dashboard Run Record screen has data for each call.
run_exporter = HttpRunExporter(endpoint=DASHBOARD_URL, api_key=API_KEY, durable=True)


# ContextVar holds the per-request capture slot. The exporter runs synchronously
# inside the same coroutine as the request handler, so the var is visible.
_capture: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "argox_capture", default=None
)


class CaptureExporter(ExporterBase):
    """In-process exporter that stashes the run metrics into the request's slot."""

    def export(self, metrics: AgentRunMetrics) -> None:
        slot = _capture.get()
        if slot is not None:
            slot["metrics"] = metrics.to_dict()


capture_exporter = CaptureExporter()


def _make_runner(agent: Agent):
    """Wrap an agent in @argox.monitor with the shared policy + exporters."""

    @argox.monitor(
        plugin=ArgoxOpenAIPlugin(),
        agent=agent,
        policy=policy_client,
        exporters=[run_exporter, capture_exporter],
    )
    async def _run(agent: Agent, prompt: str):
        return await Runner.run(agent, prompt)

    return _run


RUNNERS = {agent_id: _make_runner(entry["agent"]) for agent_id, entry in AGENTS.items()}


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #
class RunRequest(BaseModel):
    agent: str
    prompt: str


app = FastAPI(title="Argox local agent demo")


@app.on_event("startup")
async def _startup() -> None:
    await policy_client.start()
    print(f"[policy] polling {policy_client.endpoint_url} every {POLICY_REFRESH_S}s")


@app.on_event("shutdown")
async def _shutdown() -> None:
    await policy_client.stop()


@app.get("/api/config")
async def config() -> dict:
    return {"dashboard_url": DASHBOARD_URL}


@app.get("/api/agents")
async def list_agents() -> dict:
    return {
        "agents": [
            {
                "id": agent_id,
                "name": entry["name"],
                "description": entry["description"],
                "tools": [t.name for t in entry["agent"].tools],
                "examples": entry["examples"],
            }
            for agent_id, entry in AGENTS.items()
        ]
    }


@app.post("/api/run")
async def run(req: RunRequest) -> JSONResponse:
    runner = RUNNERS.get(req.agent)
    if runner is None:
        return JSONResponse({"error": f"unknown agent {req.agent!r}"}, status_code=404)

    slot: dict = {}
    token = _capture.set(slot)
    try:
        result = await runner(req.prompt)
        final_output = getattr(result, "final_output", str(result))
    except Exception as exc:  # surface run errors to the front instead of 500
        return JSONResponse(
            {"error": f"{type(exc).__name__}: {exc}", "metrics": slot.get("metrics")},
            status_code=200,
        )
    finally:
        _capture.reset(token)
        # Flush the span batch so the trace is visible in the dashboard promptly.
        await asyncio.to_thread(_tracer_provider.force_flush)

    return JSONResponse(
        {
            "agent": req.agent,
            "final_output": final_output,
            "metrics": slot.get("metrics"),
            "dashboard_url": DASHBOARD_URL,
        }
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(HERE / "index.html")


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit(
            "ARGOX_COLLECTOR_API_KEY unset. Run this via deploy/local/run.sh, "
            "which mints a key and seeds the demo policy."
        )
    print(f"\n  Demo front:  http://{HOST}:{PORT}")
    print(f"  Dashboard:   {DASHBOARD_URL}\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
