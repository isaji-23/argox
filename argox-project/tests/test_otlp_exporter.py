"""Tests for the OTLPSpanExporter wrapper."""

from __future__ import annotations

from unittest import mock

from argox.observability import OTLPSpanExporter


def test_otlp_exporter_instantiation():
    """Test basic instantiation without raising."""
    exporter = OTLPSpanExporter()
    assert isinstance(exporter, OTLPSpanExporter)


def test_otlp_exporter_custom_endpoint():
    """Test that custom endpoint is passed through to upstream."""
    endpoint = "http://custom.endpoint:4318/v1/traces"
    exporter = OTLPSpanExporter(endpoint=endpoint)
    assert isinstance(exporter, OTLPSpanExporter)


def test_otlp_exporter_respects_otel_endpoint_env():
    """Test that OTEL_EXPORTER_OTLP_ENDPOINT env var is passed through."""
    with mock.patch.dict(
        "os.environ",
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://env.endpoint:4318"},
        clear=False,
    ):
        exporter = OTLPSpanExporter()
        assert isinstance(exporter, OTLPSpanExporter)


def test_otlp_exporter_respects_traces_endpoint_env():
    """Test that OTEL_EXPORTER_OTLP_TRACES_ENDPOINT env var is passed through."""
    with mock.patch.dict(
        "os.environ",
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://traces.endpoint:4318/v1/traces"},
        clear=False,
    ):
        exporter = OTLPSpanExporter()
        assert isinstance(exporter, OTLPSpanExporter)

