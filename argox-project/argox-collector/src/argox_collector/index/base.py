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


@dataclass(frozen=True)
class RunRecord:
    """Relational summary of a single agent run (``POST /v1/runs``).

    This is the flattened, queryable projection of an ``AgentRunMetrics``
    record. The full immutable payload lives in the blob store at
    ``blob_path``; only the columns needed to list, filter and join runs are
    promoted here. ``trace_id`` lets the Query API join from a span back to
    its originating run, and ``cost_usd`` is left ``None`` at ingest time and
    backfilled from ``model`` and the token totals by the run-cost path
    (COL-17, #142).
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
    blob_path: Optional[str] = None
    # Model used by the run, keyed against the price table to backfill
    # ``cost_usd`` (COL-17). ``None`` when the client did not report a model.
    model: Optional[str] = None


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
    def insert_run(self, record: RunRecord) -> None:
        """Add a single run summary to the index.

        First-write-wins on ``run_id``: an existing row is left untouched
        rather than overwritten, mirroring the immutable run blob. A re-ingest
        is therefore a safe no-op, while a row missing from a partially-failed
        earlier attempt is still created. The run-cost path backfills
        ``cost_usd`` through :meth:`set_run_cost`, not this method.
        """

    @abstractmethod
    def set_run_cost(self, run_id: str, cost_usd: Optional[float]) -> None:
        """Backfill the collector-derived ``cost_usd`` for a run (COL-17).

        A deliberate ``UPDATE`` kept separate from :meth:`insert_run` so it
        does not collide with the first-write-wins immutability of the run
        record: cost is a collector-derived field, not client content, so the
        blob and the client-reported columns stay untouched. A ``None`` cost
        (unknown model) leaves the column NULL. Updating an unknown ``run_id``
        is a harmless no-op.
        """

    @abstractmethod
    def is_run_audited(self, run_id: str) -> bool:
        """Return whether ``run_id`` needs no WORM append (COL-14).

        Tracks the one fact the hash chain cannot: whether a run still owes an
        audit entry. Backed by a tri-state flag — a COL-14-era run is stored
        ``False`` (awaiting/failed chaining) and flipped ``True`` once chained,
        while a run that predates COL-14 has no flag (``NULL``) and is out of
        scope (no retroactive backfill). This returns ``True`` for both the
        chained and the pre-COL-14 cases, so neither the re-ingest retry nor the
        reconcile sweep touches them; only an explicit ``False`` is retried. An
        unknown ``run_id`` returns ``False``.
        """

    @abstractmethod
    def list_unaudited_runs(self, *, limit: int) -> list[RunRecord]:
        """Return runs not yet appended to the WORM chain, oldest first (COL-14).

        Bounded by ``limit``. The reconciliation sweep uses this to retry runs
        whose audit append failed on an otherwise-successful request — the case
        a re-ingest never heals because the client saw success and does not
        resend. Only runs flagged ``False`` qualify; pre-COL-14 runs (flag
        ``NULL``) are excluded, so the sweep does not retroactively backfill
        history. Ordered by ingest time so the oldest gap is closed first.
        """

    @abstractmethod
    def mark_run_audited(self, run_id: str) -> None:
        """Record that ``run_id`` has been appended to the WORM chain (COL-14).

        Set only after the audit append succeeds, so a crash between the append
        and this call leaves the flag unset and the next re-ingest re-appends —
        biasing toward a duplicate audit entry over a missing one (over-
        recording is compliant; omission is not). Marking an unknown ``run_id``
        is a harmless no-op.
        """

    @abstractmethod
    def get_run_model_from_trace(self, trace_id: str) -> Optional[str]:
        """Return a model id from the spans of ``trace_id``, or ``None``.

        The span-side fallback for the run-cost backfill (COL-17): a run that
        does not report its own ``model`` is priced from the model its spans
        carry (``gen_ai.request.model``, set by PLUGIN-05; falling back to
        ``gen_ai.response.model``). Returns ``None`` when no span under the
        trace records a model.
        """

    @abstractmethod
    def list_runs(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        agent_name: Optional[str] = None,
        success: Optional[bool] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> tuple[list[RunRecord], int]:
        """Return paginated run summaries plus the total matching count (COL-13).

        Rows are the flat index projection only — the ``prompt`` and
        ``final_output`` payloads live in the blob and are never read here, so
        the list stays lightweight regardless of run size. Runs are sorted by
        collector ingest time, newest first; ``start``/``end`` filter the same
        ingest-time column (a half-open ``[start, end)`` interval) rather than
        the free-form client ``timestamp``, which need not be chronological.
        ``agent_name`` and ``success`` are exact-match filters; a ``None``
        filter is simply not applied.

        Returns:
            A ``(runs, total)`` tuple where ``total`` is the number of runs
            matching the filters regardless of pagination.
        """

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[RunRecord]:
        """Return the run summary for ``run_id``, or ``None`` if unknown."""

    @abstractmethod
    def get_run_by_trace_id(self, trace_id: str) -> Optional[RunRecord]:
        """Return the run whose ``trace_id`` matches, or ``None`` if unknown.

        This is the span-to-run join: given a span's ``trace_id`` the Query
        API recovers the full run record (prompt, output, per-call tokens)
        from the blob referenced by :attr:`RunRecord.blob_path`.
        """

    @abstractmethod
    def health_check(self) -> None:
        """Verify the index is reachable and healthy."""
