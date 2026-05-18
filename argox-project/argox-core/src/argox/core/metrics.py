"""Argox metric instruments and recording helpers.

Instruments are created lazily on first record so they bind to whichever
``MeterProvider`` is installed at the moment metrics actually fire — this
matters for tests that swap providers between cases. Call
``reset_instruments()`` from a test fixture if you need to drop the cache.
"""

from __future__ import annotations

from opentelemetry import metrics as _metrics_api
from opentelemetry.metrics import Counter, Histogram, Meter

from argox.semconv.attributes import (
    ARGOX_AGENT_NAME,
    ARGOX_POLICY_DECISION,
    ARGOX_POLICY_RULE_ID,
    ARGOX_PROCESSOR_NAME,
    ARGOX_PROCESSOR_PHASE,
    ARGOX_PROCESSOR_STATUS,
    ARGOX_RUN_SUCCESS,
    GEN_AI_TOKEN_TYPE,
    METRIC_ARGOX_POLICY_DECISIONS,
    METRIC_ARGOX_PROCESSOR_INVOCATIONS,
    METRIC_GEN_AI_OPERATION_DURATION,
    METRIC_GEN_AI_TOKEN_USAGE,
)

_meter: Meter | None = None
_token_usage: Counter | None = None
_run_duration: Histogram | None = None
_policy_decisions: Counter | None = None
_processor_invocations: Counter | None = None


def _ensure_instruments() -> None:
    global _meter, _token_usage, _run_duration, _policy_decisions, _processor_invocations
    if _meter is not None:
        return
    _meter = _metrics_api.get_meter("argox")
    _token_usage = _meter.create_counter(
        METRIC_GEN_AI_TOKEN_USAGE,
        unit="{token}",
        description="Number of input and output tokens used per agent run.",
    )
    _run_duration = _meter.create_histogram(
        METRIC_GEN_AI_OPERATION_DURATION,
        unit="s",
        description="Duration of agent runs in seconds.",
    )
    _policy_decisions = _meter.create_counter(
        METRIC_ARGOX_POLICY_DECISIONS,
        unit="{decision}",
        description="Count of policy decisions emitted during agent runs.",
    )
    _processor_invocations = _meter.create_counter(
        METRIC_ARGOX_PROCESSOR_INVOCATIONS,
        unit="{invocation}",
        description="Count of processor invocations grouped by phase and outcome.",
    )


def record_token_usage(tokens: int, *, token_type: str) -> None:
    """Increment the token-usage counter. No-op when ``tokens`` is non-positive."""
    if tokens <= 0:
        return
    _ensure_instruments()
    assert _token_usage is not None
    _token_usage.add(tokens, {GEN_AI_TOKEN_TYPE: token_type})


def record_run_duration(
    duration_seconds: float, *, agent_name: str, success: bool
) -> None:
    """Record the total wall-clock duration of an agent run."""
    _ensure_instruments()
    assert _run_duration is not None
    _run_duration.record(
        duration_seconds,
        {ARGOX_AGENT_NAME: agent_name, ARGOX_RUN_SUCCESS: success},
    )


def record_policy_decision(*, decision: str, rule_id: str | None) -> None:
    """Increment the policy-decisions counter."""
    _ensure_instruments()
    assert _policy_decisions is not None
    attrs: dict[str, str] = {ARGOX_POLICY_DECISION: decision}
    if rule_id:
        attrs[ARGOX_POLICY_RULE_ID] = rule_id
    _policy_decisions.add(1, attrs)


def record_processor_invocation(*, name: str, phase: str, status: str) -> None:
    """Increment the processor-invocations counter."""
    _ensure_instruments()
    assert _processor_invocations is not None
    _processor_invocations.add(
        1,
        {
            ARGOX_PROCESSOR_NAME: name,
            ARGOX_PROCESSOR_PHASE: phase,
            ARGOX_PROCESSOR_STATUS: status,
        },
    )


def reset_instruments() -> None:
    """Drop cached instruments so the next record rebinds to the current MeterProvider.

    Intended for test fixtures that install a fresh provider per case.
    """
    global _meter, _token_usage, _run_duration, _policy_decisions, _processor_invocations
    _meter = None
    _token_usage = None
    _run_duration = None
    _policy_decisions = None
    _processor_invocations = None
