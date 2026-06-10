"""Policy CRUD endpoints and the merged ``/bundle`` endpoint (COL-05).

Storage layout — content-addressed blobs plus a versioned manifest:

- Each policy version is an immutable YAML document stored at
  ``policies/{policy_id}/{content_hash}.yaml``. The key is derived from the
  document's own SHA-256, so concurrent writers can never clobber each
  other's data: identical content is idempotent, different content lands on
  a different key.
- A single manifest (``policies/manifest.json``) maps every policy to its
  version history: ``{"policies": {id: {"status", "latest_version",
  "active_version", "versions": {"1": "<hash>", ...}}}}``.

Every mutation follows the same commit protocol:

1. Write the version blob first. An orphaned blob (crash or lost race) is
   harmless garbage — it is unreachable until the manifest references it.
2. Commit the manifest with a conditional write (``expected_etag``): the
   ETag observed at read time for updates, or the create-only sentinel
   ``"*"`` when the manifest does not exist yet. A lost race raises
   ``ConditionNotMetError`` and the whole read-build-commit cycle retries.

Readers only trust the manifest: a version exists exactly when the manifest
references it. Handlers are plain ``def`` so FastAPI runs the blocking
storage I/O in its threadpool.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
import yaml
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict, Field, field_validator

from argox_collector.storage import (
    BlobNotFoundError,
    ConditionNotMetError,
    StorageBackend,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])

_MANIFEST_KEY = "policies/manifest.json"
_YAML_CONTENT_TYPE = "application/x-yaml"
# Mirrors the constraints of normalize_key(): ids built from this alphabet can
# never produce an invalid or escaping blob key, so the storage layer's
# ValueError path is unreachable from these endpoints.
_ID_PATTERN = r"^[a-zA-Z0-9_-]+$"
_CAS_ATTEMPTS = 5
_BUNDLE_ID = "bundle_active"
_MAX_PAGE_SIZE = 100
# Upper bound on rules per policy version. Caps request payload size and the
# fan-in of the merged /bundle, which concatenates the rules of every active
# policy on each request (see ADR-0003 follow-ups).
_MAX_RULES_PER_POLICY = 1000
# Policy ids that collide with a static route under this router and would
# therefore be unreachable through ``GET /{policy_id}``. ``bundle`` is shadowed
# by ``GET /api/v1/policies/bundle``, so it must not be a valid policy id.
_RESERVED_IDS = frozenset({"bundle"})


def _reject_reserved_id(value: str) -> str:
    if value in _RESERVED_IDS:
        raise ValueError(f"policy id {value!r} is reserved")
    return value


class RuleCondition(BaseModel):
    """Single comparison inside a rule; mirrors the SDK parser schema."""

    model_config = ConfigDict(str_strip_whitespace=True)

    metric: str
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains", "in"]
    threshold: Any


class PolicyRule(BaseModel):
    """Single enforcement rule; mirrors the SDK parser schema."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=_ID_PATTERN)
    trigger: str
    condition: RuleCondition
    action: Literal["block", "alert", "ok"]
    enforcement: str = "strict"


class PolicyCreate(BaseModel):
    """Request body for ``POST /api/v1/policies``."""

    id: str = Field(pattern=_ID_PATTERN)
    status: Literal["active", "draft", "archived"] = "draft"
    rules: list[PolicyRule] = Field(max_length=_MAX_RULES_PER_POLICY)
    created_by: str | None = None

    _reject_reserved = field_validator("id")(_reject_reserved_id)


class PolicyUpdate(BaseModel):
    """Request body for ``PUT /api/v1/policies/{id}`` (creates version n+1)."""

    status: Literal["active", "draft", "archived"]
    rules: list[PolicyRule] = Field(max_length=_MAX_RULES_PER_POLICY)
    created_by: str | None = None


class PolicyResponse(BaseModel):
    """A stored policy version plus the hash addressing its blob."""

    id: str
    version: int
    status: Literal["active", "draft", "archived"]
    rules: list[PolicyRule]
    created_by: str | None = None
    updated_at: str | None = None
    content_hash: str


class PolicySummary(BaseModel):
    """Manifest-level view of one policy; no blob reads required."""

    id: str
    status: Literal["active", "draft", "archived"]
    latest_version: int
    active_version: int | None = None


class PolicyListResponse(BaseModel):
    policies: list[PolicySummary]
    total: int


def _storage(request: Request) -> StorageBackend:
    return request.app.state.storage


def _read_manifest(storage: StorageBackend) -> tuple[dict[str, Any], str | None]:
    """Return ``(manifest, etag)``.

    ``etag is None`` means the manifest does not exist yet; the caller must
    commit with the create-only sentinel. An existing ETag is preserved
    verbatim so the conditional write targets exactly the state that was
    read. A corrupt manifest raises (``json.JSONDecodeError`` → 500) instead
    of being silently treated as empty, which would orphan every policy.
    """
    try:
        blob = storage.get(_MANIFEST_KEY)
    except BlobNotFoundError:
        return {"policies": {}}, None
    return json.loads(blob.data.decode("utf-8")), blob.metadata.etag


def _commit_manifest(
    storage: StorageBackend, manifest: dict[str, Any], etag: str | None
) -> None:
    """Conditionally write the manifest observed at ``etag`` (None = absent)."""
    storage.put(
        _MANIFEST_KEY,
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        content_type="application/json",
        expected_etag=etag if etag is not None else "*",
    )


def _blob_key(policy_id: str, content_hash: str) -> str:
    return f"policies/{policy_id}/{content_hash}.yaml"


def _build_document(
    policy_id: str,
    version: int,
    status: str,
    rules: list[dict[str, Any]],
    created_by: str | None,
    updated_at: str,
) -> dict[str, Any]:
    """Build the full document dict that gets serialized into the blob.

    ``version`` is part of the serialized content, so it must be final here —
    the stored YAML is what every later GET returns.
    """
    return {
        "id": policy_id,
        "version": version,
        "status": status,
        "rules": rules,
        "created_by": created_by,
        "updated_at": updated_at,
    }


def _write_version_blob(
    storage: StorageBackend, policy_id: str, document: dict[str, Any]
) -> str:
    """Serialize ``document`` and persist it content-addressed; return its hash."""
    text = yaml.safe_dump(document, sort_keys=True)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    storage.put(
        _blob_key(policy_id, content_hash),
        text.encode("utf-8"),
        content_type=_YAML_CONTENT_TYPE,
    )
    return content_hash


def _load_document(
    storage: StorageBackend, policy_id: str, content_hash: str
) -> dict[str, Any]:
    """Load and parse a committed version blob.

    Raises:
        BlobNotFoundError: If the manifest references a blob that is gone
            (dangling pointer); callers decide whether that is fatal.
    """
    blob = storage.get(_blob_key(policy_id, content_hash))
    document = yaml.safe_load(blob.data.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(
            f"policy blob for {policy_id!r} does not contain a mapping"
        )
    return document


def _version_hash(entry: dict[str, Any], version: int) -> str:
    return entry["versions"][str(version)]


def _response_from(document: dict[str, Any], content_hash: str) -> PolicyResponse:
    return PolicyResponse(**document, content_hash=content_hash)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cas_exhausted() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="too many concurrent policy updates; retry the request",
    )


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """RFC 9110 ``If-None-Match`` comparison against a strong ETag."""
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    for candidate in if_none_match.split(","):
        candidate = candidate.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate == etag:
            return True
    return False


@router.get("", response_model=PolicyListResponse)
def list_policies(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> PolicyListResponse:
    """List policy summaries straight from the manifest, sorted by id.

    Sorting makes pagination deterministic regardless of manifest insertion
    order, and serving from the manifest alone keeps the endpoint O(1) blob
    reads no matter how many policies exist.
    """
    manifest, _ = _read_manifest(_storage(request))
    entries = sorted(manifest.get("policies", {}).items())
    page = entries[skip : skip + limit]
    return PolicyListResponse(
        policies=[
            PolicySummary(
                id=policy_id,
                status=entry["status"],
                latest_version=entry["latest_version"],
                active_version=entry.get("active_version"),
            )
            for policy_id, entry in page
        ],
        total=len(entries),
    )


@router.get("/bundle")
def get_bundle(request: Request) -> Response:
    """Merge the rules of every active policy into one SDK-consumable YAML.

    The response is a valid ``PolicyDocument`` for the SDK parser. The ETag
    is the SHA-256 of the YAML body, so it only changes when the effective
    rule set changes; ``If-None-Match`` hits answer ``304``. This handler
    never writes — GET stays idempotent and proxy-cacheable.
    """
    storage = _storage(request)
    manifest, _ = _read_manifest(storage)

    merged_rules: list[dict[str, Any]] = []
    # Sorted iteration keeps rule order — and therefore the ETag — stable
    # across requests and across manifest rewrites.
    for policy_id, entry in sorted(manifest.get("policies", {}).items()):
        if entry.get("status") != "active":
            continue
        active_version = entry.get("active_version")
        if active_version is None:
            continue
        try:
            document = _load_document(
                storage, policy_id, _version_hash(entry, active_version)
            )
        except (BlobNotFoundError, ValueError, KeyError) as exc:
            # The merged bundle is a fleet-wide enforcement path, so one
            # unreadable policy must never deny the ruleset to everyone else.
            # Skip and loudly log just this policy. Covered cases:
            #   BlobNotFoundError — dangling manifest pointer (committed
            #     version whose blob was later lost).
            #   KeyError — manifest inconsistency (active_version absent from
            #     the version table).
            #   ValueError — blob present but not a policy mapping (corruption
            #     or hand-editing).
            logger.error(
                "policy_bundle_unreadable",
                policy_id=policy_id,
                version=active_version,
                error=str(exc),
            )
            continue
        merged_rules.extend(document.get("rules") or [])

    bundle = {
        "id": _BUNDLE_ID,
        "version": 1,
        "status": "active",
        "rules": merged_rules,
    }
    body = yaml.safe_dump(bundle, sort_keys=True)
    etag = '"' + hashlib.sha256(body.encode("utf-8")).hexdigest() + '"'

    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=body, media_type=_YAML_CONTENT_TYPE, headers={"ETag": etag}
    )


@router.get("/{policy_id}", response_model=PolicyResponse)
def get_active_policy(
    request: Request,
    policy_id: str = PathParam(pattern=_ID_PATTERN),
) -> PolicyResponse:
    """Return the active version of a policy.

    A policy without an active version (draft or archived) is 404: clients
    must never mistake a retired document for an enforceable one.
    """
    storage = _storage(request)
    manifest, _ = _read_manifest(storage)
    entry = manifest.get("policies", {}).get(policy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="policy not found")
    active_version = entry.get("active_version")
    if active_version is None:
        raise HTTPException(
            status_code=404,
            detail=f"policy {policy_id!r} has no active version",
        )
    content_hash = _version_hash(entry, active_version)
    try:
        document = _load_document(storage, policy_id, content_hash)
    except BlobNotFoundError:
        logger.error(
            "policy_dangling_pointer",
            policy_id=policy_id,
            version=active_version,
        )
        raise HTTPException(
            status_code=500,
            detail="policy data missing for committed version",
        ) from None
    return _response_from(document, content_hash)


@router.get("/{policy_id}/v{version}", response_model=PolicyResponse)
def get_policy_version(
    request: Request,
    policy_id: str = PathParam(pattern=_ID_PATTERN),
    version: int = PathParam(ge=1),
) -> PolicyResponse:
    """Return one specific committed version of a policy.

    The lookup goes through the manifest, so blobs that were written but
    never committed (lost CAS races) are not reachable here.
    """
    storage = _storage(request)
    manifest, _ = _read_manifest(storage)
    entry = manifest.get("policies", {}).get(policy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="policy not found")
    content_hash = entry.get("versions", {}).get(str(version))
    if content_hash is None:
        raise HTTPException(status_code=404, detail="policy version not found")
    try:
        document = _load_document(storage, policy_id, content_hash)
    except BlobNotFoundError:
        logger.error(
            "policy_dangling_pointer", policy_id=policy_id, version=version
        )
        raise HTTPException(
            status_code=500,
            detail="policy data missing for committed version",
        ) from None
    return _response_from(document, content_hash)


@router.post("", response_model=PolicyResponse, status_code=201)
def create_policy(request: Request, payload: PolicyCreate) -> PolicyResponse:
    """Create a new policy as version 1."""
    storage = _storage(request)
    rules = [rule.model_dump() for rule in payload.rules]
    for _ in range(_CAS_ATTEMPTS):
        manifest, etag = _read_manifest(storage)
        policies = manifest.setdefault("policies", {})
        if payload.id in policies:
            raise HTTPException(
                status_code=409,
                detail=f"policy {payload.id!r} already exists",
            )
        document = _build_document(
            payload.id, 1, payload.status, rules, payload.created_by, _now_iso()
        )
        content_hash = _write_version_blob(storage, payload.id, document)
        policies[payload.id] = {
            "status": payload.status,
            "latest_version": 1,
            "active_version": 1 if payload.status == "active" else None,
            "versions": {"1": content_hash},
        }
        try:
            _commit_manifest(storage, manifest, etag)
        except ConditionNotMetError:
            continue
        return _response_from(document, content_hash)
    raise _cas_exhausted()


@router.put("/{policy_id}", response_model=PolicyResponse)
def update_policy(
    request: Request,
    payload: PolicyUpdate,
    policy_id: str = PathParam(pattern=_ID_PATTERN),
) -> PolicyResponse:
    """Create version n+1 of an existing policy.

    The version number is taken from the manifest read inside the CAS cycle,
    so two concurrent updates can never both commit the same number: the
    loser's manifest write fails and it retries against the new state.
    """
    storage = _storage(request)
    rules = [rule.model_dump() for rule in payload.rules]
    for _ in range(_CAS_ATTEMPTS):
        manifest, etag = _read_manifest(storage)
        entry = manifest.get("policies", {}).get(policy_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="policy not found")
        new_version = entry["latest_version"] + 1
        document = _build_document(
            policy_id,
            new_version,
            payload.status,
            rules,
            payload.created_by,
            _now_iso(),
        )
        content_hash = _write_version_blob(storage, policy_id, document)
        entry["latest_version"] = new_version
        entry["status"] = payload.status
        # active_version always tracks the new head: it points at the new
        # version while active and is cleared otherwise, so reads can never
        # serve a stale "active" document after a status transition.
        entry["active_version"] = (
            new_version if payload.status == "active" else None
        )
        entry["versions"][str(new_version)] = content_hash
        try:
            _commit_manifest(storage, manifest, etag)
        except ConditionNotMetError:
            continue
        return _response_from(document, content_hash)
    raise _cas_exhausted()


@router.delete("/{policy_id}", response_model=PolicyResponse)
def archive_policy(
    request: Request,
    policy_id: str = PathParam(pattern=_ID_PATTERN),
) -> PolicyResponse:
    """Archive a policy by committing a new ``archived`` version.

    History is preserved — nothing is deleted. Archiving an already-archived
    policy is idempotent: it returns the current head without writing a new
    version, keeping the response shape identical to the first call.
    """
    storage = _storage(request)
    for _ in range(_CAS_ATTEMPTS):
        manifest, etag = _read_manifest(storage)
        entry = manifest.get("policies", {}).get(policy_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="policy not found")
        head_hash = _version_hash(entry, entry["latest_version"])
        try:
            head_document = _load_document(storage, policy_id, head_hash)
        except BlobNotFoundError:
            logger.error(
                "policy_dangling_pointer",
                policy_id=policy_id,
                version=entry["latest_version"],
            )
            raise HTTPException(
                status_code=500,
                detail="policy data missing for committed version",
            ) from None
        if entry["status"] == "archived":
            return _response_from(head_document, head_hash)
        new_version = entry["latest_version"] + 1
        document = _build_document(
            policy_id,
            new_version,
            "archived",
            head_document.get("rules") or [],
            head_document.get("created_by"),
            _now_iso(),
        )
        content_hash = _write_version_blob(storage, policy_id, document)
        entry["latest_version"] = new_version
        entry["status"] = "archived"
        entry["active_version"] = None
        entry["versions"][str(new_version)] = content_hash
        try:
            _commit_manifest(storage, manifest, etag)
        except ConditionNotMetError:
            continue
        return _response_from(document, content_hash)
    raise _cas_exhausted()
