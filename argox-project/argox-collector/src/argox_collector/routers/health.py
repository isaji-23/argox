"""Health and readiness endpoints used by orchestrators and load balancers."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from argox_collector import __version__
from argox_collector.settings import CollectorSettings
from argox_collector.storage import StorageBackend, StorageError

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Payload returned by the liveness endpoint."""

    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Payload returned by the readiness endpoint."""

    status: str
    service: str
    version: str
    checks: dict[str, str]


def _service_name(request: Request) -> str:
    settings: CollectorSettings = request.app.state.settings
    return settings.service_name


def _storage(request: Request) -> StorageBackend:
    return request.app.state.storage


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(request: Request) -> HealthResponse:
    """Return ``ok`` when the process is alive and serving requests."""
    return HealthResponse(
        status="ok", service=_service_name(request), version=__version__
    )


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(request: Request) -> ReadinessResponse:
    """Return ``ok`` when the service is ready to accept traffic.

    The readiness probe pings the configured storage backend so orchestrators
    can drop the replica from rotation when the blob layer is unreachable.
    Index-layer checks (DuckDB, audit log) will be added in subsequent
    COL-* tickets.
    """
    checks = {"process": "ok"}
    try:
        _storage(request).health_check()
        checks["storage"] = "ok"
        status = "ok"
    except StorageError as exc:
        checks["storage"] = f"unavailable: {exc}"
        status = "degraded"

    return ReadinessResponse(
        status=status,
        service=_service_name(request),
        version=__version__,
        checks=checks,
    )
