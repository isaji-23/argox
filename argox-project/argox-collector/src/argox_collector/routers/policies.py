from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import BaseModel, ConfigDict, Field

from argox_collector.storage import BlobNotFoundError, StorageBackend, ConditionNotMetError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])

# === STORAGE STRATEGY: Content-Addressed Blobs + Versioned Manifest Pointers ===
#
# Policy documents are stored immutably at content-addressed keys:
#   policies/{policy_id}/{content_hash}.yaml
#
# The manifest (policies/manifest.json) maps versions to content hashes:
#   { "policies": { "pol_01": { "versions": { "1": "sha256:abc...", "2": "sha256:def..." }, ... } } }
#
# This architecture ensures data safety in concurrent scenarios:
#   1. Write blob first → safe for concurrent writers (same content = idempotent, unique key = no clobber)
#   2. Update manifest with CAS → atomic commit point (version <-> content binding)
#   3. Crash after blob write → only leaves orphaned blob (no dangling pointers)
#   4. No pointer-first or data-first races → content hash makes the key unique and immutable


class RuleCondition(BaseModel):
    metric: str
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains", "in"]
    threshold: Any


class PolicyRule(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    trigger: str
    condition: RuleCondition
    action: Literal["block", "alert", "ok"]
    enforcement: str = "strict"
    ai_act_ref: str | None = None


class PolicyDocument(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    version: int
    status: Literal["active", "draft", "archived"]
    rules: list[PolicyRule]
    created_by: str | None = None
    updated_at: str | None = None
    content_hash: str | None = None


class PolicyCreate(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    status: Literal["active", "draft", "archived"] = "draft"
    rules: list[PolicyRule]
    created_by: str | None = None


class PolicyUpdate(BaseModel):
    status: Literal["active", "draft", "archived"]
    rules: list[PolicyRule]
    created_by: str | None = None


def get_storage(request: Request) -> StorageBackend:
    return request.app.state.storage


def _read_manifest(storage: StorageBackend) -> tuple[dict, str | None]:
    """Read manifest. Returns (manifest, etag) where:
    - etag is None: manifest does not exist (use expected_etag='*' for create-only CAS)
    - etag is str: manifest exists with that etag (use expected_etag=etag for conditional CAS)
    
    Never confuse falsy etag from backend with sentinel. Preserve etag as-is.
    """
    try:
        blob = storage.get("policies/manifest.json")
        return json.loads(blob.data.decode("utf-8")), blob.metadata.etag
    except BlobNotFoundError:
        return {"policies": {}}, None


def _write_content_addressed_blob(storage: StorageBackend, policy_id: str, content_hash: str, yaml_content: str) -> None:
    """Write policy blob to immutable content-addressed key. Safe for concurrent writes (same hash = idempotent)."""
    blob_key = f"policies/{policy_id}/{content_hash}.yaml"
    storage.put(blob_key, yaml_content.encode("utf-8"), content_type="application/x-yaml")


def _write_manifest(storage: StorageBackend, manifest: dict, expected_etag: str) -> None:
    data = json.dumps(manifest, indent=2).encode("utf-8")
    storage.put("policies/manifest.json", data, content_type="application/json", expected_etag=expected_etag)


def _compute_yaml_hash(yaml_content: str) -> str:
    return "sha256-" + hashlib.sha256(yaml_content.encode("utf-8")).hexdigest()


@router.get("")
def list_policies(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    storage: StorageBackend = Depends(get_storage)
) -> dict:
    manifest, _ = _read_manifest(storage)
    
    result = []
    # Sort by policy ID for deterministic pagination
    policies_items = sorted(manifest.get("policies", {}).items(), key=lambda x: x[0])
    for pid, meta in policies_items[skip : skip + limit]:
        latest_ver = meta.get("latest_version", 1)
        content_hash = meta.get("versions", {}).get(str(latest_ver))
        if not content_hash:
            logger.warning(f"Missing content_hash for policy {pid} v{latest_ver}")
            continue
        
        try:
            blob = storage.get(f"policies/{pid}/{content_hash}.yaml")
            doc = yaml.safe_load(blob.data.decode("utf-8"))
            result.append(doc)
        except BlobNotFoundError:
            logger.warning(f"Orphaned reference: policy {pid} v{latest_ver} -> {content_hash}")
            continue
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse policy {pid} v{latest_ver}: {e}")
        except Exception:
            logger.exception(f"Unexpected error loading policy {pid} v{latest_ver}")
            continue
    return {"items": result, "total": len(policies_items), "skip": skip, "limit": limit}


@router.get("/bundle")
def get_bundle(request: Request, storage: StorageBackend = Depends(get_storage)) -> Response:
    manifest, _ = _read_manifest(storage)
    
    policies_meta = manifest.get("policies", {})
    # Active policies and their content hashes uniquely identify the bundle content
    active_policies = {}
    dangling_pointers = []
    
    for pid, meta in policies_meta.items():
        if meta.get("status") == "active":
            active_ver = meta.get("active_version")
            if active_ver:
                content_hash = meta.get("versions", {}).get(str(active_ver))
                if content_hash:
                    active_policies[pid] = content_hash
                else:
                    logger.warning(f"Missing content_hash for active policy {pid} v{active_ver}")
    
    # Calculate a deterministic hash of the active configuration
    manifest_snapshot = json.dumps(active_policies, sort_keys=True)
    bundle_hash = _compute_yaml_hash(manifest_snapshot)
    etag = f'"{bundle_hash}"'
    
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    # Build the bundle by merging all active policies
    all_rules = []
    
    # Sort active policies by ID for deterministic rules order
    sorted_pids = sorted(active_policies.keys())
    
    for pid in sorted_pids:
        content_hash = active_policies[pid]
        try:
            blob = storage.get(f"policies/{pid}/{content_hash}.yaml")
            doc = yaml.safe_load(blob.data.decode("utf-8"))
            all_rules.extend(doc.get("rules", []))
        except BlobNotFoundError:
            logger.error(f"Missing blob for active policy {pid}: {content_hash}")
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse active policy {pid}: {e}")
        except Exception:
            logger.exception(f"Unexpected error loading active policy {pid}")

    bundle_doc = {
        "id": "bundle_active",
        "version": 1,
        "status": "active",
        "rules": all_rules,
    }
    
    yaml_content = yaml.safe_dump(bundle_doc, sort_keys=False)
    headers = {"ETag": etag}
    return Response(content=yaml_content, media_type="application/x-yaml", headers=headers)


@router.get("/{policy_id}")
def get_active_policy(policy_id: str, storage: StorageBackend = Depends(get_storage)) -> dict:
    manifest, _ = _read_manifest(storage)
    meta = manifest.get("policies", {}).get(policy_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    active_ver = meta.get("active_version")
    if not active_ver:
        raise HTTPException(status_code=404, detail="Policy not found or archived")
    
    content_hash = meta.get("versions", {}).get(str(active_ver))
    if not content_hash:
        raise HTTPException(status_code=500, detail="Manifest inconsistency: missing content_hash")
        
    try:
        blob = storage.get(f"policies/{policy_id}/{content_hash}.yaml")
        return yaml.safe_load(blob.data.decode("utf-8"))
    except BlobNotFoundError:
        raise HTTPException(status_code=404, detail="Policy version not found") from None
    except Exception:
        logger.exception(f"Unexpected error reading active policy {policy_id}")
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/{policy_id}/v{version}")
def get_policy_version(policy_id: str, version: int, storage: StorageBackend = Depends(get_storage)) -> dict:
    manifest, _ = _read_manifest(storage)
    meta = manifest.get("policies", {}).get(policy_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    content_hash = meta.get("versions", {}).get(str(version))
    if not content_hash:
        raise HTTPException(status_code=404, detail="Policy version not found")
    
    try:
        blob = storage.get(f"policies/{policy_id}/{content_hash}.yaml")
        return yaml.safe_load(blob.data.decode("utf-8"))
    except BlobNotFoundError:
        raise HTTPException(status_code=404, detail="Policy version not found") from None
    except Exception:
        logger.exception(f"Unexpected error reading policy {policy_id} v{version}")
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("", status_code=201)
def create_policy(policy_in: PolicyCreate, storage: StorageBackend = Depends(get_storage)) -> dict:
    # Create initial document
    doc = {
        "id": policy_in.id,
        "version": 1,
        "status": policy_in.status,
        "rules": [r.model_dump() for r in policy_in.rules],
        "created_by": policy_in.created_by,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    yaml_content = yaml.safe_dump(doc, sort_keys=False)
    content_hash = _compute_yaml_hash(yaml_content)
    doc["content_hash"] = content_hash

    # === ORDER CRITICAL: Blob first, manifest second ===
    # STEP 1 (DATA): Write immutable blob at content-addressed key
    #   Safe: concurrent writes with same content are idempotent (same hash)
    _write_content_addressed_blob(storage, policy_in.id, content_hash, yaml_content)

    # STEP 2 (POINTER): Update manifest with CAS loop
    #   This is the atomic commit point. Crash after STEP 1 = orphaned blob (safe)
    #   Crash before STEP 2 completes = policy not visible (safe)
    for _ in range(5):
        manifest, etag = _read_manifest(storage)
        if policy_in.id in manifest.get("policies", {}):
            raise HTTPException(status_code=400, detail="Policy already exists")

        if "policies" not in manifest:
            manifest["policies"] = {}
            
        manifest["policies"][policy_in.id] = {
            "versions": {"1": content_hash},
            "latest_version": 1,
            "active_version": 1 if policy_in.status == "active" else None,
            "status": policy_in.status
        }
        
        # Convert etag semantics: None (no manifest) -> "*" (create-only CAS)
        expected_etag = "*" if etag is None else etag
        try:
            _write_manifest(storage, manifest, expected_etag=expected_etag)
            break
        except ConditionNotMetError:
            continue
    else:
        raise HTTPException(status_code=409, detail="Concurrent modification error")

    return doc


@router.put("/{policy_id}")
def update_policy(policy_id: str, policy_in: PolicyUpdate, storage: StorageBackend = Depends(get_storage)) -> dict:
    # Base document without version (will be filled inside CAS loop)
    doc_base = {
        "id": policy_id,
        "status": policy_in.status,
        "rules": [r.model_dump() for r in policy_in.rules],
        "created_by": policy_in.created_by,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    # === CRITICAL ORDER: Blob-first is mandatory for safety ===
    # 
    # STEP 1 (DATA): Write immutable blob at content-addressed key
    #   - Must include correct version number (reserved inside CAS loop)
    #   - Safe: concurrent writes with same content are idempotent (same hash)
    #   - If this succeeds and manifest CAS fails: orphaned blob only (safe)
    # 
    # STEP 2 (POINTER): Reserve version number and update manifest with CAS loop
    #   - Atomic commit point: version <-> content_hash binding becomes visible
    #   - Crash after STEP 1 completes = orphaned blob (harmless)
    #   - Crash during STEP 2 = manifest not updated (policy unchanged, safe)
    #
    for attempt in range(5):
        manifest, etag = _read_manifest(storage)
        meta = manifest.get("policies", {}).get(policy_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Policy not found")

        # Reserve next version number BEFORE serializing blob
        latest_version_in_manifest = meta.get("latest_version", 1)
        expected_new_version = latest_version_in_manifest + 1

        # Generate complete document with correct version
        doc = dict(doc_base)
        doc["version"] = expected_new_version
        yaml_content = yaml.safe_dump(doc, sort_keys=False)
        content_hash = _compute_yaml_hash(yaml_content)
        doc["content_hash"] = content_hash

        # STEP 1: Write immutable blob with correct version embedded
        _write_content_addressed_blob(storage, policy_id, content_hash, yaml_content)

        # STEP 2: Update manifest with version -> content_hash mapping
        if "versions" not in meta:
            meta["versions"] = {}
        meta["versions"][str(expected_new_version)] = content_hash
        meta["latest_version"] = expected_new_version
        meta["status"] = policy_in.status
        if policy_in.status == "active":
            meta["active_version"] = expected_new_version
        else:
            meta["active_version"] = None

        # Convert etag semantics: None (no manifest) -> "*" (create-only CAS)
        expected_etag = "*" if etag is None else etag
        try:
            _write_manifest(storage, manifest, expected_etag=expected_etag)
            return doc
        except ConditionNotMetError:
            continue
    
    raise HTTPException(status_code=409, detail="Concurrent modification error")


@router.delete("/{policy_id}")
def archive_policy(policy_id: str, storage: StorageBackend = Depends(get_storage)) -> dict:
    # Check if already archived and read latest version for potential early return
    manifest, _ = _read_manifest(storage)
    meta = manifest.get("policies", {}).get(policy_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Policy not found")

    if meta.get("status") == "archived":
        # Already archived, return the current archived version
        latest_ver = meta.get("latest_version", 1)
        content_hash = meta.get("versions", {}).get(str(latest_ver))
        if not content_hash:
            raise HTTPException(status_code=500, detail="Manifest inconsistency")
        try:
            blob = storage.get(f"policies/{policy_id}/{content_hash}.yaml")
            return yaml.safe_load(blob.data.decode("utf-8"))
        except BlobNotFoundError:
            raise HTTPException(status_code=404, detail="Policy version not found") from None

    # If a previous update left a dangling pointer, archive would cascade to 404.
    latest_ver = meta.get("latest_version", 1)
    prev_content_hash = meta.get("versions", {}).get(str(latest_ver))
    if not prev_content_hash:
        raise HTTPException(status_code=500, detail="Manifest inconsistency: latest version has no content_hash")
    
    try:
        blob = storage.get(f"policies/{policy_id}/{prev_content_hash}.yaml")
        last_doc = yaml.safe_load(blob.data.decode("utf-8"))
    except BlobNotFoundError:
        raise HTTPException(status_code=404, detail="Policy version not found") from None
    except Exception:
        logger.exception("Failed to read previous policy version during archive")
        raise HTTPException(status_code=500, detail="Failed to read previous policy version") from None

    # Base for archived document
    doc_base = {
        "id": policy_id,
        "status": "archived",
        "rules": last_doc.get("rules", []),
        "created_by": last_doc.get("created_by"),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    for attempt in range(5):
        manifest, etag = _read_manifest(storage)
        meta = manifest.get("policies", {}).get(policy_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Policy not found")

        # Reserve next version number
        latest_version_in_manifest = meta.get("latest_version", 1)
        expected_new_version = latest_version_in_manifest + 1

        # Generate complete document with expected version
        doc = dict(doc_base)
        doc["version"] = expected_new_version
        yaml_content = yaml.safe_dump(doc, sort_keys=False)
        content_hash = _compute_yaml_hash(yaml_content)
        doc["content_hash"] = content_hash

        # Write immutable blob
        _write_content_addressed_blob(storage, policy_id, content_hash, yaml_content)

        if "versions" not in meta:
            meta["versions"] = {}
        meta["versions"][str(expected_new_version)] = content_hash
        meta["latest_version"] = expected_new_version
        meta["status"] = "archived"
        meta["active_version"] = None
        
        expected_etag = "*" if etag is None else etag
        try:
            _write_manifest(storage, manifest, expected_etag=expected_etag)
            return doc
        except ConditionNotMetError:
            continue
    
    raise HTTPException(status_code=409, detail="Concurrent modification error")