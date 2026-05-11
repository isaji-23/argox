"""Real-LLM demo for the Argox SDK using Azure OpenAI.

Requires the following environment variables (load via ``.env`` at the
``argox-project`` directory):

- ``AZURE_OPENAI_API_KEY``
- ``AZURE_OPENAI_ENDPOINT``
- ``AZURE_OPENAI_DEPLOYMENT``

Run from ``argox-project/``::

    python examples/demo_azure_openai.py

Expected output is a single ``argox.agent.run`` span line printed by the
``ConsoleSpanExporter`` plus a metrics summary printed by the custom exporter
defined below. The demo wires a toy ``PolicyClient`` that blocks
``get_current_datetime`` so the LLM must answer using only ``get_weather``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

from agents import (
    Agent,
    Runner,
    function_tool,
    set_default_openai_client,
    set_tracing_disabled,
)
from dotenv import load_dotenv
from openai import AsyncOpenAI

from argox.core import ArgoxManager, init_telemetry
from argox.core.state import AgentRunMetrics
from argox.exporters import ConsoleSpanExporter
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox_openai import ArgoxOpenAIPlugin


load_dotenv()
set_tracing_disabled(True)
set_default_openai_client(
    AsyncOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
    )
)


@function_tool
def get_weather(city: str) -> str:
    """Return the current weather for a city (fake data)."""
    return f"It is sunny and 24C in {city}."


@function_tool
def get_current_datetime() -> str:
    """Return the current date and time."""
    return datetime.now().isoformat()


class _InlinePolicy(PolicyClient):
    """Toy in-memory policy used solely for the demo.

    Blocks ``get_current_datetime`` to exercise the Manager's tool-filtering path.
    All other inputs and outputs pass through unchanged.
    """

    BLOCKED_TOOLS = {"get_current_datetime"}

    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        if tool_name in self.BLOCKED_TOOLS:
            return PolicyResult.block(
                reason=f"{tool_name} disabled by demo policy",
                rule_id="DEMO-01",
            )
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.ok()


class _PrintMetricsExporter(ExporterBase):
    """Tiny exporter that prints a one-shot metrics summary at the end of the run."""

    def export(self, metrics: AgentRunMetrics) -> None:
        tools_called = [t.name for t in metrics.tools_called]
        blocked = [b["name"] for b in metrics.tools_blocked]
        print()
        print("[metrics] agent:        ", metrics.agent_name)
        print("[metrics] success:      ", metrics.success)
        print(f"[metrics] duration:     {metrics.duration:.2f}s")
        print(f"[metrics] tokens:       in={metrics.total_input_tokens} "
              f"out={metrics.total_output_tokens} total={metrics.total_tokens}")
        print("[metrics] tools_available:", metrics.tools_available)
        print("[metrics] tools_blocked:  ", blocked)
        print("[metrics] tools_called:   ", tools_called)
        if metrics.policy_violations:
            print("[metrics] violations:   ", metrics.policy_violations)


async def openai_runner(agent: Agent, prompt: str):
    return await Runner.run(agent, prompt)


async def main() -> None:
    init_telemetry(exporters=[ConsoleSpanExporter()])

    mgr = ArgoxManager(policy=_InlinePolicy())
    mgr.register_plugin(ArgoxOpenAIPlugin())
    mgr.register_exporter(_PrintMetricsExporter())

    agent = Agent(
        name="weather-assistant",
        instructions="Use the available tools to answer the user's question.",
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        tools=[get_weather, get_current_datetime],
    )

    output = await mgr.run(
        agent,
        "What's the weather in Madrid right now and what time is it?",
        "openai",
        openai_runner,
    )
    print("\nFinal output:", output)


if __name__ == "__main__":
    asyncio.run(main())
