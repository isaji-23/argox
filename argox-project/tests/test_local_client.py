"""Tests for LocalPolicyClient: filesystem-backed policy evaluation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argox.interfaces.policy import PolicyResult
from argox.policies.local_client import LocalPolicyClient, SYSTEM_ERROR_RULE_ID


# Sample YAML policy with blocking rules, alert rules for on_input and on_tool_call
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

  - id: alert-password-input
    trigger: on_input
    condition:
      metric: prompt
      operator: contains
      threshold: password
    action: alert

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
def policy_file(tmp_path: Path) -> Path:
    """
    Creates a temporary YAML policy file for testing.

    Args:
        tmp_path: pytest's tmp_path fixture for temporary file creation.

    Returns:
        Path to the temporary policy file.
    """
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(SAMPLE_POLICY_YAML, encoding="utf-8")
    return policy_path


@pytest.fixture
async def local_client(policy_file: Path) -> LocalPolicyClient:
    """
    Creates a LocalPolicyClient initialized with the test policy file.

    Args:
        policy_file: Path to the temporary policy file.

    Returns:
        A LocalPolicyClient instance ready for testing.
    """
    return LocalPolicyClient(policy_file)


class TestLocalClientInitialization:
    """Test LocalPolicyClient initialization."""

    def test_local_client_initialization(self, policy_file: Path) -> None:
        """
        Verifies the client initializes and parses the policy file without errors.

        The policy file is loaded and compiled into the internal cache during __init__.
        The behavior is verified through subsequent policy evaluation tests.
        """
        client = LocalPolicyClient(policy_file)

        # Verify the client has a cache and parser
        assert client.cache is not None
        assert client.parser is not None

    def test_local_client_initialization_with_string_path(
        self, policy_file: Path
    ) -> None:
        """
        Verifies that the client accepts both str and Path objects.

        The __init__ method should accept Union[str, Path].
        """
        # Test with string path
        client_str = LocalPolicyClient(str(policy_file))
        assert client_str.cache is not None

        # Test with Path object
        client_path = LocalPolicyClient(policy_file)
        assert client_path.cache is not None

    def test_local_client_initialization_invalid_file(self) -> None:
        """Verifies that an invalid policy file path raises an error."""
        with pytest.raises(FileNotFoundError):
            LocalPolicyClient("/nonexistent/path/policy.yaml")

    def test_local_client_initialization_invalid_yaml(self, tmp_path: Path) -> None:
        """Verifies that invalid YAML raises a ValueError."""
        policy_file = tmp_path / "invalid.yaml"
        policy_file.write_text("invalid: yaml: content: [", encoding="utf-8")

        with pytest.raises(ValueError, match="Failed to parse YAML"):
            LocalPolicyClient(policy_file)


class TestCheckInput:
    """Test the check_input method."""

    @pytest.mark.asyncio
    async def test_check_input_allowed(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that a safe prompt passes the input check.

        A prompt without blocked keywords should be allowed.
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
    async def test_check_input_alert(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that a prompt containing 'password' triggers an alert.

        Alert rules should pass execution (passed=True) but include a reason.
        """
        result = await local_client.check_input(
            "What is my password for the system?"
        )

        # Alert rules: passed=True but reason is set
        assert result.passed is True
        assert result.reason != ""
        assert result.rule_id == "alert-password-input"
        assert "alert-password-input" in result.reason


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

        When no rule matches a given trigger and metrics, evaluation returns PolicyResult.ok().
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

        An output without blocked phrases should be allowed.
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


class TestFailSafeBehavior:
    """Test fail-safe error handling (catch exceptions → block)."""

    @pytest.mark.asyncio
    async def test_check_input_fail_safe(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that check_input returns block on unexpected exceptions.

        Mocking cache.evaluate to raise an exception should trigger fail-safe block.
        """
        with patch.object(local_client.cache, "evaluate", side_effect=RuntimeError("Unexpected error")):
            result = await local_client.check_input("test prompt")

        # Fail-safe should return block with generic reason, not expose error details
        assert result.passed is False
        assert result.rule_id == SYSTEM_ERROR_RULE_ID
        assert "Unexpected error" not in result.reason  # No stack trace leak
        assert result.reason == "Input policy evaluation failed. Request denied."

    @pytest.mark.asyncio
    async def test_check_output_fail_safe(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that check_output returns block on unexpected exceptions.

        Mocking cache.evaluate to raise an exception should trigger fail-safe block.
        """
        with patch.object(local_client.cache, "evaluate", side_effect=ValueError("Cache error")):
            result = await local_client.check_output("test output")

        # Fail-safe should return block with generic reason
        assert result.passed is False
        assert result.rule_id == SYSTEM_ERROR_RULE_ID
        assert "Cache error" not in result.reason  # No stack trace leak
        assert result.reason == "Output policy evaluation failed. Response blocked."

    @pytest.mark.asyncio
    async def test_is_tool_allowed_fail_safe(self, local_client: LocalPolicyClient) -> None:
        """
        Tests that is_tool_allowed returns block on unexpected exceptions.

        Mocking cache.evaluate to raise an exception should trigger fail-safe block.
        """
        with patch.object(local_client.cache, "evaluate", side_effect=KeyError("Missing key")):
            result = await local_client.is_tool_allowed("some_tool")

        # Fail-safe should return block with generic reason
        assert result.passed is False
        assert result.rule_id == SYSTEM_ERROR_RULE_ID
        assert "Missing key" not in result.reason  # No stack trace leak
        assert result.reason == "Tool policy evaluation failed. Tool access denied."


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

