"""AzureBlobSpanExporter — writes spans to Azure Blob Storage."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)


class AzureBlobSpanExporter(SpanExporter):
    """OTel SpanExporter that writes batches of spans to Azure Blob Storage.

    Each export call creates a new JSONL blob in the container, following the path:
    `spans/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.jsonl`
    """

    def __init__(
        self,
        connection_string: str,
        container_name: str,
        prefix: str = "spans",
    ) -> None:
        self._container_name = container_name
        self._prefix = prefix
        self._healthy = False
        try:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
            self._healthy = True
        except ValueError as e:
            logger.exception("Invalid connection string for AzureBlobSpanExporter: %s", e)
            raise

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans to Azure Blob Storage as a single JSONL blob."""
        if not self._healthy:
            return SpanExportResult.FAILURE

        if not spans:
            return SpanExportResult.SUCCESS

        try:
            # Serialize spans to JSONL
            lines = [span.to_json(indent=None) for span in spans]
            jsonl_data = "\n".join(lines) + "\n"

            # Generate blob name based on current UTC time
            now = datetime.now(timezone.utc)
            batch_id = uuid.uuid4().hex
            blob_name = (
                f"{self._prefix}/"
                f"{now.year:04d}/{now.month:02d}/{now.day:02d}/{now.hour:02d}/"
                f"{batch_id}.jsonl"
            )

            # Upload to Azure
            blob_client = self._blob_service_client.get_blob_client(
                container=self._container_name, blob=blob_name
            )
            blob_client.upload_blob(jsonl_data.encode("utf-8"))

            return SpanExportResult.SUCCESS

        except AzureError as e:
            logger.exception("Azure error exporting spans to blob storage: %s", e)
            return SpanExportResult.FAILURE
        except Exception as e:
            logger.exception("Unexpected error exporting spans to blob storage: %s", e)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Clean up resources."""
        if self._healthy and self._blob_service_client:
            self._blob_service_client.close()
            self._healthy = False

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Nothing to flush, blobs are uploaded synchronously."""
        return True

