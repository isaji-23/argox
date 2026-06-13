"""Admin-only API key CRUD endpoints (COL-09).

Every route here requires the ``admin`` scope. Creation returns the raw key
exactly once — it is never stored in plaintext nor retrievable later — so the
operator must copy it at that moment. Listing exposes only non-secret metadata
(id, name, scopes, prefix, lifecycle timestamps), never the hash.
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from argox_collector.auth import (
    ApiKeyRecord,
    ApiKeyStore,
    ApiKeyStoreError,
    Principal,
    Scope,
    mint_key,
    parse_scopes,
    require_scope,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])


class ApiKeyCreate(BaseModel):
    """Request body for ``POST /api/v1/keys``."""

    name: str = Field(..., min_length=1, max_length=200)
    scopes: list[str] = Field(..., min_length=1)


class ApiKeyView(BaseModel):
    """Non-secret view of a stored key."""

    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    created_at: str
    created_by: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked: bool

    @classmethod
    def from_record(cls, record: ApiKeyRecord) -> "ApiKeyView":
        return cls(
            id=record.id,
            name=record.name,
            key_prefix=record.key_prefix,
            scopes=sorted(scope.value for scope in record.scopes),
            created_at=record.created_at.isoformat(),
            created_by=record.created_by,
            revoked_at=record.revoked_at.isoformat() if record.revoked_at else None,
            revoked=record.revoked,
        )


class ApiKeyCreateResponse(ApiKeyView):
    """Create response: the metadata view plus the one-time raw secret."""

    key: str


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyView]
    total: int


def _store(request: Request) -> ApiKeyStore:
    store = getattr(request.app.state, "api_key_store", None)
    if store is None:
        # Auth is enabled but no store was wired — a misconfiguration, not a
        # client error.
        raise HTTPException(status_code=503, detail="api key store unavailable")
    return store


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
def create_key(
    request: Request,
    payload: ApiKeyCreate,
    principal: Principal = Depends(require_scope(Scope.ADMIN)),
) -> ApiKeyCreateResponse:
    """Mint a new API key and return its raw secret once."""
    try:
        scopes = parse_scopes(payload.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    new_key = mint_key(
        name=payload.name, scopes=scopes, created_by=principal.subject
    )
    try:
        record = _store(request).create(new_key.record)
    except ApiKeyStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(
        "api_key_created",
        key_id=record.id,
        created_by=principal.subject,
        scopes=sorted(scope.value for scope in record.scopes),
    )
    view = ApiKeyView.from_record(record)
    return ApiKeyCreateResponse(**view.model_dump(), key=new_key.raw_key)


@router.get("", response_model=ApiKeyListResponse)
def list_keys(
    request: Request,
    _: Principal = Depends(require_scope(Scope.ADMIN)),
) -> ApiKeyListResponse:
    """List every key's non-secret metadata, newest first."""
    records = _store(request).list()
    return ApiKeyListResponse(
        keys=[ApiKeyView.from_record(record) for record in records],
        total=len(records),
    )


@router.delete("/{key_id}", status_code=204)
def revoke_key(
    request: Request,
    key_id: str = PathParam(..., min_length=1),
    principal: Principal = Depends(require_scope(Scope.ADMIN)),
) -> None:
    """Revoke a key. Idempotent: revoking an unknown/already-revoked key is 404."""
    revoked = _store(request).revoke(key_id)
    if not revoked:
        raise HTTPException(
            status_code=404, detail="no active key with that id"
        )
    logger.info("api_key_revoked", key_id=key_id, revoked_by=principal.subject)
