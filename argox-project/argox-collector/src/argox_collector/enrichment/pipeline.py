"""Compose the basic enrichment stages applied at ingest time."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from argox_collector.enrichment import pii
from argox_collector.enrichment.cost import enrich_cost
from argox_collector.enrichment.pricing import PricingTable, load_pricing
from argox_collector.index.base import SpanRecord
from argox_collector.settings import CollectorSettings


@lru_cache(maxsize=8)
def _cached_pricing(path: Optional[Path]) -> PricingTable:
    return load_pricing(path)


def enrich(records: list[SpanRecord], settings: CollectorSettings) -> list[SpanRecord]:
    """Apply cost then residual-PII enrichment to a batch of span records.

    Returns the records unchanged when ``enrichment_enabled`` is ``False``. Each
    stage is idempotent, so re-running enrichment is safe.
    """
    if not settings.enrichment_enabled:
        return records

    pricing = _cached_pricing(settings.pricing_table_path)
    return [pii.scan(enrich_cost(record, pricing)) for record in records]
