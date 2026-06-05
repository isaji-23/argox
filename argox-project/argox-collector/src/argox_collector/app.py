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
    
    COL-03 R2 Finding 1: Content-Length header is optional (Transfer-Encoding: chunked).
    We verify the actual body size, not just the header, to prevent chunked encoding bypass.
    """
    
    def __init__(self, app, max_size: int):
        """
        Initialize middleware with configurable payload size limit.
        
        Args:
            app: FastAPI app instance
            max_size: Maximum allowed payload size in bytes (default 10MB)
        """
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        """
        Check payload size before processing.
        
        Verifies actual body size to prevent chunked encoding bypass attacks.
        request.body() is cached in request._body after first call, so safe for re-reads.
        """
        # Only enforce limit on routes that accept payloads
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                # ✅ Read actual body (not just Content-Length header)
                # This catches chunked encoding attacks where Content-Length may be omitted
                body = await request.body()
                if len(body) > self.max_size:
                    return Response(
                        content=f"Payload too large. Maximum size is {self.max_size} bytes.",
                        status_code=413,
                    )
            except Exception:
                # If body read fails, let the app handle it
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
    
    # Add payload size limit middleware with configurable limit from settings
    # COL-03 R2 Finding 1: Verifies actual body size (not just header) to prevent
    # chunked encoding bypass attacks
    # COL-03 R2 Finding 3: Limit is configurable via CollectorSettings
    app.add_middleware(PayloadSizeLimitMiddleware, max_size=settings.max_payload_size)
    
    app.include_router(health.router)
    app.include_router(ingest.router)
    return app
