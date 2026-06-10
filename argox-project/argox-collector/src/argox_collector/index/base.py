"""Abstract :class:`TraceIndex` interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class SpanRecord:
    """Relational record representing a single span's metadata.

    This matches the flattened schema stored in the index (DuckDB).
    """
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    
    # Argox-specific promotions
    agent_name: Optional[str] = None
    agent_version: Optional[str] = None
    policy_decision: Optional[str] = None
    run_cost: Optional[float] = None
    run_success: Optional[bool] = None
    
    # Catch-all for other attributes
    attributes: Mapping[str, Any] = field(default_factory=dict)

    # Span events decoded from OTLP (name, timestamp, attributes). Not stored
    # in the index — the raw blob already preserves them — but carried so
    # ingest-time enrichment (residual PII scan) can inspect event payloads.
    events: tuple[Mapping[str, Any], ...] = ()


class TraceIndexError(RuntimeError):
    """Base class for index backend failures."""


class TraceIndex(ABC):
    """Abstract interface for the Collector's relational index.
    
    The index stores metadata about traces and spans to allow efficient
    filtering and aggregation. Unlike the StorageBackend, which holds the 
    full raw spans, the Index holds a flattened, queryable subset.
    """

    @abstractmethod
    def insert_span(self, record: SpanRecord) -> None:
        """Add a single span record to the index."""

    @abstractmethod
    def insert_spans(self, records: list[SpanRecord]) -> None:
        """Batch add multiple span records to the index."""

    @abstractmethod
    def list_traces(self, *, skip: int = 0, limit: int = 50) -> tuple[list[dict], int]:
        """Return paginated trace summaries plus the total trace count.

        Each summary aggregates the spans sharing a ``trace_id`` (start/end
        time, total cost, span count, root agent). Summaries are sorted by
        trace start time, newest first.

        Returns:
            A ``(summaries, total)`` tuple where ``total`` is the number of
            distinct traces in the index regardless of pagination.
        """

    @abstractmethod
    def get_trace(self, trace_id: str) -> tuple[list[SpanRecord], bool]:
        """Return the spans of ``trace_id`` ordered by start time.

        Returns:
            A ``(spans, truncated)`` tuple. ``truncated`` is True when the
            trace holds more spans than the backend's per-trace ceiling and
            the list was cut, so responses stay bounded for pathological
            traces. An unknown trace id returns ``([], False)``; callers
            decide whether that maps to a 404.
        """

    @abstractmethod
    def get_metrics_cost(self, *, window_hours: int = 24) -> dict:
        """Aggregate run cost over the trailing time window.

        Cost sums ``run_cost`` across ALL spans (it lives on whichever span
        made the LLM call, usually a child). ``trace_count`` is the number
        of traces with at least one span in the window — a different
        denominator from the latency/success metrics, which count root spans.
        """

    @abstractmethod
    def get_metrics_latency(self, *, window_hours: int = 24) -> dict:
        """Aggregate root-span latency (avg and p95) over the trailing window.

        Only root spans count: a trace's latency is its root span duration,
        and aggregating child spans would double-count nested work.
        """

    @abstractmethod
    def get_metrics_success(self, *, window_hours: int = 24) -> dict:
        """Aggregate run success rate over the trailing time window.

        Only root spans with a reported ``run_success`` enter the rate;
        spans that never reported an outcome are excluded rather than
        counted as failures.
        """

    @abstractmethod
    def health_check(self) -> None:
        """Verify the index is reachable and healthy."""
