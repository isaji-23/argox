"""Audit-log API: append events and verify the hash chain (COL-08).

Handlers are plain ``def`` so FastAPI runs the blocking blob I/O in its
threadpool, mirroring the query and policy routers. There is intentionally no
delete or update endpoint — the audit log is append-only by design.

SECURITY (COL-09, #94): these endpoints are authenticated.
- ``POST`` binds ``actor`` to the authenticated principal (``admin`` scope), not
  to a client-supplied value, so entries cannot be forged under another
  identity — the authenticity at write time that the hash chain alone cannot
  guarantee, as AI Act Art. 12 non-repudiation requires.
- The read endpoints require the ``read`` scope: they disclose the whole audit
  trail and ``/verify`` re-reads every segment on each call (a cheap DoS vector
  if left open).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from argox_collector.audit import AuditEntry, AuditLog, AuditLogError
from argox_collector.auth import Principal, Scope, require_scope

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

_MAX_PAGE_SIZE = 1000
# 64-char lowercase SHA-256 hex digest.
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class AuditAppendRequest(BaseModel):
    """Body of ``POST /api/v1/audit``.

    ``actor`` is intentionally absent: it is bound to the authenticated
    principal, never read from the request, so an entry cannot be forged under
    another identity.

    Provide either ``payload`` (hashed server-side into a digest so the raw
    value is never persisted) or a pre-computed ``payload_digest`` — not both.
    Omitting both records the digest of an empty payload.
    """

    action: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    payload: Optional[Any] = None
    payload_digest: Optional[str] = Field(default=None, pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _reject_both(self) -> "AuditAppendRequest":
        if self.payload is not None and self.payload_digest is not None:
            raise ValueError("pass either payload or payload_digest, not both")
        return self


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
    """A bounded slice of the chain, oldest first.

    ``malformed`` is True when listing stopped early because a corrupt or
    truncated record was hit (mirroring ``/verify``); use ``/verify`` to locate
    the break. One bad line never fails the whole listing.
    """

    items: list[AuditEntryResponse]
    offset: int
    limit: int
    returned: int
    malformed: bool = False


def _audit(request: Request) -> AuditLog:
    return request.app.state.audit


@router.post("", response_model=AuditEntryResponse, status_code=201)
def append_entry(
    request: Request,
    body: AuditAppendRequest,
    principal: Principal = Depends(require_scope(Scope.ADMIN)),
) -> AuditEntryResponse:
    """Append an event to the audit log and return the sealed entry.

    ``actor`` is the authenticated principal, not a client-supplied value.
    """
    try:
        entry = _audit(request).append(
            actor=principal.subject,
            action=body.action,
            target=body.target,
            payload=body.payload,
            payload_digest=body.payload_digest,
        )
    except AuditLogError as exc:
        # Concurrent writer / unrecoverable state: not the client's fault.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AuditEntryResponse.from_entry(entry)


@router.get(
    "/verify",
    response_model=AuditVerifyResponse,
    dependencies=[Depends(require_scope(Scope.READ))],
)
def verify_chain(request: Request) -> AuditVerifyResponse:
    """Walk the hash chain and report the first broken link, if any."""
    result = _audit(request).verify()
    return AuditVerifyResponse(
        ok=result.ok,
        total_entries=result.total_entries,
        broken_seq=result.broken_seq,
        reason=result.reason,
    )


@router.get(
    "",
    response_model=AuditListResponse,
    dependencies=[Depends(require_scope(Scope.READ))],
)
def list_entries(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=_MAX_PAGE_SIZE),
) -> AuditListResponse:
    """Return up to ``limit`` entries in sequence order, starting at ``offset``.

    ``offset`` is a zero-based entry index so the whole log can be paged
    through, not only its first ``limit`` entries. A corrupt record stops the
    listing with ``malformed=True`` instead of raising a 500 (mirroring
    ``/verify``).
    """
    audit = _audit(request)
    items: list[AuditEntryResponse] = []
    malformed = False
    entries = audit.iter_entries(start=offset)
    while len(items) < limit:
        try:
            entry = next(entries)
        except StopIteration:
            break
        except (ValueError, KeyError):
            # A malformed/truncated line: stop here rather than 500. /verify
            # reports exactly where the chain breaks.
            malformed = True
            break
        items.append(AuditEntryResponse.from_entry(entry))
    return AuditListResponse(
        items=items,
        offset=offset,
        limit=limit,
        returned=len(items),
        malformed=malformed,
    )
