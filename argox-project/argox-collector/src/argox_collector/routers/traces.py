"""OTLP/HTTP trace ingest endpoint (``POST /v1/traces``)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceResponse,
)

from argox_collector.auth import Scope, require_scope
from argox_collector.enrichment import enrich
from argox_collector.index import TraceIndex
from argox_collector.index.base import SpanRecord
from argox_collector.ingest import (
    OtlpDecodeError,
    decode_request,
    request_to_span_records,
)
from argox_collector.ingest.otlp import CONTENT_TYPE_JSON, CONTENT_TYPE_PROTOBUF
from argox_collector.settings import CollectorSettings
from argox_collector.storage import StorageBackend

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["traces"])

_SUPPORTED_CONTENT_TYPES = {CONTENT_TYPE_PROTOBUF, CONTENT_TYPE_JSON}
_DURABLE_HEADER = "x-argox-durable"


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _success_response(media_type: str, status_code: int) -> Response:
    """Serialise an empty ``ExportTraceServiceResponse`` (full success)."""
    message = ExportTraceServiceResponse()
    if media_type == CONTENT_TYPE_JSON:
        body = json_format.MessageToJson(message).encode("utf-8")
        return Response(
            content=body, media_type=CONTENT_TYPE_JSON, status_code=status_code
        )
    body = message.SerializeToString()
    return Response(
        content=body, media_type=CONTENT_TYPE_PROTOBUF, status_code=status_code
    )


def _error_response(message: str, status_code: int) -> Response:
    """Return a JSON error body, safely encoded regardless of ``message``."""
    return Response(
        content=json.dumps({"error": message}),
        media_type=CONTENT_TYPE_JSON,
        status_code=status_code,
    )


def _persist(
    *,
    body: bytes,
    content_type: str,
    records: list[SpanRecord],
    storage: StorageBackend,
    index: TraceIndex,
    settings: CollectorSettings,
) -> None:
    """Enrich, store the raw batch, and index the spans.

    Raises on any failure so the durable path can surface it to the client.
    The background path wraps this in :func:`_persist_safe`, which logs and
    swallows because the client has already been acknowledged.
    """
    enriched = enrich(records, settings)
    now = datetime.now(timezone.utc)
    key = f"traces/{now:%Y-%m-%d}/{uuid.uuid4().hex}.pb"
    storage.put(
        key,
        body,
        content_type=content_type,
        metadata={"span_count": str(len(records))},
    )
    index.insert_spans(enriched)


def _persist_safe(**kwargs) -> None:
    """Background-task variant of :func:`_persist` that never raises.

    The client received its ``202`` before this runs, so a persistence failure
    can only be logged — there is no longer a response to fail.
    """
    try:
        _persist(**kwargs)
    except Exception:  # noqa: BLE001 - never let a background task crash the worker
        logger.exception(
            "trace_ingest_persist_failed", span_count=len(kwargs["records"])
        )


@router.post(
    "/v1/traces",
    summary="OTLP/HTTP trace ingest",
    dependencies=[Depends(require_scope(Scope.INGEST))],
)
async def ingest_traces(
    request: Request, background_tasks: BackgroundTasks
) -> Response:
    """Accept an OTLP ``ExportTraceServiceRequest`` and persist its spans.

    Validates the batch synchronously, then delegates the blob write and index
    insert to a background task and returns ``202 Accepted``. When the request
    carries ``X-Argox-Durable: true`` the persistence runs synchronously and the
    endpoint returns ``200 OK`` only once the data is committed.
    """
    raw_content_type = request.headers.get("content-type", "")
    media_type = _media_type(raw_content_type)
    if media_type not in _SUPPORTED_CONTENT_TYPES:
        return _error_response(
            f"unsupported content type: {media_type!r}", status_code=415
        )

    body = await request.body()
    try:
        otlp_request = decode_request(body, raw_content_type)
    except OtlpDecodeError as exc:
        return _error_response(str(exc), status_code=400)

    records = request_to_span_records(otlp_request)

    settings: CollectorSettings = request.app.state.settings
    storage: StorageBackend = request.app.state.storage
    index: TraceIndex = request.app.state.index

    durable = request.headers.get(_DURABLE_HEADER, "").strip().lower() == "true"
    persist_kwargs = dict(
        body=body,
        content_type=media_type,
        records=records,
        storage=storage,
        index=index,
        settings=settings,
    )

    if durable:
        # _persist performs blocking disk/network I/O (notably the Azure blob
        # upload). Run it in the threadpool so the durable path does not stall
        # the event loop, mirroring the synchronous readyz handler. Unlike the
        # background path, failures here MUST reach the client: the durable
        # contract is to return 200 only once the batch is committed.
        try:
            await run_in_threadpool(_persist, **persist_kwargs)
        except Exception:  # noqa: BLE001 - converted into a 503 for the client
            logger.exception(
                "trace_ingest_durable_persist_failed", span_count=len(records)
            )
            return _error_response(
                "failed to persist trace batch", status_code=503
            )
        return _success_response(media_type, status_code=200)

    background_tasks.add_task(_persist_safe, **persist_kwargs)
    return _success_response(media_type, status_code=202)
