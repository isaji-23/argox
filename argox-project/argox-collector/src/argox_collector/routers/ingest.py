"""
COL-03 — OTLP Traces Ingest Endpoint
====================================

Fast, fire-and-forget ingestion of OpenTelemetry traces.

The /v1/traces endpoint accepts OTLP JSON-formatted trace payloads and processes them
asynchronously in the background (fire-and-forget mode) by default. This ensures the
endpoint returns immediately without adding latency to the caller's agent.

Optional Durable Mode (x-argox-durable: true header):
    When this header is set, processing becomes synchronous and durable. The endpoint
    only returns after traces are persisted and indexed. This trades latency for
    durability guarantees.

Fire-and-Forget Mode (default):
    Returns 200 OK immediately. Processing (DuckDB indexing and blob storage)
    happens in background tasks. If a background task fails, the client never knows—
    the response has already been sent. This is the recommended mode for high-throughput
    agent integrations.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from pydantic import BaseModel, Field

from argox_collector.dependencies import get_storage
from argox_collector.storage.base import StorageBackend

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Pydantic Models (OTLP JSON Format)
# ============================================================================


class KeyValue(BaseModel):
    """
    A key-value pair for OTLP attributes.

    Attributes:
        key: The attribute name.
        value: The attribute value (can be string, number, bool, etc.).
    """

    key: str
    value: Any


class Span(BaseModel):
    """
    A single trace span from the OTLP payload.

    Attributes:
        traceId: Unique trace identifier (string representation of bytes).
        spanId: Unique span identifier (string representation of bytes).
        name: Human-readable span name (e.g., "LLM.call", "tool.execute").
        attributes: List of key-value pairs. Optional to preserve fidelity between
                    "omitted" and "empty" fields. OTLP spec always uses list format.
        startTimeUnixNano: Span start time in Unix nanoseconds (UTC).
        endTimeUnixNano: Span end time in Unix nanoseconds (UTC).
    """

    traceId: str
    spanId: str
    name: str
    attributes: list[KeyValue] | None = None
    startTimeUnixNano: int
    endTimeUnixNano: int


class ScopeSpans(BaseModel):
    """
    A group of spans for a specific instrumentation scope (e.g., library or component).

    Attributes:
        scope: Metadata about the instrumentation scope (e.g., name, version). Optional.
        spans: List of Span objects under this scope.
    """

    scope: dict[str, Any] | None = None
    spans: list[Span]


class ResourceSpans(BaseModel):
    """
    A group of spans for a specific resource (e.g., a single agent or service).

    Attributes:
        resource: Metadata about the resource (e.g., service.name, host.name, attributes). Optional.
        scopeSpans: List of ScopeSpans under this resource.
    """

    resource: dict[str, Any] | None = None
    scopeSpans: list[ScopeSpans]


class ExportTraceServiceRequest(BaseModel):
    """
    The full OTLP ExportTraceServiceRequest payload.

    This is the top-level structure of a trace export. Multiple resources can be
    included in a single request.

    Attributes:
        resourceSpans: List of ResourceSpans, one per resource being exported.
    """

    resourceSpans: list[ResourceSpans]


# ============================================================================
# Background Processing Functions
# ============================================================================


def _index_in_duckdb(payload: dict) -> None:
    """
    Index the trace payload into DuckDB for fast analytics queries.

    This is a placeholder for the actual DuckDB insertion logic.
    The real implementation will be in COL-04.

    Args:
        payload: The parsed OTLP payload as a dictionary.
        
    Note (COL-03 R2 Finding 2):
        Span attributes may be None when the field was omitted by the sender.
        When COL-04 implements real indexing, guard against None:
            attrs = span.get("attributes") or []
        This preserves the fix for COL-03 Finding 4 (data fidelity).
    """
    # TODO (COL-04): Insert into DuckDB
    # Remember: span["attributes"] may be None for spans without attributes field
    logger.debug("Placeholder: indexing spans into DuckDB (COL-04)")


def _persist_to_blob(raw_body: bytes, storage: StorageBackend, durable: bool = False) -> None:
    """
    Persist the raw trace payload to blob storage with time-partitioned path.

    Generates a dynamic blob path based on UTC time:
    spans/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.json

    This allows efficient querying by time range and easy garbage collection.

    Args:
        raw_body: The raw request body as bytes (preserves all OTLP fields).
        storage: The storage backend (e.g., S3, local filesystem, GCS).
        durable: If True, propagate exceptions (synchronous durable mode).
                 If False, log and swallow exceptions (background mode).

    Raises:
        Exception: Propagated only when durable=True. In durable mode,
                   storage failures cause the endpoint to return 5xx.
    """
    try:
        # Generate time-partitioned path with UTC timestamp
        now_utc = datetime.now(timezone.utc)
        path = (
            f"spans/"
            f"{now_utc.year:04d}/{now_utc.month:02d}/{now_utc.day:02d}/"
            f"{now_utc.hour:02d}/"
            f"{uuid4().hex}.json"
        )

        # Persist raw body as-is, preserving all OTLP fields
        storage.put(path, raw_body)

        logger.debug("Persisted trace batch to blob storage: %s", path)
    except Exception:
        if durable:
            # In durable mode, propagate the exception to the caller
            raise
        else:
            # In background/fire-and-forget mode, log and continue
            logger.exception(
                "Failed to persist trace batch to blob storage. "
                "Traces lost (DuckDB indexing not yet implemented)."
            )


def _process_spans(raw_body: bytes, payload_dict: dict, storage: StorageBackend, durable: bool = False) -> None:
    """
    Process a trace payload: index in DuckDB and persist to blob storage.

    This function orchestrates the trace processing pipeline. It is called
    either synchronously (durable mode) or as a background task (fire-and-forget).

    Args:
        raw_body: The raw request body as bytes (preserves all OTLP fields).
        payload_dict: The parsed OTLP payload as a dictionary (for indexing).
        storage: The storage backend.
        durable: If True, propagate exceptions (durable mode).
                 If False, log and continue (background mode).

    Raises:
        Exception: Propagated from _persist_to_blob only when durable=True.
    """
    _index_in_duckdb(payload_dict)
    _persist_to_blob(raw_body, storage, durable=durable)


# ============================================================================
# FastAPI Endpoint
# ============================================================================


@router.post("/v1/traces", status_code=200)
async def ingest_traces(
    request: Request,
    payload: ExportTraceServiceRequest,
    background_tasks: BackgroundTasks,
    x_argox_durable: str = Header(default="false"),
    storage: StorageBackend = Depends(get_storage),
) -> dict[str, Any]:
    """
    Ingest OTLP trace payloads from SDKs.

    This endpoint is designed for high-throughput, low-latency trace collection.
    By default, it operates in fire-and-forget mode: returns 200 OK immediately
    while processing happens in the background. This minimizes latency impact on
    the caller's agent.

    Durable Mode (x-argox-durable: true):
        When the x-argox-durable header is set to "true", the endpoint switches
        to synchronous processing. Traces are indexed and persisted before the
        response is returned. This provides durability guarantees at the cost of
        added latency (typically 100-500ms depending on storage backend).
        If storage fails, the endpoint returns 5xx instead of 200.

    Fire-and-Forget Mode (default, x-argox-durable: false or omitted):
        Returns 200 OK immediately. Background tasks are scheduled to index
        traces in DuckDB and persist them to blob storage. If a background task fails,
        the client never knows—the response has already been sent.
        This is the recommended mode for production agent integrations.

    The response follows OTLP/HTTP specification:
    https://opentelemetry.io/docs/specs/otlp/#otlphttp-response

    Args:
        request: The raw HTTP request (to preserve original OTLP payload).
        payload: The parsed OTLP ExportTraceServiceRequest (for validation only).
        background_tasks: FastAPI's background task scheduler.
        x_argox_durable: Optional header (default "false"). Set to "true" for
                         synchronous durable processing.
        storage: The storage backend (injected via dependency).

    Returns:
        An empty JSON object (standard OTLP/HTTP ExportTraceServiceResponse).

    Status Codes:
        - 200 OK: Traces accepted and processed (or queued in fire-and-forget mode).
        - 400 Bad Request: Invalid JSON or OTLP payload structure.
        - 5xx Server Error: Storage or indexing failure in durable mode.
    """
    # Preserve the raw request body to avoid data loss from Pydantic model_dump()
    raw_body = await request.body()
    
    # COL-03 R2 Finding 4: payload_dict is computed here but only used by _index_in_duckdb
    # which is currently a stub (TODO COL-04). Once COL-04 is implemented, this should be
    # moved inside _index_in_duckdb to avoid unnecessary allocations in the hot path.
    # For now we compute it eagerly and pass it through the pipeline.
    payload_dict = payload.model_dump()
    num_resources = len(payload_dict.get("resourceSpans", []))

    if x_argox_durable.lower() == "true":
        # Durable Mode: Process synchronously before returning.
        # Exceptions from storage/indexing will propagate as 5xx errors.
        logger.info(
            "Ingest /v1/traces (durable mode): processing %d resource(s) synchronously",
            num_resources,
        )
        _process_spans(raw_body, payload_dict, storage, durable=True)
    else:
        # Fire-and-Forget Mode: Return immediately, process in background.
        # Exceptions in background task are logged but not propagated.
        logger.info(
            "Ingest /v1/traces (fire-and-forget mode): queuing %d resource(s) for background processing",
            num_resources,
        )
        background_tasks.add_task(_process_spans, raw_body, payload_dict, storage, durable=False)

    # Return empty object per OTLP/HTTP spec (ExportTraceServiceResponse)
    # https://opentelemetry.io/docs/specs/otlp/#otlphttp-response
    return {}
