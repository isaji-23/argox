"""FastAPI application factory for the Argox Collector."""

from __future__ import annotations

from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from argox_collector import __version__
from argox_collector.index import TraceIndex, build_index
from argox_collector.logging import configure_logging
from argox_collector.routers import health, ingest
from argox_collector.settings import CollectorSettings
from argox_collector.storage import StorageBackend, build_storage


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce maximum payload size and prevent OOM attacks.
    
    COL-03 Finding 3: Without size limits, buggy or malicious clients can send
    arbitrarily large payloads causing OOM under concurrent load.
    """
    
    # 10 MB limit for OTLP trace payloads (typical traces are KB-sized)
    MAX_PAYLOAD_SIZE = 10 * 1024 * 1024

    async def dispatch(self, request: Request, call_next):
        """Check payload size before processing."""
        # Only enforce limit on routes that accept payloads
        if request.method in ["POST", "PUT", "PATCH"]:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    size = int(content_length)
                    if size > self.MAX_PAYLOAD_SIZE:
                        return Response(
                            content=f"Payload too large. Maximum size is {self.MAX_PAYLOAD_SIZE} bytes.",
                            status_code=413,
                        )
                except ValueError:
                    pass
        
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Clean up index connections
    if hasattr(app.state, "index") and app.state.index is not None:
        if hasattr(app.state.index, "close"):
            app.state.index.close()


def create_app(
    settings: Optional[CollectorSettings] = None,
    *,
    storage: Optional[StorageBackend] = None,
    index: Optional[TraceIndex] = None,
) -> FastAPI:
    """Build and return a configured FastAPI application.

    Args:
        settings: Optional pre-built settings instance. When omitted, settings
            are loaded from the environment.
        storage: Optional pre-built storage backend. When omitted, one is
            constructed from ``settings``. Tests inject in-memory or local
            backends through this argument.
        index: Optional pre-built trace index. When omitted, one is
            constructed from ``settings``.

    Returns:
        A FastAPI app with health endpoints registered, structlog wired and
        the storage and index backends attached to ``app.state``.
    """
    settings = settings or CollectorSettings()
    configure_logging(level=settings.log_level)

    app = FastAPI(
        title="Argox Collector",
        version=__version__,
        description=(
            "Server-side ingestion, indexing and policy distribution service "
            "for the Argox observability platform."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.storage = storage if storage is not None else build_storage(settings)
    app.state.index = index if index is not None else build_index(settings)
    
    # Add payload size limit middleware (COL-03 Finding 3)
    app.add_middleware(PayloadSizeLimitMiddleware)
    
    app.include_router(health.router)
    app.include_router(ingest.router)
    return app
