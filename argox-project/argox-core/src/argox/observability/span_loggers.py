"""ConsoleSpanLogger — human-readable wrapper over OTel's console exporter.

Replaces the default JSON-dump formatter with a single-line summary per span
that highlights the fields a developer wants to see at a glance: span name,
duration, status, token usage, and Argox policy decisions.
"""

from __future__ import annotations

import os
import sys
from typing import IO

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter as _OtelConsoleSpanExporter,
)

from argox.semconv.attributes import (
    ARGOX_POLICY_DECISION,
    ARGOX_POLICY_RULE_ID,
    ARGOX_RUN_BLOCKED_TOOLS,
    ARGOX_RUN_COST,
)

# OTel GenAI semantic-convention attribute keys for LLM token usage.
_GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
_GEN_AI_COST = "gen_ai.usage.cost"


def _format_summary(span: ReadableSpan) -> str:
    """Render a span as a one-line summary highlighting Argox-relevant fields."""
    start = span.start_time or 0
    end = span.end_time or start
    duration_ms = (end - start) / 1_000_000

    parts: list[str] = [f"[argox] {span.name} ({duration_ms:.2f} ms)"]

    status = span.status
    if status is not None and status.status_code is not None:
        parts.append(f"status={status.status_code.name}")

    attrs = span.attributes or {}

    if _GEN_AI_INPUT_TOKENS in attrs or _GEN_AI_OUTPUT_TOKENS in attrs:
        tin = attrs.get(_GEN_AI_INPUT_TOKENS, 0)
        tout = attrs.get(_GEN_AI_OUTPUT_TOKENS, 0)
        parts.append(f"tokens={tin}/{tout}")

    cost = attrs.get(_GEN_AI_COST)
    if cost is None:
        cost = attrs.get(ARGOX_RUN_COST)
    if cost is not None:
        cost_str = f"{float(cost):.6f}".rstrip("0").rstrip(".")
        parts.append(f"cost=${cost_str}")

    decision = attrs.get(ARGOX_POLICY_DECISION)
    if decision is not None:
        rule = attrs.get(ARGOX_POLICY_RULE_ID)
        parts.append(f"policy={decision}" + (f"[{rule}]" if rule else ""))

    blocked = attrs.get(ARGOX_RUN_BLOCKED_TOOLS)
    if blocked:
        parts.append(f"blocked_tools={list(blocked)}")

    return " ".join(parts) + os.linesep


class ConsoleSpanLogger(_OtelConsoleSpanExporter):
    """OTel ConsoleSpanExporter that prints a one-line Argox summary per span.

    Drop-in replacement for ``opentelemetry.sdk.trace.export.ConsoleSpanExporter``
    that swaps the default JSON-dump formatter for a compact, scannable line
    showing span name, duration, status, token usage, and policy decision.

    Args:
        out: Output stream. Defaults to ``sys.stdout``.

    Example::

        from argox.core import init_telemetry
        from argox.observability.span_loggers import ConsoleSpanLogger

        init_telemetry(exporters=[ConsoleSpanLogger()])
    """

    def __init__(self, out: IO = sys.stdout) -> None:
        super().__init__(out=out, formatter=_format_summary)
