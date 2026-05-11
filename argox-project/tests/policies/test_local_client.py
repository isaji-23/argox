"""Tests for LocalPolicyClient: filesystem-backed policy evaluation."""

from __future__ import annotations

import os
import tempfile
from typing import Generator

import pytest

from argox.policies.local_client import LocalPolicyClient


# Sample YAML policy with blocking rules for on_input and on_tool_call
SAMPLE_POLICY_YAML = """
id: test-policy
version: 1
status: active
rules:
  - id: block-secret-input
    trigger: on_input
    condition:
      metric: prompt
      operator: contains
      threshold: secret
    action: block

  - id: block-delete-db-tool
    trigger: on_tool_call
    condition:
      metric: tool_name
      operator: eq
      threshold: delete_db
    action: block

  - id: allow-echo-tool
    trigger: on_tool_call
    condition:
      metric: tool_name
      operator: eq
      threshold: echo
    action: ok

  - id: block-debug-output
    trigger: on_output
    condition:
      metric: output
      operator: contains
      threshold: internal_error
    action: block
"""


@pytest.fixture
def temp_policy_file() -> Generator[str, None, None]:
    """
    Creates a temporary YAML policy file for testing.

    Yields:
        Path to the temporary policy file.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(SAMPLE_POLICY_YAML)
        temp_path = f.name

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
async def local_client(temp_policy_file: str) -> LocalPolicyClient:
    """
    Creates a LocalPolicyClient initialized with the test policy file.

    Args:
        temp_policy_file: Path to the temporary policy file.

    Returns:
        A LocalPolicyClient instance ready for testing.
    """
    return LocalPolicyClient(temp_policy_file)


class TestLocalClientInitialization:
    """Test LocalPolicyClient initialization."""

    def test_local_client_initialization(self, temp_policy_file: str) -> None:
        """
        Verifies the client initializes and parses the policy file without errors.

        The cache should be populated with the parsed policy rules.
        """
        client = LocalPolicyClient(temp_policy_file)

        # Verify the client has a cache and parser
        assert client.cache is not None
        assert client.parser is not None

        # Verify the cache has the expected triggers
        assert "on_input" in client.cache._rules_by_trigger
        assert "on_tool_call" in client.cache._rules_by_trigger
        assert "on_output" in client.cache._rules_by_trigger

        # Verify the number of rules for each trigger
        assert len(client.cache._rules_by_trigger["on_input"]) == 1
        assert len(client.cache._rules_by_trigger["on_tool_call"]) == 2
        assert len(client.cache._rules_by_trigger["on_output"]) == 1

    def test_local_client_initialization_invalid_file(self) -> None:
        """Verifies that an invalid policy file path raises an error."""
        with pytest.raises(FileNotFoundError):
            LocalPolicyClient("/nonexistent/path/policy.yaml")

    def test_local_client_initialization_invalid_yaml(self) -> None:
        """Verifies that invalid YAML raises a ValueError."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("invalid: yaml: content: [")  # Intentionally malformed YAML
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="Failed to parse YAML"):
                LocalPolicyClient(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class TestCheckInput:
    """Test the check_input method."""

    @pytest.mark.asyncio
    async def test_check_input_allowed(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that a safe prompt passes the input check.

        A prompt without the blocked word should be allowed.
        """
        result = await local_client.check_input("What is the weather today?")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""

    @pytest.mark.asyncio
    async def test_check_input_blocked(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that a prompt with 'secret' is blocked.

        A prompt containing the blocked keyword should be blocked.
        """
        result = await local_client.check_input("I want to access the secret API key")

        assert result.passed is False
        assert result.rule_id == "block-secret-input"
        assert "block-secret-input" in result.reason

    @pytest.mark.asyncio
    async def test_check_input_blocked_case_sensitive(
        self, local_client: LocalPolicyClient
    ) -> None:
        """
        Tests that the blocking is case-sensitive.

        A prompt with 'Secret' (capitalized) should not be blocked by the 'secret' rule.
        """
        result = await local_client.check_input("This is a Secret message")

        # Depending on the "contains" operator implementation, this may pass or fail
        # If case-sensitive, should pass; if case-insensitive, should block.
        # The current implementation is case-sensitive for 'contains'.
        assert result.passed is True


class TestIsToolAllowed:
    """Test the is_tool_allowed method."""

    @pytest.mark.asyncio
    async def test_is_tool_allowed_safe_tool(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that a safe tool is allowed.

        The 'echo' tool should pass policy checks.
        """
        result = await local_client.is_tool_allowed("echo")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""

    @pytest.mark.asyncio
    async def test_is_tool_allowed_dangerous_tool(
        self, local_client: LocalPolicyClient
    ) -> None:
        """
        Tests that the 'delete_db' tool is blocked.

        The 'delete_db' tool should be blocked by the policy.
        """
        result = await local_client.is_tool_allowed("delete_db")

        assert result.passed is False
        assert result.rule_id == "block-delete-db-tool"
        assert "block-delete-db-tool" in result.reason

    @pytest.mark.asyncio
    async def test_is_tool_allowed_other_tool(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that a tool not explicitly mentioned in the policy is allowed.

        Tools not in the blocklist should pass (fail-open).
        """
        result = await local_client.is_tool_allowed("send_email")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""


class TestCheckOutput:
    """Test the check_output method."""

    @pytest.mark.asyncio
    async def test_check_output_allowed(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that safe output passes the check.

        An output without the blocked phrase should be allowed.
        """
        result = await local_client.check_output("The weather today is sunny.")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""

    @pytest.mark.asyncio
    async def test_check_output_blocked(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that output containing 'internal_error' is blocked.

        Output with the blocked phrase should be blocked.
        """
        result = await local_client.check_output(
            "An internal_error occurred during processing"
        )

        assert result.passed is False
        assert result.rule_id == "block-debug-output"
        assert "block-debug-output" in result.reason

    @pytest.mark.asyncio
    async def test_check_output_safe_error_message(
        self, local_client: LocalPolicyClient
    ) -> None:
        """
        Tests that a generic error message (without the blocked phrase) passes.

        Output without the specific blocked keyword should be allowed.
        """
        result = await local_client.check_output("An error occurred. Please try again.")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""


class TestAsyncBehavior:
    """Test async behavior of the client."""

    @pytest.mark.asyncio
    async def test_multiple_checks_in_sequence(
        self, local_client: LocalPolicyClient
    ) -> None:
        """
        Tests that the client can perform multiple policy checks in sequence.

        Each check should be independent and stateless.
        """
        # Check multiple inputs
        result1 = await local_client.check_input("Hello")
        result2 = await local_client.check_input("secret password")
        result3 = await local_client.check_input("Goodbye")

        assert result1.passed is True
        assert result2.passed is False
        assert result3.passed is True

    @pytest.mark.asyncio
    async def test_all_three_methods(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that all three policy check methods work correctly.

        The client should support checking input, output, and tools.
        """
        input_result = await local_client.check_input("Hello")
        tool_result = await local_client.is_tool_allowed("echo")
        output_result = await local_client.check_output("Response")

        assert input_result.passed is True
        assert tool_result.passed is True
        assert output_result.passed is True
