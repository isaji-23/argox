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
