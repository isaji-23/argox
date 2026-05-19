"""
POL-04 — RemotePolicyClient
===========================
A remote policy client that fetches policy bundles from a central Collector API.

This client implements a background polling mechanism that periodically fetches
policy updates from a remote server. The hot-path evaluation methods (check_input,
check_output, is_tool_allowed) are completely synchronous and perform no network I/O.
They delegate to the in-memory PolicyCache for O(1) evaluation.

Background Polling:
    The client maintains an asyncio.Task that runs a polling loop. The loop:
    1. Fetches the policy bundle from the endpoint every refresh_interval_s seconds.
    2. Parses and loads the policy into the local cache on success.
    3. On network or parsing errors, retains the last known valid policy and logs a warning.
    4. Never crashes or propagates exceptions to the caller.

Design Notes:
    - **Fail-open behavior**: Network errors do not block or terminate the client.
      The last valid policy remains active. Errors are logged for operator visibility.
    - **Zero hot-path network I/O**: Policy evaluation methods call cache.evaluate() only.
      No requests are made during check_input, check_output, or is_tool_allowed.
    - **Stateful polling**: The client requires explicit start() and stop() calls
      to manage the background task lifecycle.

Example usage::

    client = RemotePolicyClient(
        endpoint_url="https://collector.example.com/policy",
        refresh_interval_s=30
    )
    await client.start()  # Begins background polling

    try:
        result = await client.check_input("user prompt")
        if not result.passed:
            raise PermissionError(f"Policy violation: {result.reason}")
    finally:
        await client.stop()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from argox.interfaces.policy import (
    PolicyClient,
    PolicyResult,
    TRIGGER_ON_INPUT,
    TRIGGER_ON_OUTPUT,
    TRIGGER_ON_TOOL_CALL,
)
from argox.policies.cache import PolicyCache
from argox.policies.parser import PolicyParser

logger = logging.getLogger(__name__)


class RemotePolicyClient(PolicyClient):
    """
    Remote policy client with background polling and fail-open semantics.

    Fetches policy bundles periodically from a remote Collector API and maintains
    them in a local in-memory cache. The background polling task handles network
    resilience: transient failures do not interrupt service. Policy evaluation is
    completely synchronous and performs no network I/O.

    The client requires explicit lifecycle management via start() and stop() methods.
    Attempting to evaluate policies before calling start() will return PolicyResult.ok()
    (empty cache behavior).

    Attributes:
        endpoint_url: URL of the remote Collector API policy endpoint.
        refresh_interval_s: Polling interval in seconds.
        cache: In-process cache storing compiled policy rules.
        parser: YAML policy parser.
        _client: httpx.AsyncClient for making policy fetch requests.
        _task: asyncio.Task for the background polling loop (None before start()).
    """

    def __init__(
        self,
        endpoint_url: str,
        refresh_interval_s: int = 60,
    ) -> None:
        """
        Initialize the RemotePolicyClient.

        Args:
            endpoint_url: URL of the remote policy endpoint (e.g., https://collector/policy).
            refresh_interval_s: Polling interval in seconds. Defaults to 60.
        """
        self.endpoint_url: str = endpoint_url
        self.refresh_interval_s: int = refresh_interval_s
        self.cache: PolicyCache = PolicyCache()
        self.parser: PolicyParser = PolicyParser()
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """
        Start the background policy polling task.

        This method creates an asyncio.Task that runs the _poll_loop() coroutine.
        The task runs in the background and will not block the caller.

        On first start or after stop(), an eager fetch is performed to populate the cache
        before polling begins. This ensures policies are available immediately, avoiding
        the cold-start window where all evaluations would pass due to empty cache.

        Safe to call multiple times; if a task is already running, this is a no-op.
        """
        if self._task is None or self._task.done():
            # Recreate HTTP client if it was closed
            if self._client is None or self._client.is_closed():
                self._client = httpx.AsyncClient(timeout=10.0)

            # Eager fetch before starting the polling loop
            try:
                response = await self._client.get(self.endpoint_url)
                response.raise_for_status()
                policy = self.parser.parse_yaml(response.text)
                self.cache.load_policy(policy)
                logger.info(
                    "RemotePolicyClient initial policy fetched from %s",
                    self.endpoint_url,
                )
            except Exception:
                logger.exception(
                    "Failed to fetch initial policy from %s. Starting with empty cache.",
                    self.endpoint_url,
                )
                # Continue anyway; the polling loop will retry periodically

            self._task = asyncio.create_task(self._poll_loop())
            logger.info(
                "RemotePolicyClient background polling started. Endpoint: %s, interval: %ds",
                self.endpoint_url,
                self.refresh_interval_s,
            )

    async def stop(self) -> None:
        """
        Stop the background policy polling task.

        Cancels the polling task and closes the HTTP client. This method waits
        for the task to be cancelled before returning.

        Safe to call even if the client is not running.
        """
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("RemotePolicyClient background polling stopped")

        if self._client is not None and not self._client.is_closed():
            await self._client.aclose()

    async def _poll_loop(self) -> None:
        """
        Background polling loop that fetches and updates policy.

        This coroutine runs indefinitely in a background task. On each iteration:
        1. Attempts to fetch the policy bundle from the remote endpoint.
        2. Parses and loads the policy into the cache if successful.
        3. On any error (network, parsing, etc.), logs a warning with traceback and retains
           the last known valid policy.
        4. Sleeps for refresh_interval_s seconds before the next fetch.
        5. Catches asyncio.CancelledError to gracefully shut down when stop() is called.

        This method never raises an exception to the caller (except CancelledError
        during shutdown). All transient errors are logged and absorbed.
        """
        try:
            while True:
                try:
                    assert self._client is not None, "HTTP client not initialized"
                    response = await self._client.get(self.endpoint_url)
                    response.raise_for_status()

                    # Parse and load the policy
                    policy = self.parser.parse_yaml(response.text)
                    self.cache.load_policy(policy)
                    logger.debug(
                        "Policy updated from remote endpoint: %s",
                        self.endpoint_url,
                    )

                except Exception:
                    logger.exception(
                        "Failed to fetch or parse policy from %s. "
                        "Retaining last known policy.",
                        self.endpoint_url,
                    )
                    # Continue the loop; the cache retains the previous policy

                await asyncio.sleep(self.refresh_interval_s)

        except asyncio.CancelledError:
            logger.debug("RemotePolicyClient polling loop cancelled")
            raise

    async def check_input(self, text: str) -> PolicyResult:
        """
        Evaluate the user input prompt against cached policies.

        Hot-path method: performs no network I/O. Delegates entirely to the
        in-memory policy cache.

        Args:
            text: The user's input prompt.

        Returns:
            PolicyResult.ok() if input is acceptable or cache is empty.
            PolicyResult.block(...) if a blocking rule matched.
            PolicyResult.alert(...) if an alert rule matched.
        """
        try:
            return self.cache.evaluate(
                trigger=TRIGGER_ON_INPUT, metrics={"prompt": text}
            )
        except Exception:
            logger.exception("Unexpected error during input policy evaluation")
            # Fail closed: treat evaluation errors as policy violations
            return PolicyResult.block(
                reason="Policy evaluation error. Request denied.",
                rule_id="evaluation_error",
            )

    async def check_output(self, text: str) -> PolicyResult:
        """
        Evaluate the agent's output against cached policies.

        Hot-path method: performs no network I/O. Delegates entirely to the
        in-memory policy cache.

        Args:
            text: The agent's output response.

        Returns:
            PolicyResult.ok() if output is acceptable or cache is empty.
            PolicyResult.block(...) if a blocking rule matched.
            PolicyResult.alert(...) if an alert rule matched.
        """
        try:
            return self.cache.evaluate(
                trigger=TRIGGER_ON_OUTPUT, metrics={"output": text}
            )
        except Exception:
            logger.exception("Unexpected error during output policy evaluation")
            # Fail closed: treat evaluation errors as policy violations
            return PolicyResult.block(
                reason="Policy evaluation error. Response blocked.",
                rule_id="evaluation_error",
            )

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        """
        Determine if a tool is allowed to be used by the agent.

        Hot-path method: performs no network I/O. Delegates entirely to the
        in-memory policy cache.

        Args:
            tool_name: Name of the tool as registered in the agent.

        Returns:
            PolicyResult.ok() if tool is allowed or cache is empty.
            PolicyResult.block(...) if a blocking rule matched.
            PolicyResult.alert(...) if an alert rule matched.
        """
        try:
            return self.cache.evaluate(
                trigger=TRIGGER_ON_TOOL_CALL, metrics={"tool_name": tool_name}
            )
        except Exception:
            logger.exception("Unexpected error during tool policy evaluation")
            # Fail closed: treat evaluation errors as policy violations
            return PolicyResult.block(
                reason="Policy evaluation error. Tool access denied.",
                rule_id="evaluation_error",
            )
