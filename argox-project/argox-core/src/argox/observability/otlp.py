"""OTLP SpanExporter — sends spans to Argox Collector via HTTP/protobuf."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as _OTLPSpanExporter,
)

from argox.net import is_plaintext_credential_endpoint

logger = logging.getLogger(__name__)

# Upstream default when neither an explicit endpoint nor an OTEL env var is set.
_DEFAULT_ENDPOINT = "http://localhost:4318/v1/traces"


class OTLPSpanExporter(_OTLPSpanExporter):
    """Standard OpenTelemetry OTLP Exporter configured for the Argox Collector.

    This is a thin re-export of the official OTLPSpanExporter from OpenTelemetry.
    It sends spans via HTTP/protobuf and respects standard OpenTelemetry environment
    variables (e.g., OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_TRACES_ENDPOINT).

    By default (with no endpoint provided and no env vars set), the upstream exporter
    targets http://localhost:4318/v1/traces, which is the standard Argox Collector
    port.

    Args:
        api_key: Optional Bearer token for the Collector's ``/v1/traces`` ingest
            endpoint, which enforces the ``ingest`` scope when auth is enabled.
            When set, it is injected as ``Authorization: Bearer <api_key>`` into
            the ``headers`` kwarg, mirroring ``HttpRunExporter`` and
            ``RemotePolicyClient``. Because the upstream exporter gives the
            ``headers`` kwarg precedence over ``OTEL_EXPORTER_OTLP_HEADERS``,
            ``api_key`` overrides any ``Authorization`` set through that
            environment variable. An ``Authorization`` header passed explicitly
            via ``headers`` (in any capitalization) still wins over ``api_key``.
        **kwargs: All remaining arguments are forwarded to the upstream
            OTLPSpanExporter. See OpenTelemetry documentation for full details.

    Example:
        >>> exporter = OTLPSpanExporter(
        ...     endpoint="https://collector.internal:4318/v1/traces",
        ...     api_key="argox_…",
        ... )
        >>> init_telemetry(exporters=[exporter])
    """

    def __init__(self, *, api_key: Optional[str] = None, **kwargs: Any) -> None:
        if api_key:
            headers = kwargs.get("headers")
            merged: dict[str, str] = dict(headers) if headers else {}
            # An explicit Authorization header wins; api_key only fills the gap.
            # Header names are case-insensitive on the wire, so match any
            # capitalization the caller may have used rather than just the
            # canonical "Authorization".
            if not any(name.lower() == "authorization" for name in merged):
                merged["Authorization"] = f"Bearer {api_key}"
            kwargs["headers"] = merged

            endpoint = kwargs.get("endpoint") or _resolve_endpoint_from_env()
            if is_plaintext_credential_endpoint(endpoint):
                logger.warning(
                    "OTLPSpanExporter: API key is provided but the endpoint (%s) "
                    "does not use HTTPS. The key will travel in plaintext over "
                    "the network.",
                    endpoint,
                )

        super().__init__(**kwargs)


def _resolve_endpoint_from_env() -> str:
    """Best-effort resolution of the effective endpoint for the HTTPS warning.

    Mirrors the precedence the upstream exporter applies when no ``endpoint``
    argument is passed: the traces-specific env var wins over the generic one,
    falling back to the upstream localhost default.
    """
    return (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or _DEFAULT_ENDPOINT
    )
