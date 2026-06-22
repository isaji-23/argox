from __future__ import annotations

import logging
import random
import time
from typing import Any
import httpx

from argox.core.state import AgentRunMetrics
from argox.interfaces.exporter import ExporterBase

logger = logging.getLogger(__name__)


class HttpRunExporter(ExporterBase):
    """Exporter that posts AgentRunMetrics to the Collector's /v1/runs endpoint.

    Constructs a POST request containing the serialized metrics to the specified URL.
    Retries are performed with exponential backoff and jitter if a network error or a
    5xx/429 HTTP status is hit. All exceptions are trapped locally and never propagate.
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
            max_retries: Number of exponential backoff retries on 5xx, 429, or network failure.
            durable: If True, requests synchronous persistence at the Collector (sends X-Argox-Durable: true).
        """
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.durable = durable

        if self.api_key and not self.endpoint.lower().startswith("https://"):
            logger.warning(
                "HttpRunExporter: API key is provided but the endpoint (%s) does not use HTTPS. "
                "The key will travel in plaintext over the network.",
                self.endpoint,
            )

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.durable:
            headers["X-Argox-Durable"] = "true"

        self._client = httpx.Client(timeout=self.timeout, headers=headers)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> HttpRunExporter:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def export(self, metrics: AgentRunMetrics) -> None:
        """Post the run record metrics to the Collector."""
        url = f"{self.endpoint}/v1/runs"

        try:
            payload = metrics.to_dict()
        except Exception as exc:
            err_msg = f"SerializationError: {type(exc).__name__} ({str(exc)})"
            metrics.exporter_errors.append(f"HttpRunExporter: {err_msg}")
            logger.error("HttpRunExporter serialization failed: %s", err_msg)
            return

        max_attempts = self.max_retries + 1
        last_error = None
        next_delay = None

        for attempt in range(max_attempts):
            if attempt > 0:
                if next_delay is not None:
                    delay = next_delay
                    next_delay = None
                else:
                    # Exponential backoff with jitter and a 10s cap
                    base_delay = 0.5 * (2 ** (attempt - 1))
                    jitter = random.uniform(0, 0.1 * base_delay)
                    delay = min(base_delay + jitter, 10.0)

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
                elif response.status_code == 429 or (500 <= response.status_code < 600):
                    # Retriable error codes: 429 (respect Retry-After if present) and 5xx
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            try:
                                retry_seconds = float(retry_after)
                                # Cap the Retry-After value to prevent excessive thread blocking
                                next_delay = min(retry_seconds, 10.0)
                            except ValueError:
                                pass
                else:
                    # Non-retriable error (e.g. other 4xx codes)
                    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                    metrics.exporter_errors.append(f"HttpRunExporter: {error_msg}")
                    logger.error("HttpRunExporter export failed with non-retriable status: %s", error_msg)
                    return
            except httpx.RequestError as exc:
                last_error = f"RequestError: {type(exc).__name__} ({str(exc)})"
                # Will loop/retry
            except Exception as exc:
                # Non-retriable system/program errors (never propagate per contract)
                error_msg = f"UnexpectedError: {type(exc).__name__} ({str(exc)})"
                metrics.exporter_errors.append(f"HttpRunExporter: {error_msg}")
                logger.error("HttpRunExporter export encountered an unexpected exception: %s", error_msg)
                return

        # Exhausted all attempts
        err_detail = last_error or "Unknown error"
        metrics.exporter_errors.append(
            f"HttpRunExporter: Failed to export after {max_attempts} attempts. Last error: {err_detail}"
        )
        logger.error("HttpRunExporter export exhausted all retries. Last error: %s", err_detail)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
