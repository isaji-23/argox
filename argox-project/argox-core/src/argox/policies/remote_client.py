"""
POL-04 — RemotePolicyClient
===========================
A remote policy client that fetches policy bundles from a central Collector API.

Network Semantics:
    - **Polling failures (network, parse errors)**: Fail-open. Retains the last known
      valid policy and logs warnings. Service continues uninterrupted.
    - **Evaluation errors (predicate failures)**: Fail-closed. Returns PolicyResult.block()
      to prevent unsafe defaults during system errors.

Hot-path Methods:
    check_input(), check_output(), is_tool_allowed() perform zero network I/O.
    They delegate entirely to the in-memory PolicyCache for O(1) evaluation.
    These methods fail-closed: evaluation errors return block() results.

Background Polling:
    An asyncio.Task runs _poll_loop() which:
    1. Fetches policy from endpoint every refresh_interval_s seconds.
    2. Parses and loads policy into local cache on success.
    3. On error, logs warning and retains previous policy (fail-open).
    4. Never crashes or propagates exceptions to the caller.

Cold-start Behavior:
    On start(), performs an eager fetch to populate the cache immediately.
    If eager fetch fails, the cache remains empty and all evaluations pass
    (no policies to enforce). Retries continue in the background polling loop.
    If policy_cache_dir is configured, loads persisted policy on cold-start
    (disk fallback for issue #40 resilience).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Union

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
    Remote policy client with background polling and fail-open network semantics.

    Fetches policy bundles periodically from a remote Collector API and maintains
    them in a local in-memory cache. The background polling task handles network
    resilience: transient failures do not interrupt service. Policy evaluation is
    completely synchronous and performs no network I/O.

    Network Semantics:
        - **Polling failures (network, parse errors)**: Fail-open. Retains the last
          known valid policy and logs warnings. Service continues uninterrupted.
        - **Evaluation errors (predicate failures)**: Fail-closed. Returns PolicyResult.block()
          to prevent unsafe defaults during system errors.

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
        policy_cache_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        """
        Initialize the RemotePolicyClient.

        Args:
            endpoint_url: URL of the remote policy endpoint (e.g., https://collector/policy).
            refresh_interval_s: Polling interval in seconds. Defaults to 60.
            policy_cache_dir: Directory for disk-based policy fallback. If provided,
                fetched policies are written to this directory and loaded on cold-start
                (disk fallback for issue #40). Defaults to None (memory-only).
        """
        self.endpoint_url: str = endpoint_url
        self.refresh_interval_s: int = refresh_interval_s
        self.policy_cache_dir: Optional[Path] = Path(policy_cache_dir) if policy_cache_dir else None
        self.cache: PolicyCache = PolicyCache()
        self.parser: PolicyParser = PolicyParser()
        self._client: Optional[httpx.AsyncClient] = None
        self._task: Optional[asyncio.Task[None]] = None

        # Ensure policy cache directory exists if configured (prepare for disk writes)
        if self.policy_cache_dir is not None:
            self.policy_cache_dir.mkdir(parents=True, exist_ok=True)

        # Load policy from disk on cold-start if available (issue #40 fallback)
        if self.policy_cache_dir is not None:
            self._load_policy_from_disk()

    def _load_policy_from_disk(self) -> None:
        """
        Load persisted policy from disk fallback directory (issue #40).
        
        If a policy file exists, parses and loads it into the cache.
        Failures are logged as warnings; cache remains empty if fallback unavailable.
        """
        if self.policy_cache_dir is None:
            return
            
        policy_file = self.policy_cache_dir / "policy.yaml"
        if not policy_file.exists():
            return
            
        try:
            with open(policy_file, "r", encoding="utf-8") as f:
                yaml_content = f.read()
            policy = self.parser.parse_yaml(yaml_content)
            self.cache.load_policy(policy)
            logger.info(
                "RemotePolicyClient loaded policy from disk fallback: %s",
                policy_file,
            )
        except Exception:
            logger.exception(
                "Failed to load policy from disk fallback at %s. "
                "Cache remains empty until remote fetch succeeds.",
                policy_file,
            )

    def _save_policy_to_disk(self, yaml_content: str) -> None:
        """
        Persist fetched policy to disk for cold-start fallback (issue #40).

        Uses atomic rename to ensure disk writes are not corrupted by process death
        or concurrent reads during writing.

        Failures are logged as warnings; cache has already been updated
        so the service is not affected by disk write failures.
        """
        if self.policy_cache_dir is None:
            return

        try:
            policy_file = self.policy_cache_dir / "policy.yaml"
            tmp_file = self.policy_cache_dir / "policy.yaml.tmp"

            # Write to temporary file first
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(yaml_content)

            # Atomic rename (POSIX and Windows)
            os.replace(str(tmp_file), str(policy_file))

            logger.debug("RemotePolicyClient persisted policy to disk: %s", policy_file)
        except Exception:
            logger.exception(
                "Failed to persist policy to disk fallback at %s. "
                "Cache is updated but process restart will not have fallback.",
                self.policy_cache_dir,
            )

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
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=10.0)

            # Eager fetch before starting the polling loop
            try:
                response = await self._client.get(self.endpoint_url)
                response.raise_for_status()
                policy = self.parser.parse_yaml(response.text)
                self.cache.load_policy(policy)
                self._save_policy_to_disk(response.text)
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

        if self._client is not None and not self._client.is_closed:
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
                    if self._client is None:
                        raise RuntimeError("HTTP client not initialized during polling")
                    response = await self._client.get(self.endpoint_url)
                    response.raise_for_status()

                    # Parse and load the policy
                    policy = self.parser.parse_yaml(response.text)
                    self.cache.load_policy(policy)
                    self._save_policy_to_disk(response.text)
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
