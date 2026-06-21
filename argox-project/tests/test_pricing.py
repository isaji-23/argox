"""Tests for the COL-17 pricing snapshot (remote fetch + YAML render + refresh CLI)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from argox_collector import __main__ as cli
from argox_collector.enrichment import pricing as pricing_mod
from argox_collector.enrichment.pricing import (
    fetch_remote_pricing,
    filter_pricing,
    load_pricing,
    render_pricing_yaml,
)

_LITELLM_PAYLOAD = {
    "gpt-4o": {
        "input_cost_per_token": 0.0000025,
        "output_cost_per_token": 0.00001,
    },
    "claude-opus-4": {
        "input_cost_per_token": 0.000015,
        "output_cost_per_token": 0.000075,
    },
    # No costs -> skipped rather than priced at zero.
    "sample_spec": {"max_tokens": 128000},
}


def _fake_urlopen(payload: dict):
    def _open(url, timeout):  # noqa: ANN001 - test stub
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return _open


def test_fetch_remote_pricing_normalises_per_token_to_per_1k(monkeypatch) -> None:
    monkeypatch.setattr(
        pricing_mod.urllib.request, "urlopen", _fake_urlopen(_LITELLM_PAYLOAD)
    )
    table = fetch_remote_pricing("https://example.test/prices.json")
    # Per-token prices scaled by 1,000 to USD per 1k tokens.
    assert table["gpt-4o"]["input"] == 0.0025
    assert table["gpt-4o"]["output"] == 0.01
    assert "sample_spec" not in table


def test_fetch_remote_pricing_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="non-HTTP"):
        fetch_remote_pricing("file:///etc/passwd")


def test_fetch_remote_pricing_rejects_oversized_payload(monkeypatch) -> None:
    big = b"x" * (pricing_mod._FETCH_MAX_BYTES + 10)

    def _open(url, timeout):  # noqa: ANN001 - test stub
        return io.BytesIO(big)

    monkeypatch.setattr(pricing_mod.urllib.request, "urlopen", _open)
    with pytest.raises(ValueError, match="exceeds"):
        fetch_remote_pricing("https://example.test/big.json")


def test_filter_pricing_keeps_only_matching_prefixes() -> None:
    table = {
        "gpt-4o": {"input": 1.0, "output": 2.0},
        "claude-opus-4": {"input": 3.0, "output": 4.0},
    }
    assert set(filter_pricing(table, ("gpt-",)).keys()) == {"gpt-4o"}
    assert filter_pricing(table, ()) == table  # empty prefixes -> unchanged


def test_render_pricing_yaml_round_trips_through_load(tmp_path: Path) -> None:
    table = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "claude-opus-4": {"input": 0.015, "output": 0.075},
    }
    out = tmp_path / "pricing.yaml"
    out.write_text(render_pricing_yaml(table), encoding="utf-8")
    assert load_pricing(out) == table


def test_render_pricing_yaml_is_deterministic() -> None:
    table = {
        "zeta": {"input": 1.0, "output": 2.0},
        "alpha": {"input": 3.0, "output": 4.0},
    }
    rendered = render_pricing_yaml(table)
    # Sorted by model name for a clean, reviewable diff.
    assert rendered.index("alpha") < rendered.index("zeta")
    assert render_pricing_yaml(table) == rendered


def test_refresh_pricing_cli_writes_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        pricing_mod.urllib.request, "urlopen", _fake_urlopen(_LITELLM_PAYLOAD)
    )
    out = tmp_path / "pricing.yaml"
    rc = cli.main(["refresh-pricing", "--out", str(out)])
    assert rc == 0
    table = load_pricing(out)
    assert table["gpt-4o"] == {"input": 0.0025, "output": 0.01}
    assert "sample_spec" not in table


def test_refresh_pricing_cli_provider_filter(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        pricing_mod.urllib.request, "urlopen", _fake_urlopen(_LITELLM_PAYLOAD)
    )
    out = tmp_path / "pricing.yaml"
    rc = cli.main(["refresh-pricing", "--out", str(out), "--provider", "gpt-"])
    assert rc == 0
    assert set(load_pricing(out).keys()) == {"gpt-4o"}


def test_refresh_pricing_cli_check_detects_drift(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        pricing_mod.urllib.request, "urlopen", _fake_urlopen(_LITELLM_PAYLOAD)
    )
    out = tmp_path / "pricing.yaml"
    # Missing file -> drift -> exit 1.
    assert cli.main(["refresh-pricing", "--out", str(out), "--check"]) == 1
    # Write it, then --check passes.
    assert cli.main(["refresh-pricing", "--out", str(out)]) == 0
    assert cli.main(["refresh-pricing", "--out", str(out), "--check"]) == 0


def test_refresh_pricing_cli_fetch_failure_returns_1(monkeypatch, tmp_path: Path) -> None:
    def boom(url, timeout):  # noqa: ANN001 - test stub
        raise OSError("network down")

    monkeypatch.setattr(pricing_mod.urllib.request, "urlopen", boom)
    out = tmp_path / "pricing.yaml"
    assert cli.main(["refresh-pricing", "--out", str(out)]) == 1
    assert not out.exists()
