"""Audit-log API: append events and verify the hash chain (COL-08).

Handlers are plain ``def`` so FastAPI runs the blocking blob I/O in its
threadpool, mirroring the query and policy routers. There is intentionally no
delete or update endpoint — the audit log is append-only by design.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from argox_collector.audit import AuditEntry, AuditLog

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

_MAX_PAGE_SIZE = 1000


class AuditAppendRequest(BaseModel):
    """Body of ``POST /api/v1/audit``.

    Provide either ``payload`` (hashed server-side into a digest so the raw
    value is never persisted) or a pre-computed ``payload_digest``.
    """

    actor: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    payload: Optional[Any] = None
    payload_digest: Optional[str] = None


class AuditEntryResponse(BaseModel):
    """One persisted, hash-chained audit entry."""

    seq: int
    timestamp: str
    actor: str
    action: str
    target: str
    payload_digest: str
    prev_hash: str
    hash: str

    @classmethod
    def from_entry(cls, entry: AuditEntry) -> "AuditEntryResponse":
        return cls(**entry.to_dict())


class AuditVerifyResponse(BaseModel):
    """Result of walking the chain."""

    ok: bool
    total_entries: int
    broken_seq: Optional[int] = None
    reason: Optional[str] = None


class AuditListResponse(BaseModel):
    """A bounded slice of the chain, oldest first."""

    items: list[AuditEntryResponse]
    count: int


def _audit(request: Request) -> AuditLog:
    return request.app.state.audit


@router.post("", response_model=AuditEntryResponse, status_code=201)
def append_entry(request: Request, body: AuditAppendRequest) -> AuditEntryResponse:
    """Append an event to the audit log and return the sealed entry."""
    entry = _audit(request).append(
        actor=body.actor,
        action=body.action,
        target=body.target,
        payload=body.payload,
        payload_digest=body.payload_digest,
    )
    return AuditEntryResponse.from_entry(entry)


@router.get("/verify", response_model=AuditVerifyResponse)
def verify_chain(request: Request) -> AuditVerifyResponse:
    """Walk the hash chain and report the first broken link, if any."""
    result = _audit(request).verify()
    return AuditVerifyResponse(
        ok=result.ok,
        total_entries=result.total_entries,
        broken_seq=result.broken_seq,
        reason=result.reason,
    )


@router.get("", response_model=AuditListResponse)
def list_entries(
    request: Request,
    limit: int = Query(100, ge=1, le=_MAX_PAGE_SIZE),
) -> AuditListResponse:
    """Return the first ``limit`` entries in sequence order."""
    audit = _audit(request)
    items: list[AuditEntryResponse] = []
    for entry in audit.iter_entries():
        items.append(AuditEntryResponse.from_entry(entry))
        if len(items) >= limit:
            break
    return AuditListResponse(items=items, count=len(items))
