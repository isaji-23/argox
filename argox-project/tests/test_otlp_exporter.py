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


def test_otlp_exporter_api_key_sets_bearer_header():
    """A configured api_key is sent as an Authorization: Bearer header."""
    exporter = OTLPSpanExporter(
        endpoint="https://collector.example.com/v1/traces", api_key="argox_secret"
    )
    assert exporter._session.headers.get("Authorization") == "Bearer argox_secret"


def test_otlp_exporter_without_api_key_has_no_auth_header():
    """No api_key leaves the Authorization header unset."""
    exporter = OTLPSpanExporter(endpoint="https://collector.example.com/v1/traces")
    assert exporter._session.headers.get("Authorization") is None


def test_otlp_exporter_explicit_authorization_header_wins():
    """An explicit Authorization header takes precedence over api_key."""
    exporter = OTLPSpanExporter(
        endpoint="https://collector.example.com/v1/traces",
        api_key="argox_secret",
        headers={"Authorization": "Bearer explicit"},
    )
    assert exporter._session.headers.get("Authorization") == "Bearer explicit"


def test_otlp_exporter_lowercase_authorization_header_wins():
    """A lowercase 'authorization' header is honored; api_key does not double-set."""
    exporter = OTLPSpanExporter(
        endpoint="https://collector.example.com/v1/traces",
        api_key="argox_secret",
        headers={"authorization": "Bearer explicit"},
    )
    auth_headers = {
        k: v
        for k, v in exporter._session.headers.items()
        if k.lower() == "authorization"
    }
    assert list(auth_headers.values()) == ["Bearer explicit"]


def test_otlp_exporter_warns_on_api_key_over_plaintext():
    """A non-HTTPS endpoint with an api_key logs a plaintext warning."""
    with mock.patch("argox.observability.otlp.logger") as mock_logger:
        OTLPSpanExporter(
            endpoint="http://collector.example.com/v1/traces", api_key="argox_secret"
        )
    assert mock_logger.warning.called


def test_otlp_exporter_no_warning_on_https_endpoint():
    """An HTTPS endpoint with an api_key does not warn."""
    with mock.patch("argox.observability.otlp.logger") as mock_logger:
        OTLPSpanExporter(
            endpoint="https://collector.example.com/v1/traces", api_key="argox_secret"
        )
    assert not mock_logger.warning.called


def test_otlp_exporter_no_warning_on_loopback_http_endpoint():
    """A plain-HTTP loopback endpoint with an api_key does not warn (no leak)."""
    with mock.patch("argox.observability.otlp.logger") as mock_logger:
        OTLPSpanExporter(
            endpoint="http://localhost:4318/v1/traces", api_key="argox_secret"
        )
    assert not mock_logger.warning.called


def test_otlp_exporter_warning_uses_env_endpoint():
    """With no explicit endpoint, the warning resolves the OTEL env endpoint."""
    with mock.patch.dict(
        "os.environ",
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://env.endpoint:4318/v1/traces"},
        clear=False,
    ), mock.patch("argox.observability.otlp.logger") as mock_logger:
        OTLPSpanExporter(api_key="argox_secret")
    assert mock_logger.warning.called
    assert "env.endpoint" in mock_logger.warning.call_args.args[1]


def test_otlp_exporter_respects_traces_endpoint_env():
    """Test that OTEL_EXPORTER_OTLP_TRACES_ENDPOINT env var is passed through."""
    with mock.patch.dict(
        "os.environ",
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://traces.endpoint:4318/v1/traces"},
        clear=False,
    ):
        exporter = OTLPSpanExporter()
        assert isinstance(exporter, OTLPSpanExporter)

