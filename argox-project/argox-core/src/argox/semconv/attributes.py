"""
Custom Argox OpenTelemetry semantic conventions.

This module defines string constants for Argox-specific attributes used in OpenTelemetry spans.
These attributes extend the standard OTel Generative AI Semantic Conventions with Argox-specific
metadata for monitoring, governance, and auditing of AI agents.
"""

from typing import Final

# Policy and Governance Attributes
ARGOX_POLICY_DECISION: Final[str] = "argox.policy.decision"
"""Indicates the result of a policy evaluation. Possible values: 'ok', 'block', 'alert'."""

ARGOX_POLICY_RULE_ID: Final[str] = "argox.policy.rule_id"
"""Identifier of the specific rule that triggered a block or alert decision."""

# Processor Attributes
ARGOX_PROCESSOR_APPLIED: Final[str] = "argox.processor.applied"
"""A list of processor names that transformed the data in-flight."""

ARGOX_PROCESSOR_NAME: Final[str] = "argox.processor.name"
"""The class name of the processor associated with a span event."""

ARGOX_PROCESSOR_PHASE: Final[str] = "argox.processor.phase"
"""The lifecycle phase the processor ran in. Possible values: 'input', 'tool_args', 'output'."""

ARGOX_PROCESSOR_TOOL_NAME: Final[str] = "argox.processor.tool_name"
"""The tool name a processor ran against during a 'tool_args' phase invocation."""

ARGOX_PROCESSOR_STRICT: Final[str] = "argox.processor.strict"
"""True if the failing processor was registered with fail-closed (strict) semantics."""

# Span / event names
SPAN_AGENT_RUN: Final[str] = "argox.agent.run"
"""Top-level span emitted by ArgoxManager.run() covering the full agent lifecycle."""

EVENT_PROCESSOR_APPLIED: Final[str] = "argox.processor.applied"
"""Span event marking a successful processor invocation."""

EVENT_PROCESSOR_ERROR: Final[str] = "argox.processor.error"
"""Span event marking a processor that raised during invocation."""

# Agent Attributes
ARGOX_AGENT_VERSION: Final[str] = "argox.agent.version"
"""The registered version of the agent being executed."""

# Run/Execution Attributes
ARGOX_RUN_BLOCKED_TOOLS: Final[str] = "argox.run.blocked_tools"
"""A list of tools that were filtered/blocked by the policy engine during the run."""

ARGOX_RUN_SUCCESS: Final[str] = "argox.run.success"
"""Boolean attribute marking whether a run completed without unhandled errors."""

ARGOX_RUN_COST: Final[str] = "argox.run.cost"
"""The estimated cost of the run in USD."""

ARGOX_AGENT_NAME: Final[str] = "argox.agent.name"
"""Logical name of the agent recorded alongside run-level metrics."""

ARGOX_PROCESSOR_STATUS: Final[str] = "argox.processor.status"
"""Outcome of a processor invocation. Possible values: 'applied', 'error'."""

ARGOX_PII_REDACTIONS: Final[str] = "argox.pii.redactions"
"""Per-entity redaction counts emitted by the built-in PII processor.

Stored on the active span as a list of ``"<ENTITY>:<count>"`` strings so it
encodes cleanly through every OpenTelemetry exporter (attributes cannot hold
nested dicts). The raw redacted values are never recorded.
"""

EVENT_PII_REDACTED: Final[str] = "argox.pii.redacted"
"""Span event emitted by the built-in PII processor when redactions fire.

Distinct from :data:`EVENT_PROCESSOR_APPLIED` (which the Manager emits once
per processor invocation regardless of effect), so consumers can tell apart
"this processor ran" from "this processor actually redacted something".
"""

# Metric instrument names
METRIC_GEN_AI_TOKEN_USAGE: Final[str] = "gen_ai.client.token.usage"
"""Counter for input/output tokens consumed by agent runs."""

METRIC_GEN_AI_OPERATION_DURATION: Final[str] = "gen_ai.client.operation.duration"
"""Histogram for total agent-run duration in seconds."""

METRIC_ARGOX_POLICY_DECISIONS: Final[str] = "argox.policy.decisions"
"""Counter for policy decisions emitted by the policy engine."""

METRIC_ARGOX_PROCESSOR_INVOCATIONS: Final[str] = "argox.processor.invocations"
"""Counter for processor invocations grouped by phase and outcome."""

# Metric-only attribute keys
GEN_AI_TOKEN_TYPE: Final[str] = "gen_ai.token.type"
"""Distinguishes 'input' vs 'output' token-usage counter increments."""
