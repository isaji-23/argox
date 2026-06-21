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

import dataclasses
import json
import re
from datetime import datetime, timezone
from typing import Optional, Union

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from argox_collector.auth import Scope, require_scope
from argox_collector.enrichment.cost import enrich_run_cost
from argox_collector.enrichment.pricing import PricingTable, cached_pricing
from argox_collector.index import RunRecord, TraceIndex
from argox_collector.storage import ConditionNotMetError, StorageBackend

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["runs"])

_DURABLE_HEADER = "x-argox-durable"
_CONTENT_TYPE_JSON = "application/json"

# Upper bound on records per submission. The global payload-size middleware
# already caps the request body; this caps the element count so a single
# request cannot fan out into an unbounded number of blob writes.
_MAX_BATCH_RECORDS = 1000

# run_id becomes a blob-path segment (runs/{date}/{run_id}.json), so it must be
# a single safe filename component: no slashes, no traversal, no control
# characters. Validated at the API boundary so a malformed id is rejected
# synchronously (before the 202) rather than failing silently in a background
# blob write.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


class RunTokens(BaseModel):
    """Token totals carried by a run record.

    Extra keys (e.g. ``total`` or ``by_api_call``) are preserved on the blob
    but ignored by the index, which only promotes the input/output totals.
    """

    model_config = ConfigDict(extra="allow")

    input: int = Field(default=0, ge=0)
    output: int = Field(default=0, ge=0)


class RunRecordIn(BaseModel):
    """A single ``AgentRunMetrics``-shaped run record.

    Mirrors :meth:`argox.core.state.AgentRunMetrics.to_dict`. Only ``run_id``
    is required; everything else defaults so partial records still index. The
    Collector does not scrub content (PII redaction is the SDK's job) and
    preserves unknown fields on the immutable blob via ``extra="allow"``.

    ``trace_id`` is optional and top-level: the SDK exporter (EXP-09) sets it
    so the Query API can join a span back to its run. ``cost_usd`` is left
    unset at ingest and backfilled from ``model`` and the token totals
    (COL-17).
    """

    model_config = ConfigDict(extra="allow")

    run_id: str
    trace_id: Optional[str] = None
    agent_name: str = ""
    agent_version: str = ""
    timestamp: Optional[str] = None
    # Optional tri-state: a record that omits success is left unknown (None)
    # rather than indexed as a failed run, which would skew success metrics.
    success: Optional[bool] = None
    duration_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    # Model the run used; keyed against the price table to backfill cost_usd
    # (COL-17). Left None when the client does not report one.
    model: Optional[str] = None
    tokens: RunTokens = Field(default_factory=RunTokens)

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        if not _RUN_ID_RE.fullmatch(value):
            raise ValueError(
                "run_id must be 1-200 chars of [A-Za-z0-9._-] (it is used as a "
                "blob-path segment)"
            )
        if value in {".", ".."}:
            raise ValueError("run_id must not be a path-traversal segment")
        return value


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
        model=payload.model or None,
    )


def _persist(
    *,
    items: list[tuple[RunRecord, bytes]],
    storage: StorageBackend,
    index: TraceIndex,
    pricing: Optional[PricingTable] = None,
) -> None:
    """Write each run blob, index its summary, and backfill its cost.

    Raises on any failure so the durable path can surface it. The background
    path wraps this in :func:`_persist_safe`, which logs and swallows because
    the client has already been acknowledged.

    The blob is written create-only (``expected_etag="*"``) so an existing run
    blob is never overwritten — the record is immutable. A re-ingest therefore
    keeps the original blob; the index insert still runs so a row missing from
    a partially-failed earlier attempt is recovered (``insert_run`` is itself
    first-write-wins on ``run_id``).

    The cost is priced and written via the separate ``set_run_cost`` UPDATE
    (COL-17). The model is taken from the run record, falling back to the model
    its spans carry (joined by ``trace_id``, set by PLUGIN-05), priced against
    the bundled snapshot price table. A pricing failure must not lose the
    already-persisted run, so it is logged and swallowed independently of the
    blob/index writes above.
    """
    for record, blob in items:
        try:
            storage.put(
                record.blob_path,
                blob,
                content_type=_CONTENT_TYPE_JSON,
                metadata={"run_id": record.run_id},
                expected_etag="*",
            )
        except ConditionNotMetError:
            logger.info("run_blob_exists", run_id=record.run_id)
        index.insert_run(record)
        _backfill_cost(record, index, pricing)


def _backfill_cost(
    record: RunRecord, index: TraceIndex, pricing: Optional[PricingTable]
) -> None:
    """Price a run's cost and write it (COL-17), never raising.

    Resolves the model from the run record first, then from its spans via
    ``trace_id`` (PLUGIN-05). A client-supplied ``cost_usd`` is left as-is.
    """
    if pricing is None or record.cost_usd is not None:
        return
    try:
        model = record.model or _model_from_trace(record, index)
        if not model:
            return
        priced = record if record.model else dataclasses.replace(record, model=model)
        cost = enrich_run_cost(priced, pricing)
        if cost is not None:
            index.set_run_cost(record.run_id, cost)
    except Exception:  # noqa: BLE001 - cost is best-effort; the run is already stored
        logger.exception("run_cost_backfill_failed", run_id=record.run_id)


def _model_from_trace(record: RunRecord, index: TraceIndex) -> Optional[str]:
    """Recover the run's model from its spans, or ``None`` (no trace, no span)."""
    if not record.trace_id:
        return None
    return index.get_run_model_from_trace(record.trace_id)


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
        seen: set[str] = set()
        for payload, element in zip(body, elements):
            # Duplicate run_ids in one batch share a blob path; keep the first
            # so the second cannot silently overwrite it (create-only would
            # reject it anyway, but skipping avoids the wasted write).
            if payload.run_id in seen:
                continue
            seen.add(payload.run_id)
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
    if isinstance(body, list) and len(body) > _MAX_BATCH_RECORDS:
        return Response(
            content=json.dumps(
                {"error": f"batch exceeds {_MAX_BATCH_RECORDS} records"}
            ),
            media_type=_CONTENT_TYPE_JSON,
            status_code=413,
        )

    raw_body = await request.body()
    now = datetime.now(timezone.utc)
    items = _build_items(body, raw_body, now)

    storage: StorageBackend = request.app.state.storage
    index: TraceIndex = request.app.state.index
    pricing = cached_pricing(request.app.state.settings.pricing_table_path)
    persist_kwargs = dict(
        items=items, storage=storage, index=index, pricing=pricing
    )

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
