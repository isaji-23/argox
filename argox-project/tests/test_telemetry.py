import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from argox.core.telemetry import init_telemetry


def test_init_telemetry_defaults():
    provider = init_telemetry()
    assert isinstance(provider, TracerProvider)
    
    # Check if global provider is set
    global_provider = trace.get_tracer_provider()
    assert isinstance(global_provider, TracerProvider)
    
    # Verify resource attributes
    attributes = provider.resource.attributes
    assert attributes["service.name"] == "argox-agent"
    assert attributes["service.version"] == "0.1.0"
    assert attributes["telemetry.sdk.name"] == "argox"


def test_init_telemetry_custom_attributes():
    provider = init_telemetry(
        service_name="custom-agent",
        service_version="1.2.3",
    )
    attributes = provider.resource.attributes
    assert attributes["service.name"] == "custom-agent"
    assert attributes["service.version"] == "1.2.3"


def test_init_telemetry_with_exporters():
    exporter = ConsoleSpanExporter()
    provider = init_telemetry(exporters=[exporter])
    
    # We should have one active span processor now (BatchSpanProcessor wrapping ConsoleSpanExporter)
    # The SDK internal structure may vary slightly, but we ensure it processes.
    assert len(provider._active_span_processor._span_processors) == 1
