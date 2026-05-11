"""
POL-03 — LocalPolicyClient
==========================
A filesystem-backed policy client for development and testing.

This client loads policy rules from a local YAML file and evaluates them
using the in-process PolicyCache. It implements the PolicyClient interface
and is suitable for development without network dependencies.

Example usage::

    client = LocalPolicyClient("policy.yaml")
    result = await client.check_input("user prompt")
    if not result.passed:
        raise PermissionError(f"Policy violation: {result.reason}")
"""

from __future__ import annotations

from pathlib import Path

from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.policies.cache import PolicyCache
from argox.policies.parser import PolicyParser


class LocalPolicyClient(PolicyClient):
    """
    Filesystem-backed policy client for local policy evaluation.

    Loads a YAML policy file, compiles its rules into the PolicyCache,
    and evaluates policies synchronously via the cache's high-performance
    evaluation engine. All methods catch exceptions internally and return
    PolicyResult blocks rather than raising exceptions.

    Attributes:
        cache: In-process policy cache storing compiled rule predicates.
        parser: PolicyParser instance for loading and validating YAML files.
    """

    def __init__(self, policy_path: str) -> None:
        """
        Initialize the LocalPolicyClient and load the policy file.

        Args:
            policy_path: Path to the YAML policy file (absolute or relative).

        Raises:
            FileNotFoundError: If the policy file does not exist.
            ValueError: If the policy file is invalid or cannot be parsed.
        """
        self.cache: PolicyCache = PolicyCache()
        self.parser: PolicyParser = PolicyParser()

        # Load the policy document from the file
        document = self.parser.parse_file(policy_path)

        # Compile and cache the policy rules
        self.cache.load_policy(document)

    async def check_input(self, text: str) -> PolicyResult:
        """
        Evaluate the user input prompt against cached policies.

        Checks if the input violates any policies defined for the 'on_input' trigger.

        Args:
            text: The user's input prompt.

        Returns:
            PolicyResult.ok() if input is acceptable.
            PolicyResult.block(...) if a blocking rule matched.
            PolicyResult.alert(...) if an alert rule matched.
        """
        try:
            return self.cache.evaluate(trigger="on_input", metrics={"prompt": text})
        except Exception as e:
            # Fail-safe: return block on unexpected errors
            return PolicyResult.block(
                reason=f"Unexpected error during input policy check: {e}",
                rule_id="system_error",
            )

    async def check_output(self, text: str) -> PolicyResult:
        """
        Evaluate the agent's output against cached policies.

        Checks if the output violates any policies defined for the 'on_output' trigger.

        Args:
            text: The agent's output response.

        Returns:
            PolicyResult.ok() if output is acceptable.
            PolicyResult.block(...) if a blocking rule matched.
            PolicyResult.alert(...) if an alert rule matched.
        """
        try:
            return self.cache.evaluate(trigger="on_output", metrics={"output": text})
        except Exception as e:
            # Fail-safe: return block on unexpected errors
            return PolicyResult.block(
                reason=f"Unexpected error during output policy check: {e}",
                rule_id="system_error",
            )

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        """
        Determine if a tool is allowed to be used by the agent.

        Checks if the tool violates any policies defined for the 'on_tool_call' trigger.

        Args:
            tool_name: Name of the tool as registered in the agent.

        Returns:
            PolicyResult.ok() if tool is allowed.
            PolicyResult.block(...) if a blocking rule matched.
            PolicyResult.alert(...) if an alert rule matched.
        """
        try:
            return self.cache.evaluate(
                trigger="on_tool_call", metrics={"tool_name": tool_name}
            )
        except Exception as e:
            # Fail-safe: return block on unexpected errors
            return PolicyResult.block(
                reason=f"Unexpected error during tool policy check: {e}",
                rule_id="system_error",
            )
