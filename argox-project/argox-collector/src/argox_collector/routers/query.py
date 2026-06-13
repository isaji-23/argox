"""Read-only Query API for the dashboard (COL-06).

Exposes paginated trace lists, per-trace span detail and aggregated
cost/latency/success metrics on top of the relational index. Handlers are
plain ``def`` so FastAPI runs the blocking DuckDB queries in its threadpool,
mirroring the readyz and policy handlers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from argox_collector.auth import Scope, require_scope
from argox_collector.index import TraceIndex

router = APIRouter(
    prefix="/api/v1",
    tags=["query"],
    dependencies=[Depends(require_scope(Scope.READ))],
)

_MAX_PAGE_SIZE = 1000
# Trailing-window upper bound: 30 days.
_MAX_WINDOW_HOURS = 720


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


class CostMetricsResponse(BaseModel):
    """Aggregated cost over a trailing window."""

    window_hours: int
    total_cost: float
    trace_count: int


class LatencyMetricsResponse(BaseModel):
    """Aggregated root-span latency over a trailing window."""

    window_hours: int
    avg_latency_ms: float
    p95_latency_ms: float
    trace_count: int


class SuccessMetricsResponse(BaseModel):
    """Aggregated run success rate over a trailing window.

    ``success_rate`` is ``None`` when no runs reported an outcome inside the
    window, so an idle deployment is distinguishable from a failing one.
    """

    window_hours: int
    total_runs: int
    successful_runs: int
    success_rate: Optional[float] = None


def _index(request: Request) -> TraceIndex:
    return request.app.state.index


@router.get("/traces", response_model=TraceListResponse)
def list_traces(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> TraceListResponse:
    """List trace summaries, newest first."""
    summaries, total = _index(request).list_traces(skip=skip, limit=limit)
    return TraceListResponse(
        items=[TraceSummary(**summary) for summary in summaries],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
def get_trace(request: Request, trace_id: str) -> TraceDetailResponse:
    """Return the full span waterfall of one trace."""
    spans, truncated = _index(request).get_trace(trace_id)
    if not spans:
        raise HTTPException(status_code=404, detail="trace not found")
    return TraceDetailResponse(
        trace_id=trace_id,
        truncated=truncated,
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


@router.get("/metrics/cost", response_model=CostMetricsResponse)
def get_metrics_cost(
    request: Request,
    window_hours: int = Query(24, ge=1, le=_MAX_WINDOW_HOURS),
) -> CostMetricsResponse:
    """Total run cost (USD) over the trailing window."""
    return CostMetricsResponse(
        **_index(request).get_metrics_cost(window_hours=window_hours)
    )


@router.get("/metrics/latency", response_model=LatencyMetricsResponse)
def get_metrics_latency(
    request: Request,
    window_hours: int = Query(24, ge=1, le=_MAX_WINDOW_HOURS),
) -> LatencyMetricsResponse:
    """Average and p95 root-span latency over the trailing window."""
    return LatencyMetricsResponse(
        **_index(request).get_metrics_latency(window_hours=window_hours)
    )


@router.get("/metrics/success", response_model=SuccessMetricsResponse)
def get_metrics_success(
    request: Request,
    window_hours: int = Query(24, ge=1, le=_MAX_WINDOW_HOURS),
) -> SuccessMetricsResponse:
    """Run success rate over the trailing window."""
    return SuccessMetricsResponse(
        **_index(request).get_metrics_success(window_hours=window_hours)
    )
