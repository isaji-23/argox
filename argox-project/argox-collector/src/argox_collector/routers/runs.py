"""Run-summary ingest endpoint (``POST /v1/runs``).

Route B of the content-ingest design: a parallel path to ``/v1/traces`` that
accepts full ``AgentRunMetrics`` records (prompt, final output, per-call token
breakdowns, tool records, policy violations). Traces stay lightweight and
operational; run summaries carry the content the dashboard, WORM audit log and
enrichment worker need, with their own storage layout and retention.

The endpoint validates synchronously, returns ``202 Accepted`` and delegates
the blob write plus the index insert to a background task, mirroring
``/v1/traces``. The opt-in ``X-Argox-Durable: true`` header makes persistence
synchronous and returns ``200 OK`` only once the records are committed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Union

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from argox_collector.auth import Scope, require_scope
from argox_collector.index import RunRecord, TraceIndex
from argox_collector.storage import StorageBackend

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["runs"])

_DURABLE_HEADER = "x-argox-durable"
_CONTENT_TYPE_JSON = "application/json"


class RunTokens(BaseModel):
    """Token totals carried by a run record.

    Extra keys (e.g. ``total`` or ``by_api_call``) are preserved on the blob
    but ignored by the index, which only promotes the input/output totals.
    """

    model_config = ConfigDict(extra="allow")

    input: int = 0
    output: int = 0


class RunRecordIn(BaseModel):
    """A single ``AgentRunMetrics``-shaped run record.

    Mirrors :meth:`argox.core.state.AgentRunMetrics.to_dict`. Only ``run_id``
    is required; everything else defaults so partial records still index. The
    Collector does not scrub content (PII redaction is the SDK's job) and
    preserves unknown fields on the immutable blob via ``extra="allow"``.

    ``trace_id`` is optional and top-level: the SDK exporter (EXP-09) sets it
    so the Query API can join a span back to its run. ``cost_usd`` is left
    unset at ingest and backfilled by the enrichment worker (#92).
    """

    model_config = ConfigDict(extra="allow")

    run_id: str
    trace_id: Optional[str] = None
    agent_name: str = ""
    agent_version: str = ""
    timestamp: Optional[str] = None
    success: bool = False
    duration_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    tokens: RunTokens = Field(default_factory=RunTokens)


# A submission is one record or a batch of them.
RunIngestBody = Union[RunRecordIn, list[RunRecordIn]]


def _blob_path(run_id: str, now: datetime) -> str:
    """Immutable blob key for a run record: ``runs/{YYYY-MM-DD}/{run_id}.json``."""
    return f"runs/{now:%Y-%m-%d}/{run_id}.json"


def _to_record(payload: RunRecordIn, blob_path: str) -> RunRecord:
    return RunRecord(
        run_id=payload.run_id,
        trace_id=payload.trace_id,
        agent_name=payload.agent_name or None,
        agent_version=payload.agent_version or None,
        timestamp=payload.timestamp,
        success=payload.success,
        total_input_tokens=payload.tokens.input,
        total_output_tokens=payload.tokens.output,
        duration_seconds=payload.duration_seconds,
        cost_usd=payload.cost_usd,
        blob_path=blob_path,
    )


def _persist(
    *,
    items: list[tuple[RunRecord, bytes]],
    storage: StorageBackend,
    index: TraceIndex,
) -> None:
    """Write each run blob and index its summary.

    Raises on any failure so the durable path can surface it. The background
    path wraps this in :func:`_persist_safe`, which logs and swallows because
    the client has already been acknowledged.
    """
    for record, blob in items:
        storage.put(
            record.blob_path,
            blob,
            content_type=_CONTENT_TYPE_JSON,
            metadata={"run_id": record.run_id},
        )
        index.insert_run(record)


def _persist_safe(**kwargs) -> None:
    """Background-task variant of :func:`_persist` that never raises."""
    try:
        _persist(**kwargs)
    except Exception:  # noqa: BLE001 - never let a background task crash the worker
        logger.exception(
            "run_ingest_persist_failed", run_count=len(kwargs["items"])
        )


def _build_items(
    body: RunIngestBody, raw_body: bytes, now: datetime
) -> list[tuple[RunRecord, bytes]]:
    """Pair each validated record with the exact bytes to store for it.

    A single-record submission stores the request body verbatim so the blob
    matches byte-for-byte. A batch re-serialises each element compactly, since
    the array bytes cannot be sliced back into per-record blobs.
    """
    if isinstance(body, list):
        elements = json.loads(raw_body)
        items: list[tuple[RunRecord, bytes]] = []
        for payload, element in zip(body, elements):
            blob = json.dumps(element, ensure_ascii=False).encode("utf-8")
            items.append((_to_record(payload, _blob_path(payload.run_id, now)), blob))
        return items
    return [(_to_record(body, _blob_path(body.run_id, now)), raw_body)]


@router.post(
    "/v1/runs",
    summary="Agent run-summary ingest",
    dependencies=[Depends(require_scope(Scope.INGEST))],
    response_class=Response,
    status_code=202,
    responses={
        202: {"description": "Run record(s) accepted for asynchronous persistence."},
        200: {
            "description": (
                "Run record(s) persisted synchronously (sent with "
                "X-Argox-Durable: true)."
            )
        },
        503: {"description": "Durable persistence failed; the batch was not committed."},
    },
)
async def ingest_runs(
    body: RunIngestBody, request: Request, background_tasks: BackgroundTasks
) -> Response:
    """Accept one or a batch of run records and persist them.

    Validates the payload synchronously, then either delegates persistence to
    a background task (``202``) or, when ``X-Argox-Durable: true`` is set, runs
    it in the threadpool and returns ``200`` only once committed.
    """
    raw_body = await request.body()
    now = datetime.now(timezone.utc)
    items = _build_items(body, raw_body, now)

    storage: StorageBackend = request.app.state.storage
    index: TraceIndex = request.app.state.index
    persist_kwargs = dict(items=items, storage=storage, index=index)

    durable = request.headers.get(_DURABLE_HEADER, "").strip().lower() == "true"
    if durable:
        # Blob writes are blocking I/O; run them off the event loop. Unlike the
        # background path, failures here MUST reach the client: the durable
        # contract is to return 200 only once the batch is committed.
        try:
            await run_in_threadpool(_persist, **persist_kwargs)
        except Exception:  # noqa: BLE001 - converted into a 503 for the client
            logger.exception(
                "run_ingest_durable_persist_failed", run_count=len(items)
            )
            return Response(
                content=json.dumps({"error": "failed to persist run records"}),
                media_type=_CONTENT_TYPE_JSON,
                status_code=503,
            )
        return Response(status_code=200)

    background_tasks.add_task(_persist_safe, **persist_kwargs)
    return Response(status_code=202)
