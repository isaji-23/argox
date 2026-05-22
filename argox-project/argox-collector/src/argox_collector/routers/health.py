"""Health and readiness endpoints used by orchestrators and load balancers."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
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


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
    summary="Readiness probe",
)
async def readyz(request: Request) -> JSONResponse:
    """Report whether the service is ready to accept traffic.

    Probes the configured storage backend so orchestrators can drop the
    replica from rotation when the blob layer is unreachable. Returns
    ``503`` (still with the structured ``checks`` payload) on degradation
    so standard readiness probes react without parsing the body.
    Index-layer checks (DuckDB, audit log) will be added in later
    COL-* tickets.
    """
    checks = {"process": "ok"}
    status_code = 200
    overall = "ok"
    try:
        _storage(request).health_check()
        checks["storage"] = "ok"
    except StorageError as exc:
        checks["storage"] = f"unavailable: {exc}"
        overall = "degraded"
        status_code = 503

    payload = ReadinessResponse(
        status=overall,
        service=_service_name(request),
        version=__version__,
        checks=checks,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())
