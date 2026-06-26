"""Minimal Argox-monitored agent against a deployed Collector.

Runs ONE simple agent call (single tool) wrapped in ``@argox.monitor`` and ships
the resulting OTel spans to the Argox Collector over OTLP/HTTP. The Collector
prices the run and exposes it through ``/api/v1/metrics/*`` — ``demo.sh`` runs
this script and then prints those metrics.

LLM backend (pick one via environment):
  * OpenAI:       OPENAI_API_KEY [, OPENAI_MODEL=gpt-4o-mini]
  * Azure OpenAI: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT

Collector wiring (exported by demo.sh):
  ARGOX_COLLECTOR_ENDPOINT   https://<dashboard-fqdn>/v1/traces
  ARGOX_COLLECTOR_API_KEY    key with the ``ingest`` scope

The OpenAI Agents SDK is the only agent framework Argox ships a plugin for
(``argox-plugin-openai``); pointing its client at Azure OpenAI is the supported
way to run against an Azure-hosted model.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

try:
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
    from argox.exporters import HttpRunExporter
    from argox.observability import ConsoleSpanLogger, OTLPSpanExporter
    from argox_openai import ArgoxOpenAIPlugin
except ModuleNotFoundError as exc:  # pragma: no cover - demo guard
    raise SystemExit(
        f"Missing dependency: {exc.name}. Install the SDK and demo extras, e.g.\n"
        "  pip install -e argox-project/argox-core "
        "-e argox-project/argox-plugins/argox-plugin-openai\n"
        "  pip install openai openai-agents python-dotenv"
    ) from exc

# Load this directory's .env so the LLM + Collector vars are configurable in one
# place. demo.sh also sources it, but loading here keeps the script runnable on
# its own. Existing environment values win over .env (override=False default).
load_dotenv(Path(__file__).resolve().parent / ".env")


def _make_client_and_model() -> tuple[AsyncOpenAI, str]:
    """Pick the LLM backend from the environment. Azure OpenAI is preferred
    (same cloud as the deploy); plain OpenAI is the fallback.

    Azure OpenAI is reached through its OpenAI-compatible v1 surface: the
    endpoint already includes ``/openai/v1/`` (e.g.
    ``https://<resource>.openai.azure.com/openai/v1/``), so the standard
    ``AsyncOpenAI`` client works directly with ``base_url`` set to that endpoint
    and the Azure *deployment* name passed as the model. This mirrors
    argox-project/examples/demo_azure_openai.py. (Do not use ``AsyncAzureOpenAI``
    here: it would re-append ``/openai/deployments/...`` and 404.)
    """
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


set_tracing_disabled(True)  # silence the OpenAI SDK's own tracer; Argox owns spans
_client, _model = _make_client_and_model()
set_default_openai_client(_client)


@function_tool
def get_weather(city: str) -> str:
    """Return the current weather for a city (fake data)."""
    print(f"[tool:get_weather] city={city!r}")
    return f"It is sunny and 24C in {city}."


def _build_exporters() -> list:
    """Console logger + OTLP exporter pointed at the deployed Collector."""
    endpoint = os.environ.get("ARGOX_COLLECTOR_ENDPOINT")
    if not endpoint:
        raise SystemExit("ARGOX_COLLECTOR_ENDPOINT unset (run this via demo.sh).")
    headers = {}
    key = os.environ.get("ARGOX_COLLECTOR_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    print(f"[otlp] shipping spans to {endpoint}")
    return [ConsoleSpanLogger(), OTLPSpanExporter(endpoint=endpoint, headers=headers or None)]


def _build_run_exporter() -> "HttpRunExporter":
    """Post the run summary (prompt, final output, tool calls, tokens) to the
    Collector's ``/v1/runs`` so the dashboard Run Record screen has data.

    The OTLP path above only ships spans; the Run Record is backed by a separate
    ``AgentRunMetrics`` payload that ``@argox.monitor`` hands to its registered
    exporters. ``ARGOX_COLLECTOR_ENDPOINT`` points at the OTLP ``/v1/traces``
    path, so strip that suffix to get the Collector base; ``HttpRunExporter``
    appends ``/v1/runs`` itself. ``durable=True`` requests synchronous
    persistence so the record is committed before this short-lived script exits.
    """
    endpoint = os.environ.get("ARGOX_COLLECTOR_ENDPOINT")
    if not endpoint:
        raise SystemExit("ARGOX_COLLECTOR_ENDPOINT unset (run this via demo.sh).")
    base = endpoint.removesuffix("/v1/traces")
    key = os.environ.get("ARGOX_COLLECTOR_API_KEY")
    print(f"[runs] posting run records to {base}/v1/runs")
    return HttpRunExporter(endpoint=base, api_key=key, durable=True)


# Keep the provider so we can force_flush the BatchSpanProcessor before exit;
# a short-lived script would otherwise drop the pending OTLP batch.
_tracer_provider = init_telemetry(exporters=_build_exporters())

agent = Agent(
    name="weather-assistant",
    instructions="When the user asks for weather, you MUST call get_weather.",
    model=_model,
    tools=[get_weather],
)


@argox.monitor(
    plugin=ArgoxOpenAIPlugin(),
    agent=agent,
    exporters=[_build_run_exporter()],
)
async def run_agent(agent: Agent, prompt: str):
    """The instrumented agent run. The decorator injects the monitored agent."""
    return await Runner.run(agent, prompt)


async def main() -> None:
    result = await run_agent("What's the weather in Madrid?")
    print("\nAnswer:", getattr(result, "final_output", result))
    # Block until the OTLP batch is delivered to the Collector.
    _tracer_provider.force_flush()


if __name__ == "__main__":
    asyncio.run(main())
