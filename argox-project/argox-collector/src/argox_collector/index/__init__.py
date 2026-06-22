"""Relational indexing for trace and span metadata."""

from __future__ import annotations

from argox_collector.index.base import (
    RunRecord,
    SpanRecord,
    TraceIndex,
    TraceIndexError,
    ALLOWED_SORT_FIELDS,
)
from argox_collector.index.duckdb import DuckDBTraceIndex
from argox_collector.index.factory import build_index

__all__ = [
    "RunRecord",
    "SpanRecord",
    "TraceIndex",
    "TraceIndexError",
    "DuckDBTraceIndex",
    "build_index",
    "ALLOWED_SORT_FIELDS",
]
