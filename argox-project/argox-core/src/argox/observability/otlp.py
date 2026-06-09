"""OTLP SpanExporter — sends spans to Argox Collector via HTTP/protobuf."""

from __future__ import annotations

from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as _OTLPSpanExporter,
)


class OTLPSpanExporter(_OTLPSpanExporter):
    """Standard OpenTelemetry OTLP Exporter configured for the Argox Collector.

    This is a thin re-export of the official OTLPSpanExporter from OpenTelemetry.
    It sends spans via HTTP/protobuf and respects standard OpenTelemetry environment
    variables (e.g., OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_TRACES_ENDPOINT).

    By default (with no endpoint provided and no env vars set), the upstream exporter
    targets http://localhost:4318/v1/traces, which is the standard Argox Collector
    port.

    Args:
        **kwargs: All arguments are forwarded to the upstream OTLPSpanExporter.
            See OpenTelemetry documentation for full parameter details.

    Example:
        >>> exporter = OTLPSpanExporter(
        ...     endpoint="http://collector.internal:4318/v1/traces"
        ... )
        >>> init_telemetry(exporters=[exporter])
    """
