"""Tests for the COL-03 basic enrichment stages (cost + residual PII)."""

from __future__ import annotations

from argox_collector.enrichment import pii
from argox_collector.enrichment.cost import enrich_cost
from argox_collector.enrichment.pricing import load_pricing
from argox_collector.index.base import SpanRecord


def _record(**attrs) -> SpanRecord:
    return SpanRecord(trace_id="t", span_id="s", attributes=attrs)


def test_cost_computed_for_known_model() -> None:
    pricing = load_pricing()
    record = _record(
        **{
            "gen_ai.request.model": "gpt-4o",
            "gen_ai.usage.input_tokens": 1000,
            "gen_ai.usage.output_tokens": 500,
        }
    )
    enriched = enrich_cost(record, pricing)
    # 1.0 * 0.0025 + 0.5 * 0.01 = 0.0075
    assert enriched.run_cost == 0.0075


def test_cost_unknown_model_leaves_none() -> None:
    pricing = load_pricing()
    record = _record(
        **{
            "gen_ai.request.model": "mystery-model",
            "gen_ai.usage.input_tokens": 1000,
        }
    )
    assert enrich_cost(record, pricing).run_cost is None


def test_cost_is_idempotent_when_already_set() -> None:
    pricing = load_pricing()
    record = SpanRecord(
        trace_id="t",
        span_id="s",
        run_cost=0.42,
        attributes={
            "gen_ai.request.model": "gpt-4o",
            "gen_ai.usage.input_tokens": 1000,
            "gen_ai.usage.output_tokens": 500,
        },
    )
    assert enrich_cost(record, pricing).run_cost == 0.42


def test_pii_scan_tags_email() -> None:
    record = _record(**{"prompt": "reach me at user@example.com please"})
    enriched = pii.scan(record)
    assert enriched.attributes["argox.pii.residual_detected"] is True


def test_pii_scan_tags_iban() -> None:
    record = _record(**{"note": "IBAN ES9121000418450200051332"})
    assert pii.scan(record).attributes["argox.pii.residual_detected"] is True


def test_pii_scan_leaves_clean_span_untouched() -> None:
    record = _record(**{"prompt": "summarise the quarterly report"})
    enriched = pii.scan(record)
    assert "argox.pii.residual_detected" not in enriched.attributes
    assert enriched is record


def test_pii_scan_is_idempotent() -> None:
    record = _record(
        **{
            "prompt": "user@example.com",
            "argox.pii.residual_detected": True,
        }
    )
    assert pii.scan(record) is record
