"""Tests for the COL-17 live pricing provider (remote fetch + cache + fallback)."""

from __future__ import annotations

import io
import json

from argox_collector.enrichment import pricing as pricing_mod
from argox_collector.enrichment.pricing import (
    PricingProvider,
    fetch_remote_pricing,
    load_pricing,
)


def test_fetch_remote_pricing_normalises_per_token_to_per_1k(monkeypatch) -> None:
    payload = {
        "gpt-4o": {
            "input_cost_per_token": 0.0000025,
            "output_cost_per_token": 0.00001,
        },
        # No costs -> skipped rather than priced at zero.
        "sample_spec": {"max_tokens": 128000},
    }

    def fake_urlopen(url, timeout):  # noqa: ANN001 - test stub
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(pricing_mod.urllib.request, "urlopen", fake_urlopen)

    table = fetch_remote_pricing("https://example.test/prices.json")
    # Per-token prices scaled by 1,000 to USD per 1k tokens.
    assert table["gpt-4o"]["input"] == 0.0025
    assert table["gpt-4o"]["output"] == 0.01
    assert "sample_spec" not in table


def test_provider_caches_within_ttl() -> None:
    calls = {"n": 0}

    def fetcher(url: str):
        calls["n"] += 1
        return {"gpt-4o": {"input": 0.001, "output": 0.002}}

    clock = {"t": 0.0}
    provider = PricingProvider(
        remote_url="https://example.test",
        ttl_seconds=100,
        fetcher=fetcher,
        clock=lambda: clock["t"],
    )

    provider.get_table()
    provider.get_table()
    assert calls["n"] == 1  # second call served from cache

    clock["t"] = 150.0  # past the TTL
    provider.get_table()
    assert calls["n"] == 2  # refreshed after expiry


def test_provider_falls_back_to_yaml_on_fetch_failure() -> None:
    def boom(url: str):
        raise OSError("network down")

    provider = PricingProvider(
        remote_url="https://example.test", fetcher=boom
    )
    table = provider.get_table()
    # Bundled YAML still serves a known model.
    assert table == load_pricing()
    assert "gpt-4o" in table


def test_provider_without_remote_url_serves_bundled_table() -> None:
    def fetcher(url: str):  # pragma: no cover - must never be called
        raise AssertionError("remote fetch must not run when remote_url is None")

    provider = PricingProvider(remote_url=None, fetcher=fetcher)
    assert "gpt-4o" in provider.get_table()


def test_provider_falls_back_when_remote_empty() -> None:
    provider = PricingProvider(
        remote_url="https://example.test", fetcher=lambda url: {}
    )
    assert provider.get_table() == load_pricing()
