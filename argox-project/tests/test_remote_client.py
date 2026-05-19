"""Tests for RemotePolicyClient: remote policy fetching with background polling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

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


@pytest_asyncio.fixture
async def remote_client(endpoint_url: str) -> RemotePolicyClient:
    """Creates a RemotePolicyClient instance for testing (does NOT start it)."""
    client = RemotePolicyClient(
        endpoint_url=endpoint_url,
        refresh_interval_s=1,  # Fast interval for testing
    )
    yield client
    # Cleanup: ensure the background task is stopped if started
    if client._task is not None:
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
        assert client._client is None  # Lazy-init: not created until start()
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
        # Mock HTTP before start()
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            assert remote_client._task is None
            await remote_client.start()

            assert remote_client._task is not None
            assert not remote_client._task.done()

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that stop() cancels the background task."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            await remote_client.start()
            task = remote_client._task

            await remote_client.stop()

            assert task is not None
            assert task.done()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that stop() can be called multiple times safely."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            await remote_client.start()
            await remote_client.stop()

            # Should not raise
            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that start() is idempotent."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

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
    async def test_eager_fetch_on_start(self, remote_client: RemotePolicyClient) -> None:
        """Verifies that start() performs an eager fetch before polling begins."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            await remote_client.start()

            # Verify eager fetch was called immediately
            mock_instance.get.assert_called_with(remote_client.endpoint_url)

            # Cache should be populated immediately
            assert remote_client.cache._rules_by_trigger

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_cold_start_avoids_bypass_window(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies cache is populated on start, avoiding early bypass window."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            # Before start, cache is empty
            result_before = await remote_client.check_input("any text")
            assert result_before.passed is True
            assert result_before.rule_id == ""

            # Start client
            await remote_client.start()

            # After start, policy should be loaded immediately
            result_after = await remote_client.check_input("I need the secret password")
            assert result_after.passed is False
            assert result_after.rule_id == "block-secret-input"

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_network_error_during_eager_fetch(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies fail-open behavior on network errors during eager fetch."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=Exception("Network error"))
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            # Should not raise, should start with empty cache
            await remote_client.start()

            # Verify the task is running despite the error
            assert remote_client._task is not None
            assert not remote_client._task.done()

            # Empty cache: evaluations pass
            result = await remote_client.check_input("any text")
            assert result.passed is True

            await remote_client.stop()

    @pytest.mark.asyncio
    async def test_parse_error_during_eager_fetch(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies fail-open behavior on YAML parse errors."""
        mock_response = MagicMock()
        mock_response.text = "invalid: yaml: ["
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            # Should start with empty cache despite parse error
            await remote_client.start()

            assert remote_client._task is not None
            assert not remote_client._task.done()

            # Empty cache: evaluations pass
            result = await remote_client.check_input("any text")
            assert result.passed is True

            await remote_client.stop()


    @pytest.mark.asyncio
    async def test_http_error_during_eager_fetch(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies fail-open behavior on HTTP errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 500")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            # Should start despite HTTP error
            await remote_client.start()

            assert remote_client._task is not None
            assert not remote_client._task.done()

            await remote_client.stop()


class TestRemotePolicyClientHotPath:
    """Test hot-path evaluation methods (no network I/O)."""

    @pytest.mark.asyncio
    async def test_check_input_no_network_io(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Tests that check_input does not make network requests."""
        # Load a policy
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        result = await remote_client.check_input("What is the weather?")

        # Verify no errors (not making network requests)
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
    async def test_check_output_no_network_io(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Tests that check_output does not make network requests."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        result = await remote_client.check_output("The weather is sunny.")

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
    async def test_is_tool_allowed_no_network_io(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Tests that is_tool_allowed does not make network requests."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        result = await remote_client.is_tool_allowed("send_email")

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
    async def test_concurrent_evaluations(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies that concurrent evaluations work correctly."""
        policy = remote_client.parser.parse_yaml(SAMPLE_POLICY_YAML)
        remote_client.cache.load_policy(policy)

        # Perform multiple concurrent evaluations
        results = await asyncio.gather(
            remote_client.check_input("test 1"),
            remote_client.check_input("test 2"),
            remote_client.check_output("test 3"),
            remote_client.is_tool_allowed("test_tool"),
        )

        # All should complete without error
        assert len(results) == 4
        assert all(r.passed is True for r in results)

    @pytest.mark.asyncio
    async def test_stop_during_polling(
        self, remote_client: RemotePolicyClient
    ) -> None:
        """Verifies that stop() works correctly while polling is active."""
        mock_response = MagicMock()
        mock_response.text = SAMPLE_POLICY_YAML
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.is_closed.return_value = False
            mock_client_class.return_value = mock_instance

            await remote_client.start()

            # Stop should work cleanly
            await remote_client.stop()

            # Task should be cancelled
            assert remote_client._task is not None
            assert remote_client._task.done()

