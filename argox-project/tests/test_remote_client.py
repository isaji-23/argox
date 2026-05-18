"""Tests for RemotePolicyClient: remote policy fetching with background polling."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argox.policies.remote_client import RemotePolicyClient


# Sample YAML policy with blocking rules
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

  - id: block-debug-output
    trigger: on_output
    condition:
      metric: output
      operator: contains
      threshold: internal_error
    action: block
"""


@pytest.fixture
def endpoint_url() -> str:
    """The mock endpoint URL."""
    return "https://collector.example.com/policy"


@pytest.fixture
async def remote_client(endpoint_url: str) -> RemotePolicyClient:
    """Creates a RemotePolicyClient instance for testing."""
    client = RemotePolicyClient(
        endpoint_url=endpoint_url,
        refresh_interval_s=1,  # Fast interval for testing
    )
    yield client
    # Cleanup: ensure the background task is stopped
    await client.stop()


class TestRemotePolicyClientInitialization:
    """Test RemotePolicyClient initialization."""

    def test_initialization(self, endpoint_url: str) -> None:
        """Verifies the client initializes with correct attributes."""
        client = RemotePolicyClient(
            endpoint_url=endpoint_url,
            refresh_interval_s=30,
        )

        assert client.endpoint_url == endpoint_url
        assert client.refresh_interval_s == 30
        assert client.cache is not None
        assert client.parser is not None
        assert client._client is not None
        assert client._task is None

    def test_initialization_defaults(self, endpoint_url: str) -> None:
        """Verifies default refresh interval is 60 seconds."""
        client = RemotePolicyClient(endpoint_url=endpoint_url)

        assert client.refresh_interval_s == 60


class TestRemotePolicyClientLifecycle:
    """Test lifecycle management (start/stop)."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that start() creates the background polling task."""
        assert remote_client._task is None

        await remote_client.start()

        assert remote_client._task is not None
        assert not remote_client._task.done()

        await remote_client.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that stop() cancels the background task."""
        await remote_client.start()
        task = remote_client._task

        await remote_client.stop()

        assert task is not None
        assert task.done()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that stop() can be called multiple times safely."""
        await remote_client.start()
        await remote_client.stop()

        # Should not raise
        await remote_client.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that start() is idempotent."""
        await remote_client.start()
        task1 = remote_client._task

        # Call start again
        await remote_client.start()
        task2 = remote_client._task

        # Should reuse the same task
        assert task1 == task2

        await remote_client.stop()


class TestRemotePolicyClientPolling:
    """Test background polling mechanism."""

    @pytest.mark.asyncio
    async def test_polling_success(self, remote_client: RemotePolicyClient) -> None:
        """Verifies successful policy fetching and loading."""
        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            await remote_client.start()

            # Wait for at least one polling cycle
            await asyncio.sleep(1.5)

            # Verify the policy was fetched and loaded
            mock_get.assert_called()
            assert remote_client.cache._rules_by_trigger  # Cache should be populated

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_polling_network_error_fail_open(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies fail-open behavior on network errors."""
        # First, load a valid policy into the cache
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        # Mock the HTTP client to fail
        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = Exception("Network error")

            await remote_client.start()

            # Wait for a polling cycle
            await asyncio.sleep(1.5)

            # Verify the client is still running despite the error
            assert remote_client._task is not None
            assert not remote_client._task.done()

            # Verify the cache still contains the previous policy
            assert remote_client.cache._rules_by_trigger

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_polling_parse_error_fail_open(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies fail-open behavior on YAML parse errors."""
        # First, load a valid policy into the cache
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        # Mock the HTTP client to return invalid YAML
        mock_response = MagicMock()
        mock_response.text = "invalid: yaml: ["
        mock_response.status_code = 200

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            await remote_client.start()

            # Wait for a polling cycle
            await asyncio.sleep(1.5)

            # Verify the client is still running despite the parse error
            assert remote_client._task is not None
            assert not remote_client._task.done()

            # Verify the cache still contains the previous policy
            assert remote_client.cache._rules_by_trigger

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_polling_http_error(self, remote_client: RemotePolicyClient) -> None:
        """Verifies fail-open behavior on HTTP errors."""
        # Load a valid policy into the cache
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        # Mock the HTTP client to return an error status
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 500")

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            await remote_client.start()

            # Wait for a polling cycle
            await asyncio.sleep(1.5)

            # Verify the client is still running
            assert remote_client._task is not None
            assert not remote_client._task.done()

            # Verify the cache still contains the previous policy
            assert remote_client.cache._rules_by_trigger

            await remote_client.stop()


class TestRemotePolicyClientHotPath:
    """Test hot-path evaluation methods (no network I/O)."""

    @pytest.mark.asyncio
    async def test_check_input_allowed(self, remote_client: RemotePolicyClient) -> None:
        """Tests that check_input does not make network requests."""
        # Load a policy
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        # Mock the HTTP client (should not be called)
        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            result = await remote_client.check_input("What is the weather?")

            # Verify no network request was made
            mock_get.assert_not_called()
            assert result.passed is True

    @pytest.mark.asyncio
    async def test_check_input_blocked(self, remote_client: RemotePolicyClient) -> None:
        """Tests blocking rule in check_input."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        result = await remote_client.check_input("I need the secret password")

        assert result.passed is False
        assert result.rule_id == "block-secret-input"

    @pytest.mark.asyncio
    async def test_check_output_allowed(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Tests that check_output does not make network requests."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            result = await remote_client.check_output("The weather is sunny.")

            mock_get.assert_not_called()
            assert result.passed is True

    @pytest.mark.asyncio
    async def test_check_output_blocked(self, remote_client: RemotePolicyClient) -> None:
        """Tests blocking rule in check_output."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        result = await remote_client.check_output("Error: internal_error occurred")

        assert result.passed is False
        assert result.rule_id == "block-debug-output"

    @pytest.mark.asyncio
    async def test_is_tool_allowed_safe(self, remote_client: RemotePolicyClient) -> None:
        """Tests that is_tool_allowed does not make network requests."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            result = await remote_client.is_tool_allowed("send_email")

            mock_get.assert_not_called()
            assert result.passed is True

    @pytest.mark.asyncio
    async def test_is_tool_allowed_blocked(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Tests blocking rule in is_tool_allowed."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        result = await remote_client.is_tool_allowed("delete_db")

        assert result.passed is False
        assert result.rule_id == "block-delete-db-tool"


class TestRemotePolicyClientEmptyCache:
    """Test behavior with empty cache (no policies loaded yet)."""

    @pytest.mark.asyncio
    async def test_check_input_empty_cache(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies check_input returns ok() when cache is empty."""
        result = await remote_client.check_input("any text")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""

    @pytest.mark.asyncio
    async def test_check_output_empty_cache(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies check_output returns ok() when cache is empty."""
        result = await remote_client.check_output("any output")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""

    @pytest.mark.asyncio
    async def test_is_tool_allowed_empty_cache(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies is_tool_allowed returns ok() when cache is empty."""
        result = await remote_client.is_tool_allowed("any_tool")

        assert result.passed is True
        assert result.reason == ""
        assert result.rule_id == ""


class TestRemotePolicyClientAsyncBehavior:
    """Test async behavior and concurrency."""

    @pytest.mark.asyncio
    async def test_concurrent_evaluations_with_polling(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies that evaluations and polling can run concurrently."""
        # Load a policy
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        # Mock successful polling
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            await remote_client.start()

            # Perform multiple concurrent evaluations while polling
            results = await asyncio.gather(
                remote_client.check_input("test 1"),
                remote_client.check_input("test 2"),
                remote_client.check_output("test 3"),
                remote_client.is_tool_allowed("test_tool"),
            )

            # All should complete without error
            assert len(results) == 4
            assert all(r.passed is True for r in results)

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_stop_during_polling(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies that stop() works correctly while polling is active."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            await remote_client.start()

            # Let it poll for a bit
            await asyncio.sleep(0.5)

            # Stop should work cleanly
            await remote_client.stop()

            # Task should be cancelled
            assert remote_client._task is not None
            assert remote_client._task.done()


class TestRemotePolicyClientMultiplePolicies:
    """Test handling multiple policy updates."""

    @pytest.mark.asyncio
    async def test_policy_update_sequence(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies that the client can update policies multiple times."""
        policy1_yaml = """
id: policy-v1
version: 1
status: active
rules:
  - id: rule1
    trigger: on_input
    condition:
      metric: prompt
      operator: contains
      threshold: secret
    action: block
"""

        policy2_yaml = """
id: policy-v2
version: 2
status: active
rules:
  - id: rule2
    trigger: on_input
    condition:
      metric: prompt
      operator: contains
      threshold: password
    action: block
"""

        call_count = 0
        responses = [policy1_yaml, policy2_yaml]

        async def mock_get_side_effect(*args, **kwargs):
            nonlocal call_count
            mock_response = MagicMock()
            mock_response.text = responses[min(call_count, len(responses) - 1)]
            mock_response.status_code = 200
            call_count += 1
            return mock_response

        with patch.object(
            remote_client._client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = mock_get_side_effect

            await remote_client.start()

            # Wait for two polling cycles
            await asyncio.sleep(2.5)

            # Verify multiple updates occurred
            assert mock_get.call_count >= 2

            await remote_client.stop()
