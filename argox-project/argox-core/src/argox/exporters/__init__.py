"""Built-in OpenTelemetry SpanExporters distributed with argox-core."""

from .console import ConsoleSpanExporter
from .jsonl import JsonlSpanExporter

__all__ = ["ConsoleSpanExporter", "JsonlSpanExporter", "OTLPSpanExporter"]


def __getattr__(name: str) -> object:
    """Lazy-load optional OTLP exporter with helpful error message.

    Args:
        name: The attribute name being accessed.

    Returns:
        The requested exporter class if it can be imported.

    Raises:
        ImportError: If OTLPSpanExporter is requested but the optional
            dependency is not installed. Includes installation instructions.
    """
    if name == "OTLPSpanExporter":
        try:
            from .otlp import OTLPSpanExporter as _OTLPSpanExporter

            return _OTLPSpanExporter
        except ImportError as e:
            raise ImportError(
                "OTLPSpanExporter requires the optional dependency. "
                "Install it with: pip install argox-core[otlp]"
            ) from e
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
