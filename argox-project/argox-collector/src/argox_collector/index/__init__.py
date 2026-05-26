"""Relational indexing for trace and span metadata."""

from __future__ import annotations

from argox_collector.index.base import SpanRecord, TraceIndex
from argox_collector.index.duckdb import DuckDBTraceIndex
from argox_collector.index.factory import build_index

__all__ = [
    "SpanRecord",
    "TraceIndex",
    "DuckDBTraceIndex",
    "build_index",
]
