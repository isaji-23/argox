from __future__ import annotations

import logging
import time
from typing import Any
import httpx

from argox.core.state import AgentRunMetrics
from argox.interfaces.exporter import ExporterBase

logger = logging.getLogger(__name__)


class HttpRunExporter(ExporterBase):
    """Exporter that posts AgentRunMetrics to the Collector's /v1/runs endpoint.

    Constructs a POST request containing the serialized metrics to the specified URL.
    Retries are performed with exponential backoff if a network or 5xx server error is hit.
    All exceptions are trapped locally and never propagate to the agent's execution.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        timeout: float = 5.0,
        max_retries: int = 3,
        durable: bool = False,
    ) -> None:
        """Initialize the HttpRunExporter.

        Args:
            endpoint: Base URL of the Collector (e.g. http://localhost:8000).
            api_key: Optional Bearer token for authorization.
            timeout: Maximum time in seconds for a request.
            max_retries: Number of exponential backoff retries on 5xx or network failure.
            durable: If True, requests synchronous persistence at the Collector (sends X-Argox-Durable: true).
        """
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.durable = durable

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.durable:
            headers["X-Argox-Durable"] = "true"

        self._client = httpx.Client(timeout=self.timeout, headers=headers)

    def export(self, metrics: AgentRunMetrics) -> None:
        """Post the run record metrics to the Collector."""
        payload = metrics.to_dict()
        url = f"{self.endpoint}/v1/runs"

        max_attempts = self.max_retries + 1
        last_error = None

        for attempt in range(max_attempts):
            if attempt > 0:
                # Exponential backoff delay: 0.5 * (2 ** (attempt - 1))
                delay = 0.5 * (2 ** (attempt - 1))
                logger.warning(
                    "Retrying HttpRunExporter export to %s in %.2fs (attempt %d/%d). Error: %s",
                    url,
                    delay,
                    attempt + 1,
                    max_attempts,
                    last_error,
                )
                time.sleep(delay)

            try:
                response = self._client.post(url, json=payload)

                if 200 <= response.status_code < 300:
                    # Success
                    return
                elif 500 <= response.status_code < 600:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    # Will loop/retry
                else:
                    # Non-retriable error (e.g. 4xx)
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    metrics.exporter_errors.append(f"HttpRunExporter: {error_msg}")
                    logger.error("HttpRunExporter export failed with non-retriable status: %s", error_msg)
                    return
            except httpx.RequestError as exc:
                last_error = f"RequestError: {type(exc).__name__} ({str(exc)})"
                # Will loop/retry
            except Exception as exc:
                last_error = f"UnexpectedError: {type(exc).__name__} ({str(exc)})"
                # Will loop/retry

        # Exhausted all attempts
        err_detail = last_error or "Unknown error"
        metrics.exporter_errors.append(
            f"HttpRunExporter: Failed to export after {max_attempts} attempts. Last error: {err_detail}"
        )
        logger.error("HttpRunExporter export exhausted all retries. Last error: %s", err_detail)

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
