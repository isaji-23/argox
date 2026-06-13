"""FastAPI application factory for the Argox Collector."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from argox_collector import __version__
from argox_collector.audit import AuditLog
from argox_collector.auth import (
    ApiKeyStore,
    Authenticator,
    build_api_key_store,
    build_authenticator,
)
from argox_collector.index import TraceIndex, build_index
from argox_collector.logging import configure_logging
from argox_collector.middleware import PayloadSizeLimitMiddleware
from argox_collector.routers import audit, health, keys, policies, query, traces
from argox_collector.settings import CollectorSettings
from argox_collector.storage import StorageBackend, build_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Clean up index connections
    if hasattr(app.state, "index") and app.state.index is not None:
        if hasattr(app.state.index, "close"):
            app.state.index.close()
    # Close the API key store's own DuckDB connection, but only if the app
    # opened it (an injected store belongs to the caller).
    store = getattr(app.state, "api_key_store", None)
    if (
        store is not None
        and getattr(app.state, "owns_api_key_store", False)
        and hasattr(store, "close")
    ):
        store.close()


def create_app(
    settings: Optional[CollectorSettings] = None,
    *,
    storage: Optional[StorageBackend] = None,
    index: Optional[TraceIndex] = None,
    audit_log: Optional[AuditLog] = None,
    api_key_store: Optional[ApiKeyStore] = None,
    authenticator: Optional[Authenticator] = None,
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
        audit_log: Optional pre-built audit log. When omitted, one is
            constructed over ``app.state.storage`` from ``settings``.
        api_key_store: Optional pre-built API key store. When omitted and auth
            is enabled, one is opened on the index DB path. Tests inject a
            temp-path store here. The app closes a store it opened itself.
        authenticator: Optional pre-built authenticator. When omitted, one is
            built from ``settings`` over the API key store.

    Returns:
        A FastAPI app with health endpoints registered, structlog wired and
        the storage, index, audit log and authenticator attached to
        ``app.state``.
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
    app.state.audit = (
        audit_log
        if audit_log is not None
        else AuditLog(
            app.state.storage,
            prefix=settings.audit_log_prefix,
            max_segment_records=settings.audit_segment_max_records,
        )
    )

    # Authentication (COL-09). A key store is opened lazily only when auth is on
    # and none was injected. The app closes a store it opened itself (tracked by
    # ``owns_api_key_store``); an injected store's lifecycle stays with the test.
    key_store = api_key_store
    app.state.owns_api_key_store = False
    if key_store is None and settings.auth_enabled:
        key_store = build_api_key_store(settings)
        app.state.owns_api_key_store = True
    app.state.api_key_store = key_store
    app.state.auth = authenticator or build_authenticator(
        settings, key_store=key_store
    )

    app.add_middleware(
        PayloadSizeLimitMiddleware, max_bytes=settings.max_payload_size
    )
    cors_origins = settings.cors_origin_list
    if cors_origins:
        # Only installed when origins are configured: an empty default keeps
        # same-origin deployments free of permissive CORS headers.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    app.include_router(traces.router)
    app.include_router(policies.router)
    app.include_router(query.router)
    app.include_router(audit.router)
    app.include_router(keys.router)
    return app
