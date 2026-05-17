"""Real-LLM demo for the Argox SDK using Azure OpenAI.

Requires the following environment variables (load via ``.env`` at the
``argox-project`` directory):

- ``AZURE_OPENAI_API_KEY``
- ``AZURE_OPENAI_ENDPOINT``
- ``AZURE_OPENAI_DEPLOYMENT``

Run from ``argox-project/``::

    python examples/demo_azure_openai.py

The demo exercises three Argox capabilities end-to-end:

1. **Policy-based tool blocking** — ``get_current_datetime`` is denied by the
   inline policy, so the LLM must answer using only the other tools.
2. **In-flight argument redaction (PLUGIN-02)** — a ``PiiRedactingProcessor``
   scrubs anything that looks like an email address from tool arguments
   *before* the tool function receives them. The processor prints each
   redaction it performs, and the recipient tool prints exactly what it ends
   up seeing so the in-flight mutation is visible side-by-side.
3. **Metrics export** — a tiny custom exporter prints a one-line summary of
   the run (tokens, duration, tools called/blocked) once the run completes.

Expected output is a ``ConsoleSpanExporter`` span line for the run, plus the
processor's redaction logs, the tools' "received" lines, and the metrics
summary. The final answer from the LLM is printed last.

This example uses the public ``@argox.monitor`` decorator, which replaces the
manual ``ArgoxManager`` wiring with a single declaration on the runner.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Any

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
from argox.core.context import RunContext
from argox.core.state import AgentRunMetrics
from argox.exporters import ConsoleSpanExporter
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.interfaces.processor import ArgoxProcessor
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
    print(f"[tool:get_weather] received: city={city!r}")
    return f"It is sunny and 24C in {city}."


@function_tool
def get_current_datetime() -> str:
    """Return the current date and time."""
    return datetime.now().isoformat()


@function_tool
def log_user_activity(email: str, action: str) -> str:
    """Persist a user activity record (fake sink — prints what it received)."""
    print(f"[tool:log_user_activity] received: email={email!r} action={action!r}")
    return f"logged action={action!r} for {email}"


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


class _PiiRedactingProcessor(ArgoxProcessor):
    """Scrubs email-shaped substrings from tool argument values in flight.

    Exercises the PLUGIN-02 pathway: ``ArgoxOpenAIPlugin`` wraps each function
    tool so that registered processors run on the arguments *before* the tool
    body executes. The processor returns a new dict; the original LLM-emitted
    args are never seen by the tool.

    ``process_input`` and ``process_output`` are pass-throughs — this demo
    only showcases the tool-args phase.
    """

    _EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    async def process_input(self, text: str, ctx: RunContext) -> str:
        return text

    async def process_tool_args(
        self, tool_name: str, args: dict, ctx: RunContext,
    ) -> dict:
        scrubbed: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str):
                redacted = self._EMAIL_PATTERN.sub("[REDACTED]", value)
                if redacted != value:
                    print(
                        f"[processor] redacted email in tool={tool_name!r} "
                        f"arg={key!r}: {value!r} -> {redacted!r}"
                    )
                scrubbed[key] = redacted
            else:
                scrubbed[key] = value
        return scrubbed

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return text


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


init_telemetry(exporters=[ConsoleSpanExporter()])

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
    policy=_InlinePolicy(),
    processors=[_PiiRedactingProcessor()],
    exporters=[_PrintMetricsExporter()],
)
async def run_agent(agent: Agent, prompt: str):
    return await Runner.run(agent, prompt)


async def main() -> None:
    output = await run_agent(
        "Log that user@example.com just checked the forecast, "
        "and tell me the weather in Madrid."
    )
    print("\nFinal output:", output)


if __name__ == "__main__":
    asyncio.run(main())
