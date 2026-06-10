"""Per-span cost enrichment (COL-07).

Computes ``run_cost`` (USD) from the canonical GenAI token-usage attributes
(populated by the normalisation stage) and a model price table. The SDK sums
``api_calls`` token counts into the span totals read here, so the per-span
cost is the per-call sum. Joining run records (``api_calls[]`` written by the
``/v1/runs`` path) into a ``runs.cost_usd`` column is deferred until COL-11
(#105) lands that table.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

import structlog

from argox_collector import semconv
from argox_collector.enrichment.pricing import PricingTable
from argox_collector.index.base import SpanRecord

logger = structlog.get_logger(__name__)


def enrich_cost(record: SpanRecord, pricing: PricingTable) -> SpanRecord:
    """Return ``record`` with ``run_cost`` populated when computable.

    Idempotent: a record that already carries ``run_cost`` is returned
    unchanged, so re-running enrichment never double-counts. Unknown models log
    a warning and leave ``run_cost`` as ``None``.
    """
    if record.run_cost is not None:
        return record

    attrs = record.attributes
    model = attrs.get(semconv.GEN_AI_REQUEST_MODEL) or attrs.get(
        semconv.GEN_AI_RESPONSE_MODEL
    )
    if not model:
        return record

    prices = pricing.get(str(model).lower())
    if prices is None:
        logger.warning("cost_unknown_model", model=model, span_id=record.span_id)
        return record

    input_tokens = _as_int(attrs.get(semconv.GEN_AI_USAGE_INPUT_TOKENS))
    output_tokens = _as_int(attrs.get(semconv.GEN_AI_USAGE_OUTPUT_TOKENS))
    if input_tokens is None and output_tokens is None:
        return record

    cost = (input_tokens or 0) / 1000 * prices["input"] + (
        output_tokens or 0
    ) / 1000 * prices["output"]
    return dataclasses.replace(record, run_cost=cost)


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
