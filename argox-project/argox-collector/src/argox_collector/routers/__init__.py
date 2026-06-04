"""Collector HTTP routers."""

from argox_collector.routers.health import router as health_router
from argox_collector.routers.query import router as query_router

__all__ = ["health_router", "query_router"]
