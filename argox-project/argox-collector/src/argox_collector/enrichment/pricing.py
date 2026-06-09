"""Load the model-to-price table used by the cost enricher."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
import yaml

logger = structlog.get_logger(__name__)

# Bundled default table shipped alongside this module.
_DEFAULT_PRICING_PATH = Path(__file__).with_name("pricing.yaml")

# Model name -> {"input": usd_per_1k, "output": usd_per_1k}.
PricingTable = dict[str, dict[str, float]]


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
