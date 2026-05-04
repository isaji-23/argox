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

# Agent Attributes
ARGOX_AGENT_VERSION: Final[str] = "argox.agent.version"
"""The registered version of the agent being executed."""

# Run/Execution Attributes
ARGOX_RUN_BLOCKED_TOOLS: Final[str] = "argox.run.blocked_tools"
"""A list of tools that were filtered/blocked by the policy engine during the run."""
