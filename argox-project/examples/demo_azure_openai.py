"""Real-LLM demo for the Argox SDK using Azure OpenAI.

Requires the following environment variables (load via ``.env`` at the
``argox-project`` directory):

- ``AZURE_OPENAI_API_KEY``
- ``AZURE_OPENAI_ENDPOINT``
- ``AZURE_OPENAI_DEPLOYMENT``

Run from ``argox-project/``::

    python examples/demo_azure_openai.py

The demo exercises every Argox capability that is currently implemented:

1. **YAML-backed policy evaluation** — ``LocalPolicyClient`` loads
   ``examples/policies/demo_policy.yaml``, compiles its rules into the
   in-process ``PolicyCache``, and evaluates them at the three policy
   hooks (``on_input``, ``on_tool_call``, ``on_output``). The shipped
   policy blocks ``get_current_datetime`` at tool-filter time, alerts on
   prompts that mention "password", and blocks any output containing
   ``STACK_TRACE``. Swap the YAML to retune the run — no code change.
2. **In-flight argument redaction (PLUGIN-02 + PROC-01)** — the built-in
   ``PiiRedactionProcessor`` from ``argox.processors`` scrubs PII (emails,
   phones, IPs, IBAN, credit cards, ES_DNI/ES_NIE) from tool arguments
   *before* the tool function receives them, and from the LLM's final
   output before it returns to the caller. The recipient tool prints
   exactly what it ends up seeing so the in-flight mutation is visible.
   See the docstring of ``_CustomPiiProcessor`` below for a minimal
   example of how to build your own processor against the same contract.
3. **Span export — multi-sink** — every run emits a single
   ``argox.agent.run`` span carrying token usage, policy decision,
   blocked-tool list, and processor events. The demo wires two span
   exporters in parallel: ``ConsoleSpanExporter`` for a human-readable
   one-line summary on stdout, and ``JsonlSpanExporter`` writing the full
   OTel JSON payload to ``examples/run_artifacts/spans.jsonl`` for
   offline inspection.
4. **Metrics export** — a tiny custom ``ExporterBase`` prints a one-line
   summary of the run (tokens, duration, tools called/blocked) from the
   in-memory ``AgentRunMetrics`` once the run completes.

Expected output is a ``ConsoleSpanExporter`` span line for the run, the
processor's redaction logs, the tools' "received" lines, the in-memory
metrics summary, the LLM's final answer, and a ``spans.jsonl`` file
written under ``examples/run_artifacts/``.

This example uses the public ``@argox.monitor`` decorator, which replaces the
manual ``ArgoxManager`` wiring with a single declaration on the runner.
"""

from __future__ import annotations

import asyncio
import os
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
from argox.exporters import ConsoleSpanExporter, JsonlSpanExporter
from argox.interfaces.exporter import ExporterBase
from argox.policies import LocalPolicyClient
from argox.processors import PiiRedactionProcessor
from argox_openai import ArgoxOpenAIPlugin

_EXAMPLES_DIR = Path(__file__).resolve().parent
_POLICY_PATH = _EXAMPLES_DIR / "policies" / "demo_policy.yaml"
_SPANS_PATH = _EXAMPLES_DIR / "run_artifacts" / "spans.jsonl"


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


class _CustomPiiProcessor:
    """Reference implementation kept here as a tutorial for custom processors.

    Production code should use the built-in ``argox.processors.PiiRedactionProcessor``
    (registered below) which covers EMAIL/PHONE/IPV4/IPV6/IBAN/CREDIT_CARD/ES_DNI/ES_NIE,
    nested-dict traversal, MASK/HASH/DROP modes, and span events. This stub is
    *not* registered with the manager — it exists only to document the minimal
    contract a custom processor must satisfy. To roll your own::

        import re

        from argox.interfaces.processor import ArgoxProcessor


        class MyProcessor(ArgoxProcessor):
            _EMAIL_PATTERN = re.compile(r"[\\w.+-]+@[\\w-]+\\.[\\w.-]+")

            async def process_input(self, text, ctx):
                return text  # opt-out of input scrubbing

            async def process_tool_args(self, tool_name, args, ctx):
                return {
                    k: self._EMAIL_PATTERN.sub("[REDACTED]", v) if isinstance(v, str) else v
                    for k, v in args.items()
                }

            async def process_output(self, text, ctx):
                return self._EMAIL_PATTERN.sub("[REDACTED]", text)
    """


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


init_telemetry(
    exporters=[
        ConsoleSpanExporter(),
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
