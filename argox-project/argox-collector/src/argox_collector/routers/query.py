"""Read-only Query API for the dashboard (COL-06).

Exposes paginated trace lists, per-trace span detail and aggregated
cost/latency/success metrics on top of the relational index. Handlers are
plain ``def`` so FastAPI runs the blocking DuckDB queries in its threadpool,
mirroring the readyz and policy handlers.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from argox_collector.auth import Scope, require_scope
from argox_collector.index import ALLOWED_SORT_FIELDS, RunRecord, TraceIndex
from argox_collector.storage import (
    BlobNotFoundError,
    StorageBackend,
    StorageError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["query"],
    dependencies=[Depends(require_scope(Scope.READ))],
)

_MAX_PAGE_SIZE = 1000
# Trailing-window upper bound: 30 days.
_MAX_WINDOW_HOURS = 720
_SORT_PATTERN = f"^({'|'.join(sorted(ALLOWED_SORT_FIELDS))}):(asc|desc)$"


class TraceSummary(BaseModel):
    """Aggregated, per-trace row for the dashboard list view."""

    trace_id: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_duration_ms: Optional[float] = None
    total_cost: Optional[float] = None
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    span_count: int
    status: str
    decision: str


class TraceListResponse(BaseModel):
    """Paginated payload returned by ``GET /api/v1/traces``."""

    items: list[TraceSummary]
    total: int
    skip: int
    limit: int


class SpanDetail(BaseModel):
    """One span inside a trace waterfall."""

    span_id: str
    parent_span_id: Optional[str] = None
    name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    policy_decision: Optional[str] = None
    run_cost: Optional[float] = None
    run_success: Optional[bool] = None
    attributes: dict[str, Any] = {}


class TraceDetailResponse(BaseModel):
    """Full span waterfall returned by ``GET /api/v1/traces/{trace_id}``.

    ``truncated`` is True when the trace exceeded the index's per-trace span
    ceiling and ``spans`` was cut to keep the response bounded.
    """

    trace_id: str
    spans: list[SpanDetail]
    truncated: bool = False
    duration_ms: Optional[float] = None


class CostTimeSeriesPoint(BaseModel):
    bucket: datetime
    model: str
    cost: float


class AgentSpendPoint(BaseModel):
    agent_name: str
    spend: float


class CostMetricsResponse(BaseModel):
    """Aggregated cost over a trailing window."""

    window_hours: int
    total_cost: float
    trace_count: int
    timeline: list[CostTimeSeriesPoint]
    top_agents: list[AgentSpendPoint]


class LatencyHistogramBin(BaseModel):
    bin_min: float
    bin_max: float
    count: int


class LatencyPercentiles(BaseModel):
    p50: float
    p95: float
    p99: float


class LatencyMetricsResponse(BaseModel):
    """Aggregated root-span latency over a trailing window."""

    window_hours: int
    avg_latency_ms: float
    p95_latency_ms: float
    trace_count: int
    percentiles: LatencyPercentiles
    histogram: list[LatencyHistogramBin]


class SuccessTimeSeriesPoint(BaseModel):
    bucket: datetime
    total_runs: int
    successful_runs: int
    success_rate: Optional[float] = None


class BlockedToolPoint(BaseModel):
    tool_name: str
    blocked_count: int


class SuccessMetricsResponse(BaseModel):
    """Aggregated run success rate over a trailing window.

    ``success_rate`` is ``None`` when no runs reported an outcome inside the
    window, so an idle deployment is distinguishable from a failing one.
    """

    window_hours: int
    total_runs: int
    successful_runs: int
    success_rate: Optional[float] = None
    timeline: list[SuccessTimeSeriesPoint]
    top_blocked_tools: list[BlockedToolPoint]


class RunSummary(BaseModel):
    """Lightweight, per-run row for the dashboard list view (COL-13).

    The flat index projection only: ``prompt`` and ``final_output`` live on
    the blob and are deliberately excluded so a list response stays bounded
    regardless of run size. ``blob_path`` is an internal storage key and is
    not exposed.
    """

    run_id: str
    trace_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    timestamp: Optional[str] = None
    success: Optional[bool] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    duration_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    model: Optional[str] = None


class RunListResponse(BaseModel):
    """Paginated payload returned by ``GET /api/v1/runs``."""

    items: list[RunSummary]
    total: int
    page: int
    page_size: int


class RunDetail(BaseModel):
    """Full run record returned by the run-detail endpoints (COL-13).

    The promoted columns are typed for the generated client; the original
    ``AgentRunMetrics`` payload carries more (prompt, final output, per-tool
    detail, per-call tokens, policy violations), so ``extra="allow"`` keeps
    them on the response. The handler returns the stored blob bytes verbatim
    when present, falling back to this projection of the index row otherwise.
    """

    model_config = ConfigDict(extra="allow")

    run_id: str
    trace_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    timestamp: Optional[str] = None
    success: Optional[bool] = None
    duration_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    model: Optional[str] = None
    tokens: dict[str, Any] = {}


def _index(request: Request) -> TraceIndex:
    return request.app.state.index


def _storage(request: Request) -> StorageBackend:
    return request.app.state.storage


@router.get(
    "/traces", response_model=TraceListResponse, summary="List traces"
)
def list_traces(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
    trace_id: Optional[str] = Query(None, min_length=1),
    agent_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(ok|error)$"),
    decision: Optional[str] = Query(None, pattern="^(allow|block|warn)$"),
    sort: Optional[str] = Query(None, pattern=_SORT_PATTERN),
    window_hours: Optional[int] = Query(None, ge=1, le=_MAX_WINDOW_HOURS),
) -> TraceListResponse:
    """List trace summaries, newest first."""
    summaries, total = _index(request).list_traces(
        skip=skip,
        limit=limit,
        trace_id=trace_id,
        agent_name=agent_name,
        status=status,
        decision=decision,
        sort=sort,
        window_hours=window_hours,
    )
    return TraceListResponse(
        items=[TraceSummary(**summary) for summary in summaries],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/traces/{trace_id}",
    response_model=TraceDetailResponse,
    summary="Get trace detail",
)
def get_trace(request: Request, trace_id: str) -> TraceDetailResponse:
    """Return the full span waterfall of one trace."""
    spans, truncated, duration_ms = _index(request).get_trace(trace_id)
    if not spans:
        raise HTTPException(status_code=404, detail="trace not found")
    return TraceDetailResponse(
        trace_id=trace_id,
        truncated=truncated,
        duration_ms=duration_ms,
        spans=[
            SpanDetail(
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
                name=span.name,
                start_time=span.start_time,
                end_time=span.end_time,
                duration_ms=span.duration_ms,
                agent_name=span.agent_name,
                agent_version=span.agent_version,
                policy_decision=span.policy_decision,
                run_cost=span.run_cost,
                run_success=span.run_success,
                attributes=dict(span.attributes),
            )
            for span in spans
        ],
    )


@router.get(
    "/metrics/cost",
    response_model=CostMetricsResponse,
    summary="Cost metrics",
)
def get_metrics_cost(
    request: Request,
    window_hours: int = Query(24, ge=1, le=_MAX_WINDOW_HOURS),
) -> CostMetricsResponse:
    """Total run cost (USD) over the trailing window."""
    return CostMetricsResponse(
        **_index(request).get_metrics_cost(window_hours=window_hours)
    )


@router.get(
    "/metrics/latency",
    response_model=LatencyMetricsResponse,
    summary="Latency metrics",
)
def get_metrics_latency(
    request: Request,
    window_hours: int = Query(24, ge=1, le=_MAX_WINDOW_HOURS),
) -> LatencyMetricsResponse:
    """Average and p95 root-span latency over the trailing window."""
    return LatencyMetricsResponse(
        **_index(request).get_metrics_latency(window_hours=window_hours)
    )


@router.get(
    "/metrics/success",
    response_model=SuccessMetricsResponse,
    summary="Success rate metrics",
)
def get_metrics_success(
    request: Request,
    window_hours: int = Query(24, ge=1, le=_MAX_WINDOW_HOURS),
) -> SuccessMetricsResponse:
    """Run success rate over the trailing window."""
    return SuccessMetricsResponse(
        **_index(request).get_metrics_success(window_hours=window_hours)
    )


def _run_summary(record: RunRecord) -> RunSummary:
    return RunSummary(
        run_id=record.run_id,
        trace_id=record.trace_id,
        agent_name=record.agent_name,
        agent_version=record.agent_version,
        timestamp=record.timestamp,
        success=record.success,
        total_input_tokens=record.total_input_tokens,
        total_output_tokens=record.total_output_tokens,
        duration_seconds=record.duration_seconds,
        cost_usd=record.cost_usd,
        model=record.model,
    )


def _run_fallback_json(record: RunRecord) -> bytes:
    """Build a detail payload from the index row when the blob is unavailable.

    Mirrors the ``RunRecordIn`` ingest shape so a run whose blob was lost (or
    never written) still resolves to a usable record from the promoted
    columns, rather than a 404 that hides an indexed run.
    """
    payload = {
        "run_id": record.run_id,
        "trace_id": record.trace_id,
        "agent_name": record.agent_name,
        "agent_version": record.agent_version,
        "timestamp": record.timestamp,
        "success": record.success,
        "duration_seconds": record.duration_seconds,
        "cost_usd": record.cost_usd,
        "model": record.model,
        "tokens": {
            "input": record.total_input_tokens,
            "output": record.total_output_tokens,
        },
    }
    return json.dumps(payload).encode("utf-8")


# Stop a browser from MIME-sniffing a run blob (raw client content) into an
# executable type; the body is always served as application/json.
_DETAIL_HEADERS = {"X-Content-Type-Options": "nosniff"}


def _merge_run_blob(blob: bytes, record: RunRecord) -> Optional[bytes]:
    """Overlay collector-derived fields onto the immutable client blob.

    The blob is the client's original submission, which leaves ``cost_usd``
    unset at ingest; COL-17 backfills it into the index, not the blob. Returning
    the blob verbatim would therefore show a stale ``null`` cost in the detail
    view while the list view (read from the index) shows the backfilled value.
    The index ``cost_usd`` is overlaid so both agree.

    Returns ``None`` when the blob is not a JSON object (corrupt or hand-edited)
    so the caller can fall back to the index row rather than serving non-JSON
    bytes under an ``application/json`` content type.
    """
    try:
        payload = json.loads(blob)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["cost_usd"] = record.cost_usd
    return json.dumps(payload).encode("utf-8")


def _run_detail_response(storage: StorageBackend, record: RunRecord) -> Response:
    """Return the run's full record, blob first with the index row as fallback.

    The stored blob (the immutable JSON written at ingest by COL-11) carries the
    content the index omits — prompt, final output, per-call tokens, policy
    violations — but its ``cost_usd`` is overlaid from the index so the detail
    view never disagrees with the list view (see :func:`_merge_run_blob`). A
    missing, unreadable or non-JSON blob degrades to a projection of the index
    row rather than failing the request or serving corrupt bytes as JSON.
    """
    content: Optional[bytes] = None
    if record.blob_path:
        try:
            content = _merge_run_blob(storage.get(record.blob_path).data, record)
        except BlobNotFoundError:
            logger.info("run_blob_missing", run_id=record.run_id)
        except StorageError:
            logger.warning("run_blob_read_failed", run_id=record.run_id)
    if content is None:
        content = _run_fallback_json(record)
    return Response(
        content=content, media_type="application/json", headers=_DETAIL_HEADERS
    )


@router.get("/runs", response_model=RunListResponse, summary="List runs")
def list_runs(
    request: Request,
    agent: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> RunListResponse:
    """List run summaries, newest first, with optional filters.

    Rows are lightweight (no ``prompt``/``final_output``); ``from``/``to``
    bound the collector ingest time as a half-open ``[from, to)`` interval.
    """
    # An inverted range would silently return an empty page; reject it so the
    # caller learns the bounds are wrong rather than reading it as "no runs".
    if from_ is not None and to is not None and from_ > to:
        raise HTTPException(
            status_code=422, detail="'from' must not be after 'to'"
        )
    runs, total = _index(request).list_runs(
        skip=(page - 1) * page_size,
        limit=page_size,
        agent_name=agent,
        success=success,
        start=from_,
        end=to,
    )
    return RunListResponse(
        items=[_run_summary(run) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/runs/{run_id}",
    response_class=Response,
    summary="Get run detail",
    responses={200: {"model": RunDetail}, 404: {"description": "Run not found"}},
)
def get_run(request: Request, run_id: str) -> Response:
    """Return the full run record for ``run_id`` (byte-equivalent blob)."""
    record = _index(request).get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_detail_response(_storage(request), record)


@router.get(
    "/runs/by-trace/{trace_id}",
    response_class=Response,
    summary="Get run detail by trace id",
    responses={200: {"model": RunDetail}, 404: {"description": "Run not found"}},
)
def get_run_by_trace(request: Request, trace_id: str) -> Response:
    """Return the run record joined from a span's ``trace_id``.

    Returns 404 when no run was exported for the trace (the SDK's
    ``HttpRunExporter`` was not wired), so a span without a run is
    distinguishable from a missing trace.
    """
    record = _index(request).get_run_by_trace_id(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found for trace")
    return _run_detail_response(_storage(request), record)
