"""
IFACE-03 — PolicyClient
========================
Contract that abstracts communication with the external policy service.

It decouples the SDK from the concrete transport: the local stub (for development without
network) and the real SSE client (for production) are distinct implementations
of the same contract. The ArgoxManager only knows this interface.

Evaluation Model
--------------------
Every evaluation returns a ``PolicyResult``: an immutable object with the
verdict (``passed``), a readable reason (``reason``), and the name of the
rule that generated it (``rule_id``). This allows the Manager to log and audit
without depending on the internal format of each implementation.

Evaluation Points
--------------------
The lifecycle of an execution has three points where policies are applied:

  1. ``check_input``  — before sending the prompt to the agent.
  2. ``is_tool_allowed``   — before allowing the agent to call a tool.
  3. ``check_output`` — after receiving the final response from the agent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyResult:
    """
    Immutable result of a policy evaluation.

    Attributes:
        passed:  ``True`` if the evaluation found no violations.
        reason:  Readable description of the reason for the verdict.
                 Empty when ``passed`` is ``True``.
        rule_id: Identifier of the rule that generated the verdict.
                 Useful for correlating with the external policy service.
                 Empty when ``passed`` is ``True``.
    """
    passed: bool
    reason: str = ""
    rule_id: str = ""

    # Semantic constructors for better readability in implementations.

    @classmethod
    def ok(cls) -> "PolicyResult":
        """Positive verdict without additional information."""
        return cls(passed=True)

    @classmethod
    def block(cls, reason: str, rule_id: str = "") -> "PolicyResult":
        """Negative verdict with a mandatory reason."""
        return cls(passed=False, reason=reason, rule_id=rule_id)


class PolicyClient(ABC):
    """
    Abstract interface for policy service clients.

    Planned implementations:
        - ``LocalPolicyClient``  — hardcoded rules, no network. Development stub.
        - ``SsePolicyClient``    — consumes the external service via SSE with local cache.

    All implementations must:
        - Be fail-safe against network errors: if the service does not respond, apply
          the configured fallback policy (by default: allow with warning).
        - Not raise exceptions to the Manager — catch and return
          ``PolicyResult.block(reason="...")`` if something fails internally.
        - Be stateless per call: the cache state is internal to the implementation.

    Usage example in ArgoxManager::

        result = await self.policy.check_input(prompt)
        if not result.passed:
            metrics.policy_violations.append(result.reason)
            raise PermissionError(f"[POLICY:{result.rule_id}] {result.reason}")
    """

    @abstractmethod
    async def check_input(self, text: str) -> PolicyResult:
        """
        Evaluates the user prompt before sending it to the agent.

        Args:
            text: The full prompt as entered by the user.

        Returns:
            ``PolicyResult.ok()`` if the input is acceptable.
            ``PolicyResult.block(...)`` if the execution should be blocked.
        """
        ...

    @abstractmethod
    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        """
        Determines if a tool can be exposed to the agent.
        It is evaluated in pre-flight: the Manager filters the list BEFORE
        the agent receives it.

        Args:
            tool_name: Name of the tool as registered in the agent.

        Returns:
            ``PolicyResult.ok()`` if the tool can be executed.
            ``PolicyResult.block(...)`` if it should be disabled.
        """
        ...

    @abstractmethod
    async def check_output(self, text: str) -> PolicyResult:
        """
        Evaluates the final response of the agent before returning it to the user.

        Args:
            text: The final output of the agent as a pure string.

        Returns:
            ``PolicyResult.ok()`` if the output is acceptable.
            ``PolicyResult.block(...)`` if it should be marked as a violation.
        """
        ...
        