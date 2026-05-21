"""Health and readiness endpoints used by orchestrators and load balancers."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from argox_collector import __version__
from argox_collector.settings import CollectorSettings

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


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(request: Request) -> HealthResponse:
    """Return ``ok`` when the process is alive and serving requests."""
    return HealthResponse(
        status="ok", service=_service_name(request), version=__version__
    )


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(request: Request) -> ReadinessResponse:
    """Return ``ok`` when the service is ready to accept traffic.

    Downstream dependency checks (storage backend, DuckDB index) will be wired
    in subsequent COL-* tickets; for now the probe only reports process health.
    """
    return ReadinessResponse(
        status="ok",
        service=_service_name(request),
        version=__version__,
        checks={"process": "ok"},
    )
