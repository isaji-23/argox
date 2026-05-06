"""OpenTelemetry initialization and management for Argox."""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter


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
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "telemetry.sdk.name": "argox",
        }
    )

    provider = TracerProvider(resource=resource)

    if exporters:
        for exporter in exporters:
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)

    # Set the global tracer provider
    trace.set_tracer_provider(provider)

    return provider
