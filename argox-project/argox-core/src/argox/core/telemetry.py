"""OpenTelemetry initialization and management for Argox."""

from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter


def _build_resource(service_name: str, service_version: str) -> Resource:
    return Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "telemetry.distro.name": "argox",
        }
    )


def init_telemetry(
    service_name: str = "argox-agent",
    service_version: str = "0.1.0",
    exporters: list[SpanExporter] | None = None,
) -> TracerProvider:
    """Initialize the OpenTelemetry TracerProvider with resource and processors.

    Args:
        service_name: The name of the service, defaults to 'argox-agent'.
        service_version: The version of the service.
        exporters: Optional list of OpenTelemetry SpanExporters to attach via BatchSpanProcessor.

    Returns:
        The configured TracerProvider.
    """
    resource = _build_resource(service_name, service_version)
    provider = TracerProvider(resource=resource)

    if exporters:
        for exporter in exporters:
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)
    return provider


def init_metrics(
    service_name: str = "argox-agent",
    service_version: str = "0.1.0",
    exporters: list[MetricExporter] | None = None,
    readers: list[MetricReader] | None = None,
    views: list[View] | None = None,
    export_interval_ms: int = 60000,
) -> MeterProvider:
    """Initialize the OpenTelemetry MeterProvider with resource, readers, and optional views.

    Two ways to attach data sinks (use whichever fits, both can be combined):

    - ``exporters``: each is auto-wrapped in a ``PeriodicExportingMetricReader``
      using ``export_interval_ms``. Use this for the common push-export case
      (Console, OTLP, etc.).
    - ``readers``: passed verbatim. Use this for raw readers such as
      ``InMemoryMetricReader`` in tests or a pull-based Prometheus reader.

    Args:
        service_name: The name of the service, defaults to 'argox-agent'.
        service_version: The version of the service.
        exporters: Optional list of OTel MetricExporters; each is wrapped in a
            PeriodicExportingMetricReader.
        readers: Optional list of pre-built MetricReaders attached as-is.
        views: Optional list of Views forwarded to the MeterProvider for
            custom histogram buckets, attribute filtering, etc.
        export_interval_ms: Periodic export interval applied to ``exporters``.

    Returns:
        The configured MeterProvider (also registered globally).
    """
    resource = _build_resource(service_name, service_version)

    metric_readers: list[MetricReader] = []
    if exporters:
        for exp in exporters:
            metric_readers.append(
                PeriodicExportingMetricReader(
                    exp, export_interval_millis=export_interval_ms
                )
            )
    if readers:
        metric_readers.extend(readers)

    provider = MeterProvider(
        resource=resource,
        metric_readers=metric_readers,
        views=views or (),
    )
    metrics.set_meter_provider(provider)
    return provider
