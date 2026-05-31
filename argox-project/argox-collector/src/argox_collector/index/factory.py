"""Build a :class:`TraceIndex` from :class:`CollectorSettings`."""

from __future__ import annotations

from argox_collector.index.base import TraceIndex
from argox_collector.index.duckdb import DuckDBTraceIndex
from argox_collector.settings import CollectorSettings


def build_index(settings: CollectorSettings) -> TraceIndex:
    """Return the index backend selected by ``settings``.

    Args:
        settings: Collector configuration; ``index_backend`` and the
            backend-specific fields select the driver.

    Raises:
        ValueError: If the requested backend is unknown.
    """
    backend = settings.index_backend.lower()
    if backend == "duckdb":
        return DuckDBTraceIndex(db_path=settings.index_duckdb_path)
    
    raise ValueError(f"unknown index backend: {settings.index_backend!r}")
