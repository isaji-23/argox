"""FastAPI application factory for the Argox Collector."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from argox_collector import __version__
from argox_collector.logging import configure_logging
from argox_collector.routers import health
from argox_collector.settings import CollectorSettings
from argox_collector.storage import StorageBackend, build_storage


def create_app(
    settings: Optional[CollectorSettings] = None,
    *,
    storage: Optional[StorageBackend] = None,
) -> FastAPI:
    """Build and return a configured FastAPI application.

    Args:
        settings: Optional pre-built settings instance. When omitted, settings
            are loaded from the environment.
        storage: Optional pre-built storage backend. When omitted, one is
            constructed from ``settings``. Tests inject in-memory or local
            backends through this argument.

    Returns:
        A FastAPI app with health endpoints registered, structlog wired and
        the storage backend attached to ``app.state``.
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
    )
    app.state.settings = settings
    app.state.storage = storage if storage is not None else build_storage(settings)
    app.include_router(health.router)
    return app
