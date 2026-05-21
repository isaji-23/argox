"""Health and readiness endpoints used by orchestrators and load balancers."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from argox_collector import __version__

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


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    """Return ``ok`` when the process is alive and serving requests."""
    return HealthResponse(status="ok", service="argox-collector", version=__version__)


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz() -> ReadinessResponse:
    """Return ``ok`` when the service is ready to accept traffic.

    Downstream dependency checks (storage backend, DuckDB index) will be wired
    in subsequent COL-* tickets; for now the probe only reports process health.
    """
    return ReadinessResponse(
        status="ok",
        service="argox-collector",
        version=__version__,
        checks={"process": "ok"},
    )
