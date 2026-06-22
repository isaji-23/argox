"""Cost enrichment (COL-07, COL-17).

Computes USD cost from token usage and a model price table, on two paths:

* :func:`enrich_cost` populates a span's ``run_cost`` from the canonical GenAI
  token-usage attributes (populated by the normalisation stage). The SDK sums
  ``api_calls`` token counts into the span totals read here, so the per-span
  cost is the per-call sum.
* :func:`enrich_run_cost` prices a run record (``/v1/runs``) from its
  ``model`` and promoted token totals, feeding the ``runs.cost_usd`` backfill
  (COL-17). The run table landed in COL-11 (#105); this is the writer that
  fills the column it left nullable.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

import structlog

from argox_collector import semconv
from argox_collector.enrichment.pricing import PricingTable
from argox_collector.index.base import RunRecord, SpanRecord

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


def enrich_run_cost(record: RunRecord, pricing: PricingTable) -> Optional[float]:
    """Return the USD cost for a run record, or ``None`` when not computable.

    Mirrors :func:`enrich_cost`: a record that already carries ``cost_usd`` is
    returned unchanged, a missing or unknown model yields ``None`` (the column
    stays NULL) with a warning, and ingest never raises here. Cost is derived
    from the promoted ``total_input_tokens`` / ``total_output_tokens`` columns,
    which the run ingest sums from the ``tokens.by_api_call`` breakdown.

    Args:
        record: The indexed run summary to price.
        pricing: Model-name to USD-per-1k price table.

    Returns:
        The computed cost in USD, or ``None`` when the model is absent/unknown.
    """
    if record.cost_usd is not None:
        return record.cost_usd

    model = record.model
    if not model:
        return None

    prices = pricing.get(str(model).lower())
    if prices is None:
        logger.warning("run_cost_unknown_model", model=model, run_id=record.run_id)
        return None

    return (record.total_input_tokens or 0) / 1000 * prices["input"] + (
        record.total_output_tokens or 0
    ) / 1000 * prices["output"]


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
