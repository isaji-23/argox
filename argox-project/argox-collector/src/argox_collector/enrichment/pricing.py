"""Load the model-to-price table used by the cost enricher.

Two sources feed the same :data:`PricingTable` shape: the bundled
``pricing.yaml`` (loaded by :func:`load_pricing`) and a remote LiteLLM price
map (fetched by :func:`fetch_remote_pricing`). :class:`PricingProvider` wraps
both with an in-memory TTL cache and a graceful fallback, so the run-cost
backfill (COL-17) can prefer live prices without making ingest depend on the
network being reachable.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import structlog
import yaml

logger = structlog.get_logger(__name__)

# Bundled default table shipped alongside this module.
_DEFAULT_PRICING_PATH = Path(__file__).with_name("pricing.yaml")

# Model name -> {"input": usd_per_1k, "output": usd_per_1k}.
PricingTable = dict[str, dict[str, float]]

# LiteLLM publishes per-token prices; the Argox table is per 1,000 tokens, so
# every fetched cost is scaled by this factor.
_TOKENS_PER_UNIT = 1000.0

# Network timeout (seconds) for a remote price fetch. Kept short so a slow or
# unreachable host degrades to the bundled table quickly instead of stalling.
_FETCH_TIMEOUT_SECONDS = 5.0


def load_pricing(path: Optional[Path] = None) -> PricingTable:
    """Load the pricing table from YAML.

    Args:
        path: Optional override path. When ``None`` the bundled
            ``pricing.yaml`` is used.

    Returns:
        A mapping of lowercase model name to ``{"input", "output"}`` USD prices
        per 1,000 tokens. Returns an empty table (and logs a warning) when the
        file is missing or malformed, so enrichment degrades gracefully.
    """
    source = path or _DEFAULT_PRICING_PATH
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("pricing_table_load_failed", path=str(source), error=str(exc))
        return {}

    models = raw.get("models", {}) if isinstance(raw, dict) else {}
    table: PricingTable = {}
    for name, prices in models.items():
        if not isinstance(prices, dict):
            continue
        try:
            table[str(name).lower()] = {
                "input": float(prices["input"]),
                "output": float(prices["output"]),
            }
        except (KeyError, TypeError, ValueError):
            logger.warning("pricing_table_bad_entry", model=name)
    return table


def fetch_remote_pricing(
    url: str, *, timeout: float = _FETCH_TIMEOUT_SECONDS
) -> PricingTable:
    """Fetch a LiteLLM-format price map and normalise it to the Argox shape.

    LiteLLM's ``model_prices_and_context_window.json`` keys each model to a
    record carrying ``input_cost_per_token`` / ``output_cost_per_token`` in USD
    per single token. Those are scaled to USD per 1,000 tokens to match the
    bundled table. Entries that carry neither cost (or whose costs are not
    numeric) are skipped rather than priced at zero.

    Args:
        url: Location of the LiteLLM JSON map.
        timeout: Socket timeout in seconds for the fetch.

    Returns:
        A model-name (lowercased) to ``{"input", "output"}`` USD-per-1k table.

    Raises:
        OSError, ValueError: On a network failure or unparseable payload, so
            :class:`PricingProvider` can fall back to the bundled table.
    """
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        raw = json.loads(response.read().decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("remote pricing payload is not a JSON object")

    table: PricingTable = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        input_cost = entry.get("input_cost_per_token")
        output_cost = entry.get("output_cost_per_token")
        if input_cost is None and output_cost is None:
            continue
        try:
            table[str(name).lower()] = {
                "input": float(input_cost or 0.0) * _TOKENS_PER_UNIT,
                "output": float(output_cost or 0.0) * _TOKENS_PER_UNIT,
            }
        except (TypeError, ValueError):
            logger.warning("pricing_remote_bad_entry", model=name)
    return table


class PricingProvider:
    """Resolve the model-price table, preferring a cached remote map.

    The remote map is fetched at most once per ``ttl_seconds`` and held in
    memory. Any fetch failure (or an empty result) falls back to the bundled
    YAML table, so cost enrichment degrades gracefully instead of failing
    ingest. Access is thread-safe: ingest runs the backfill from background
    tasks and the durable threadpool.
    """

    def __init__(
        self,
        *,
        remote_url: Optional[str] = None,
        ttl_seconds: float = 6 * 60 * 60,
        fallback_path: Optional[Path] = None,
        fetcher: Callable[[str], PricingTable] = fetch_remote_pricing,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialise the provider.

        Args:
            remote_url: LiteLLM map URL. ``None`` or empty disables the remote
                fetch entirely and the provider serves the bundled table.
            ttl_seconds: Maximum age of a cached table before it is refreshed.
            fallback_path: Optional override for the bundled YAML table.
            fetcher: Injection point for the remote fetch (tests pass a stub).
            clock: Monotonic clock, injectable for deterministic TTL tests.
        """
        self._remote_url = remote_url
        self._ttl = ttl_seconds
        self._fallback_path = fallback_path
        self._fetcher = fetcher
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: Optional[PricingTable] = None
        self._fetched_at = 0.0

    def get_table(self) -> PricingTable:
        """Return the current price table, refreshing the cache when stale."""
        with self._lock:
            if (
                self._cache is not None
                and (self._clock() - self._fetched_at) < self._ttl
            ):
                return self._cache
            self._cache = self._load()
            self._fetched_at = self._clock()
            return self._cache

    def _load(self) -> PricingTable:
        if self._remote_url:
            try:
                table = self._fetcher(self._remote_url)
            except Exception as exc:  # noqa: BLE001 - any failure must fall back
                logger.warning(
                    "pricing_remote_fetch_failed",
                    url=self._remote_url,
                    error=str(exc),
                )
            else:
                if table:
                    return table
                logger.warning("pricing_remote_empty", url=self._remote_url)
        return load_pricing(self._fallback_path)
