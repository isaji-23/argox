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
    name: str = ""
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
    def health_check(self) -> None:
        """Verify the index is reachable and healthy."""
