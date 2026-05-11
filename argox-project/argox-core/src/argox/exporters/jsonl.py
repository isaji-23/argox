"""JsonlSpanExporter — serializes OpenTelemetry spans into a JSONL file."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class JsonlSpanExporter(SpanExporter):
    """OTel SpanExporter that writes spans as JSON lines to a file.

    Useful for development, debugging, and offline analysis.

    Args:
        file_path: The path to the output .jsonl file. The directory will be
            created if it does not exist.
    """

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans by appending them as JSON lines to the file."""
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                for span in spans:
                    f.write(span.to_json() + "\n")
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Called when the exporter is shut down."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush spans. Since we write directly to the file, return True."""
        return True
