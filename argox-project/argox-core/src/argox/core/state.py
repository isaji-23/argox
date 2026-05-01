"""Core data model for Argox agent run metrics.

Minimal stubs used by the interface layer. CORE-01 will flesh out the full model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class ApiCallRecord:
    """Token usage for a single LLM API call."""

    call_number: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class ToolCallRecord:
    """Record of a single tool invocation by the agent."""

    tool_name: str
    args: dict = field(default_factory=dict)


@dataclass
class AgentRunMetrics:
    """Accumulated metrics for one agent execution."""

    agent_name: str = ""
    api_calls: List[ApiCallRecord] = field(default_factory=list)
    tools_called: List[ToolCallRecord] = field(default_factory=list)
    policy_violations: List[str] = field(default_factory=list)
    output: str = ""
    success: bool = False
