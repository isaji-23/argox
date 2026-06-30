"""Compose the enrichment stages applied at ingest time (COL-07).

Stage order matters: GenAI attribute normalisation runs first so the cost
stage only has to read the canonical keys, and the residual-PII scan runs
last over the final attribute set.
"""

from __future__ import annotations

from argox_collector.enrichment import pii
from argox_collector.enrichment.cost import enrich_cost
from argox_collector.enrichment.normalize import normalize
from argox_collector.enrichment.pricing import cached_pricing
from argox_collector.index.base import SpanRecord
from argox_collector.settings import CollectorSettings


def enrich(records: list[SpanRecord], settings: CollectorSettings) -> list[SpanRecord]:
    """Apply normalisation, cost, and residual-PII enrichment to a batch.

    Returns the records unchanged when ``enrichment_enabled`` is ``False``. Each
    stage is idempotent, so re-running enrichment is safe.
    """
    if not settings.enrichment_enabled:
        return records

    pricing = cached_pricing(settings.pricing_table_path)
    return [pii.scan(enrich_cost(normalize(record), pricing)) for record in records]
