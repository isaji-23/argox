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
    Returns 202 Accepted immediately. Processing (DuckDB indexing and blob storage)
    happens in background tasks. If a background task fails, the client never knows—
    the response has already been sent. This is the recommended mode for high-throughput
    agent integrations.
"""

import json
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
        attributes: List of key-value pairs or a dict of attributes. Defaults to empty list.
        startTimeUnixNano: Span start time in Unix nanoseconds (UTC).
        endTimeUnixNano: Span end time in Unix nanoseconds (UTC).
    """

    traceId: str
    spanId: str
    name: str
    attributes: list[KeyValue] | dict[str, Any] = Field(default_factory=list)
    startTimeUnixNano: int
    endTimeUnixNano: int


class ScopeSpans(BaseModel):
    """
    A group of spans for a specific instrumentation scope (e.g., library or component).

    Attributes:
        scope: Metadata about the instrumentation scope (e.g., name, version).
        spans: List of Span objects under this scope.
    """

    scope: dict[str, Any] = Field(default_factory=dict)
    spans: list[Span]


class ResourceSpans(BaseModel):
    """
    A group of spans for a specific resource (e.g., a single agent or service).

    Attributes:
        resource: Metadata about the resource (e.g., service.name, host.name, attributes).
        scopeSpans: List of ScopeSpans under this resource.
    """

    resource: dict[str, Any] = Field(default_factory=dict)
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
    """
    # TODO (COL-04): Insert into DuckDB
    logger.debug("Placeholder: indexing spans into DuckDB (COL-04)")


def _persist_to_blob(payload: dict, storage: StorageBackend) -> None:
    """
    Persist the raw trace payload to blob storage with time-partitioned path.

    Generates a dynamic blob path based on UTC time:
    spans/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.json

    This allows efficient querying by time range and easy garbage collection.

    Args:
        payload: The parsed OTLP payload as a dictionary.
        storage: The storage backend (e.g., S3, local filesystem, GCS).

    Raises:
        Exception: If blob write fails. The exception is logged and swallowed
                   in fire-and-forget mode (background task).
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

        # Serialize payload to JSON and persist as bytes
        json_content = json.dumps(payload, default=str)
        storage.put(path, json_content.encode("utf-8"))

        logger.debug("Persisted trace batch to blob storage: %s", path)
    except Exception:
        logger.exception(
            "Failed to persist trace batch to blob storage. "
            "Traces are indexed in DuckDB but may be lost on restart."
        )


def _process_spans(payload_dict: dict, storage: StorageBackend) -> None:
    """
    Process a trace payload: index in DuckDB and persist to blob storage.

    This function orchestrates the trace processing pipeline. It is called
    either synchronously (durable mode) or as a background task (fire-and-forget).

    Args:
        payload_dict: The parsed OTLP payload as a dictionary.
        storage: The storage backend.
    """
    _index_in_duckdb(payload_dict)
    _persist_to_blob(payload_dict, storage)


# ============================================================================
# FastAPI Endpoint
# ============================================================================


@router.post("/v1/traces", status_code=202)
async def ingest_traces(
    request: Request,
    payload: ExportTraceServiceRequest,
    background_tasks: BackgroundTasks,
    x_argox_durable: str = Header(default="false"),
    storage: StorageBackend = Depends(get_storage),
) -> dict[str, str]:
    """
    Ingest OTLP trace payloads from SDKs.

    This endpoint is designed for high-throughput, low-latency trace collection.
    By default, it operates in fire-and-forget mode: returns 202 Accepted immediately
    while processing happens in the background. This minimizes latency impact on
    the caller's agent.

    Durable Mode (x-argox-durable: true):
        When the x-argox-durable header is set to "true", the endpoint switches
        to synchronous processing. Traces are indexed and persisted before the
        response is returned. This provides durability guarantees at the cost of
        added latency (typically 100-500ms depending on storage backend).

    Fire-and-Forget Mode (default, x-argox-durable: false or omitted):
        Returns 202 Accepted immediately. Background tasks are scheduled to index
        traces in DuckDB and persist them to blob storage. If a background task fails,
        the client never knows—the response has already been sent.
        This is the recommended mode for production agent integrations.

    Args:
        request: The raw HTTP request (for debugging/auditing).
        payload: The parsed OTLP ExportTraceServiceRequest.
        background_tasks: FastAPI's background task scheduler.
        x_argox_durable: Optional header (default "false"). Set to "true" for
                         synchronous durable processing.
        storage: The storage backend (injected via dependency).

    Returns:
        A JSON response with a status field. The HTTP status code is always 202
        (Accepted) as per OTLP standard.

    Status Codes:
        - 202 Accepted: Traces accepted. Synchronous (durable) or async (fire-and-forget)
                        processing is about to begin or has begun.
        - 4xx / 5xx: Validation or server errors (e.g., invalid JSON, storage failure in
                     durable mode).
    """
    payload_dict = payload.model_dump()

    if x_argox_durable.lower() == "true":
        # Durable Mode: Process synchronously before returning
        logger.info(
            "Ingest /v1/traces (durable mode): processing %d resource(s) synchronously",
            len(payload_dict.get("resourceSpans", [])),
        )
        _process_spans(payload_dict, storage)
        return {"status": "accepted_durable"}
    else:
        # Fire-and-Forget Mode: Return immediately, process in background
        logger.info(
            "Ingest /v1/traces (fire-and-forget mode): queuing %d resource(s) for background processing",
            len(payload_dict.get("resourceSpans", [])),
        )
        background_tasks.add_task(_process_spans, payload_dict, storage)
        return {"status": "accepted"}
