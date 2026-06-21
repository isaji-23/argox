"""Load the model-to-price table used by the cost enricher.

The runtime source of truth is the bundled ``pricing.yaml`` (loaded by
:func:`load_pricing`, cached by :func:`cached_pricing`). It is a committed
snapshot of LiteLLM's price map: :func:`fetch_remote_pricing` pulls the live
LiteLLM JSON and :func:`render_pricing_yaml` serialises it back into the
``pricing.yaml`` shape, so a scheduled job (``argox-collector refresh-pricing``)
can regenerate the file and open a PR. This keeps the cost basis deterministic,
version-controlled and reviewable, with no network dependency on the ingest
path (see ADR-0008).
"""

from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog
import yaml

logger = structlog.get_logger(__name__)

# Bundled default table shipped alongside this module.
DEFAULT_PRICING_PATH = Path(__file__).with_name("pricing.yaml")

# Model name -> {"input": usd_per_1k, "output": usd_per_1k}.
PricingTable = dict[str, dict[str, float]]

# LiteLLM publishes per-token prices; the Argox table is per 1,000 tokens, so
# every fetched cost is scaled by this factor.
_TOKENS_PER_UNIT = 1000.0

# Default LiteLLM price map used by the refresh job (not fetched at runtime).
LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

# Network timeout (seconds) for the refresh-time fetch.
_FETCH_TIMEOUT_SECONDS = 15.0


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
    source = path or DEFAULT_PRICING_PATH
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


@lru_cache(maxsize=8)
def cached_pricing(path: Optional[Path] = None) -> PricingTable:
    """Return the loaded pricing table, cached per path.

    The bundled YAML is read once and reused across requests; both the span
    enrichment pipeline and the run-cost backfill share this cache. Call
    :meth:`cached_pricing.cache_clear` to force a reload (e.g. after the
    refresh job rewrites the file in a long-lived process).
    """
    return load_pricing(path)


def fetch_remote_pricing(
    url: str, *, timeout: float = _FETCH_TIMEOUT_SECONDS
) -> PricingTable:
    """Fetch a LiteLLM-format price map and normalise it to the Argox shape.

    LiteLLM's ``model_prices_and_context_window.json`` keys each model to a
    record carrying ``input_cost_per_token`` / ``output_cost_per_token`` in USD
    per single token. Those are scaled to USD per 1,000 tokens to match the
    bundled table. Entries that carry neither cost (or whose costs are not
    numeric) are skipped rather than priced at zero.

    This is a refresh-time helper for :func:`render_pricing_yaml`, not called on
    the ingest path.

    Args:
        url: Location of the LiteLLM JSON map.
        timeout: Socket timeout in seconds for the fetch.

    Returns:
        A model-name (lowercased) to ``{"input", "output"}`` USD-per-1k table.

    Raises:
        OSError, ValueError: On a network failure or unparseable payload.
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


def filter_pricing(table: PricingTable, prefixes: tuple[str, ...]) -> PricingTable:
    """Return only the models whose name starts with one of ``prefixes``.

    Lets the refresh job keep the snapshot small (e.g. the providers in use)
    instead of committing LiteLLM's full multi-thousand-model map. An empty
    ``prefixes`` returns the table unchanged.
    """
    if not prefixes:
        return table
    lowered = tuple(p.lower() for p in prefixes)
    return {
        name: prices
        for name, prices in table.items()
        if name.startswith(lowered)
    }


def render_pricing_yaml(table: PricingTable) -> str:
    """Serialise a price table into the committed ``pricing.yaml`` shape.

    Output is deterministic (models sorted by name) so a regeneration produces
    a clean, reviewable diff. Prices are USD per 1,000 tokens, matching
    :func:`load_pricing`.
    """
    header = (
        "# Per-model LLM pricing used by the cost enricher (COL-07, COL-17).\n"
        "#\n"
        "# Prices are USD per 1,000 tokens. Keys are matched case-insensitively\n"
        "# against the model id (gen_ai.request.model / a run's reported model).\n"
        "# This file is a committed snapshot of the LiteLLM price map; regenerate\n"
        "# it with 'argox-collector refresh-pricing'. Override at runtime with\n"
        "# ARGOX_PRICING_TABLE_PATH; unknown models log a warning and skip.\n"
    )
    models = {
        name: {"input": prices["input"], "output": prices["output"]}
        for name, prices in sorted(table.items())
    }
    body = yaml.safe_dump(
        {"models": models}, sort_keys=False, default_flow_style=False
    )
    return header + body
