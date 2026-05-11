"""Built-in OpenTelemetry SpanExporters distributed with argox-core."""

from .console import ConsoleSpanExporter

__all__ = ["ConsoleSpanExporter"]
