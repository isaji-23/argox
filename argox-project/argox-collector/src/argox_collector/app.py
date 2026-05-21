"""FastAPI application factory for the Argox Collector."""

from __future__ import annotations

from fastapi import FastAPI

from argox_collector import __version__
from argox_collector.logging import configure_logging
from argox_collector.routers import health
from argox_collector.settings import CollectorSettings


def create_app(settings: CollectorSettings | None = None) -> FastAPI:
    """Build and return a configured FastAPI application.

    Args:
        settings: Optional pre-built settings instance. When omitted, settings
            are loaded from the environment.

    Returns:
        A FastAPI app with health endpoints registered and structlog wired.
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
    app.include_router(health.router)
    return app


app = create_app()
