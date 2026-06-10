"""Tests for the COL-07 enrichment stages (normalisation, cost, residual PII)."""

from __future__ import annotations

from pathlib import Path

from argox_collector.enrichment import pii
from argox_collector.enrichment.cost import enrich_cost
from argox_collector.enrichment.normalize import normalize
from argox_collector.enrichment.pipeline import enrich
from argox_collector.enrichment.pricing import load_pricing
from argox_collector.index.base import SpanRecord
from argox_collector.settings import CollectorSettings


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


def test_pii_scan_tags_event_payload() -> None:
    record = SpanRecord(
        trace_id="t",
        span_id="s",
        attributes={"prompt": "clean"},
        events=(
            {
                "name": "gen_ai.content.completion",
                "timestamp": None,
                "attributes": {"completion": "card 4111 1111 1111 1111 charged"},
            },
        ),
    )
    enriched = pii.scan(record)
    assert enriched.attributes["argox.pii.residual_detected"] is True


def test_pii_scan_ignores_clean_events() -> None:
    record = SpanRecord(
        trace_id="t",
        span_id="s",
        attributes={"prompt": "clean"},
        events=({"name": "retry", "timestamp": None, "attributes": {"n": 2}},),
    )
    assert pii.scan(record) is record


def test_normalize_maps_legacy_token_keys() -> None:
    record = _record(
        **{
            "gen_ai.usage.prompt_tokens": 1000,
            "gen_ai.usage.completion_tokens": 500,
        }
    )
    normalised = normalize(record)
    assert normalised.attributes["gen_ai.usage.input_tokens"] == 1000
    assert normalised.attributes["gen_ai.usage.output_tokens"] == 500


def test_normalize_maps_openinference_keys() -> None:
    record = _record(
        **{
            "llm.model_name": "gpt-4o",
            "llm.token_count.prompt": 10,
            "llm.token_count.completion": 5,
        }
    )
    normalised = normalize(record)
    assert normalised.attributes["gen_ai.request.model"] == "gpt-4o"
    assert normalised.attributes["gen_ai.usage.input_tokens"] == 10
    assert normalised.attributes["gen_ai.usage.output_tokens"] == 5


def test_normalize_canonical_key_wins_over_variant() -> None:
    record = _record(
        **{
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.prompt_tokens": 999,
        }
    )
    assert normalize(record).attributes["gen_ai.usage.input_tokens"] == 100


def test_normalize_no_variants_returns_same_record() -> None:
    record = _record(**{"gen_ai.request.model": "gpt-4o"})
    assert normalize(record) is record


def test_pricing_loads_custom_yaml(tmp_path: Path) -> None:
    table = tmp_path / "pricing.yaml"
    table.write_text(
        "models:\n  custom-model:\n    input: 0.001\n    output: 0.002\n",
        encoding="utf-8",
    )
    pricing = load_pricing(table)
    assert pricing == {"custom-model": {"input": 0.001, "output": 0.002}}


def test_pipeline_normalises_then_costs_and_is_idempotent(tmp_path: Path) -> None:
    settings = CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
    )
    record = _record(
        **{
            "llm.model_name": "gpt-4o",
            "gen_ai.usage.prompt_tokens": 1000,
            "gen_ai.usage.completion_tokens": 500,
            "prompt": "reach me at user@example.com",
        }
    )
    first = enrich([record], settings)[0]
    # 1.0 * 0.0025 + 0.5 * 0.01 = 0.0075, via normalised variant keys.
    assert first.run_cost == 0.0075
    assert first.attributes["argox.pii.residual_detected"] is True

    second = enrich([first], settings)[0]
    assert second == first
