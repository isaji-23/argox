"""JsonlSpanExporter — serializes OpenTelemetry spans into a JSONL file."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)


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
        # We keep the file handle open for performance (avoid syscalls per export).
        # newline="" prevents extra \r in Windows and lets Python handle line endings.
        self._fh = open(self.file_path, "a", encoding="utf-8", newline="")

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans by appending them as JSON lines to the file."""
        if self._fh.closed:
            return SpanExportResult.FAILURE

        try:
            for span in spans:
                # indent=None ensures the JSON is written as a single line (JSONL format).
                self._fh.write(span.to_json(indent=None) + "\n")
            return SpanExportResult.SUCCESS
        except Exception:
            logger.exception("Failed to export spans to %s", self.file_path)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Close the file handle when the exporter is shut down."""
        self._fh.close()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Ensure all buffered spans are written to disk."""
        if not self._fh.closed:
            self._fh.flush()
        return True
