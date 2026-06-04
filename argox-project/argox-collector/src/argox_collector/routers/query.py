from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from argox_collector.index.base import TraceIndex

router = APIRouter(prefix="/api/v1", tags=["query"])

def get_index(request: Request) -> TraceIndex:
    if not hasattr(request.app.state, "index") or request.app.state.index is None:
        raise HTTPException(status_code=503, detail="TraceIndex not initialized")
    return request.app.state.index


@router.get("/traces")
def list_traces(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    index: TraceIndex = Depends(get_index)
) -> dict:
    """List trace summaries for the dashboard."""
    traces = index.list_traces(skip=skip, limit=limit)
    return {
        "items": traces,
        "skip": skip,
        "limit": limit,
    }


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, index: TraceIndex = Depends(get_index)) -> dict:
    """Get full waterfall of spans for a trace."""
    spans = index.get_trace(trace_id=trace_id)
    if not spans:
        raise HTTPException(status_code=404, detail="Trace not found")
        
    return {
        "trace_id": trace_id,
        "spans": [
            {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "name": s.name,
                "start_time": s.start_time.isoformat() + "Z" if s.start_time else None,
                "end_time": s.end_time.isoformat() + "Z" if s.end_time else None,
                "duration_ms": s.duration_ms,
                "agent_name": s.agent_name,
                "agent_version": s.agent_version,
                "policy_decision": s.policy_decision,
                "run_cost": s.run_cost,
                "run_success": s.run_success,
                "attributes": s.attributes,
            }
            for s in spans
        ]
    }


@router.get("/metrics/cost")
def get_metrics_cost(
    window_hours: int = Query(24, ge=1, le=720),
    index: TraceIndex = Depends(get_index)
) -> dict:
    """Get aggregated cost metrics."""
    return index.get_metrics_cost(window_hours=window_hours)


@router.get("/metrics/latency")
def get_metrics_latency(
    window_hours: int = Query(24, ge=1, le=720),
    index: TraceIndex = Depends(get_index)
) -> dict:
    """Get aggregated latency metrics (avg and p95)."""
    return index.get_metrics_latency(window_hours=window_hours)


@router.get("/metrics/success")
def get_metrics_success(
    window_hours: int = Query(24, ge=1, le=720),
    index: TraceIndex = Depends(get_index)
) -> dict:
    """Get aggregated success rate metrics."""
    return index.get_metrics_success(window_hours=window_hours)
