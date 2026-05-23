"""OpenTelemetry-specific span processors and exporters for Argox.

This namespace contains components that integrate directly with the
OpenTelemetry SDK to provide enhanced logging and observability.
"""

from argox.observability.jsonl import JsonlSpanExporter
from argox.observability.otlp import OTLPSpanExporter
from argox.observability.span_loggers import ConsoleSpanLogger

__all__ = [
    "ConsoleSpanLogger",
    "JsonlSpanExporter",
    "OTLPSpanExporter",
]
