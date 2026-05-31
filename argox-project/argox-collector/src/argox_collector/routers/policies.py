import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from argox_collector.storage import StorageBackend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


class RuleCondition(BaseModel):
    metric: str
    operator: str
    threshold: Any


class PolicyRule(BaseModel):
    id: str
    trigger: str
    condition: RuleCondition
    action: str
    enforcement: str = "strict"
    ai_act_ref: Optional[str] = None


class PolicyDocument(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    version: int
    status: str
    rules: List[PolicyRule]
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    content_hash: Optional[str] = None


class PolicyCreate(BaseModel):
    id: str
    status: str = "draft"
    rules: List[PolicyRule]
    created_by: Optional[str] = None


class PolicyUpdate(BaseModel):
    status: str
    rules: List[PolicyRule]
    created_by: Optional[str] = None


def get_storage(request: Request) -> StorageBackend:
    return request.app.state.storage


def _read_manifest(storage: StorageBackend) -> dict:
    try:
        blob = storage.get("policies/manifest.json")
        return json.loads(blob.data.decode("utf-8"))
    except Exception:
        return {"policies": {}, "bundle_hash": ""}


def _write_manifest(storage: StorageBackend, manifest: dict) -> None:
    data = json.dumps(manifest, indent=2).encode("utf-8")
    storage.put("policies/manifest.json", data, content_type="application/json")


def _compute_yaml_hash(yaml_content: str) -> str:
    return "sha256:" + hashlib.sha256(yaml_content.encode("utf-8")).hexdigest()


@router.get("")
async def list_policies(skip: int = 0, limit: int = 50, storage: StorageBackend = Depends(get_storage)):
    manifest = _read_manifest(storage)
    result = []
    policies_items = list(manifest.get("policies", {}).items())
    for pid, meta in policies_items[skip : skip + limit]:
        latest_ver = meta.get("latest_version", 1)
        try:
            blob = storage.get(f"policies/{pid}/v{latest_ver}.yaml")
            doc = yaml.safe_load(blob.data.decode("utf-8"))
            result.append(doc)
        except Exception:
            continue
    return {"items": result, "total": len(policies_items), "skip": skip, "limit": limit}


@router.get("/bundle")
async def get_bundle(request: Request, response: Response, storage: StorageBackend = Depends(get_storage)):
    manifest = _read_manifest(storage)
    bundle_hash = manifest.get("bundle_hash", "")
    
    if bundle_hash:
        etag = f'"{bundle_hash}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        response.headers["ETag"] = etag

    # Build the bundle by merging all active policies
    all_rules = []
    policies_meta = manifest.get("policies", {})
    
    for pid, meta in policies_meta.items():
        if meta.get("status") == "active":
            active_ver = meta.get("active_version", 1)
            try:
                blob = storage.get(f"policies/{pid}/v{active_ver}.yaml")
                doc = yaml.safe_load(blob.data.decode("utf-8"))
                all_rules.extend(doc.get("rules", []))
            except Exception as e:
                logger.error(f"Failed to load active policy {pid} v{active_ver}: {e}")

    bundle_doc = {
        "id": "bundle_active",
        "version": 1,
        "status": "active",
        "rules": all_rules,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    yaml_content = yaml.dump(bundle_doc, sort_keys=False)
    
    # Update hash if needed
    current_hash = _compute_yaml_hash(yaml_content)
    if current_hash != bundle_hash:
        manifest["bundle_hash"] = current_hash
        _write_manifest(storage, manifest)

    headers = {"ETag": f'"{current_hash}"'}
    return Response(content=yaml_content, media_type="application/x-yaml", headers=headers)


@router.get("/{policy_id}")
async def get_active_policy(policy_id: str, storage: StorageBackend = Depends(get_storage)):
    manifest = _read_manifest(storage)
    meta = manifest.get("policies", {}).get(policy_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    active_ver = meta.get("active_version")
    if not active_ver:
        active_ver = meta.get("latest_version")
        
    try:
        blob = storage.get(f"policies/{policy_id}/v{active_ver}.yaml")
        return yaml.safe_load(blob.data.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=404, detail="Policy version not found")


@router.get("/{policy_id}/v{version}")
async def get_policy_version(policy_id: str, version: int, storage: StorageBackend = Depends(get_storage)):
    try:
        blob = storage.get(f"policies/{policy_id}/v{version}.yaml")
        return yaml.safe_load(blob.data.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=404, detail="Policy version not found")


@router.post("")
async def create_policy(policy_in: PolicyCreate, storage: StorageBackend = Depends(get_storage)):
    manifest = _read_manifest(storage)
    if policy_in.id in manifest.get("policies", {}):
        raise HTTPException(status_code=400, detail="Policy already exists")

    doc = {
        "id": policy_in.id,
        "version": 1,
        "status": policy_in.status,
        "rules": [r.model_dump() for r in policy_in.rules],
        "created_by": policy_in.created_by,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    yaml_content = yaml.dump(doc, sort_keys=False)
    doc["content_hash"] = _compute_yaml_hash(yaml_content)
    
    # Re-dump to include content_hash
    yaml_content = yaml.dump(doc, sort_keys=False)

    storage.put(f"policies/{policy_in.id}/v1.yaml", yaml_content.encode("utf-8"), content_type="application/x-yaml")

    if "policies" not in manifest:
        manifest["policies"] = {}
        
    manifest["policies"][policy_in.id] = {
        "latest_version": 1,
        "active_version": 1 if policy_in.status == "active" else None,
        "status": policy_in.status
    }
    
    # Invalidate bundle hash
    manifest["bundle_hash"] = ""
    _write_manifest(storage, manifest)

    return doc


@router.put("/{policy_id}")
async def update_policy(policy_id: str, policy_in: PolicyUpdate, storage: StorageBackend = Depends(get_storage)):
    manifest = _read_manifest(storage)
    meta = manifest.get("policies", {}).get(policy_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Policy not found")

    new_version = meta["latest_version"] + 1

    doc = {
        "id": policy_id,
        "version": new_version,
        "status": policy_in.status,
        "rules": [r.model_dump() for r in policy_in.rules],
        "created_by": policy_in.created_by,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    yaml_content = yaml.dump(doc, sort_keys=False)
    doc["content_hash"] = _compute_yaml_hash(yaml_content)
    
    yaml_content = yaml.dump(doc, sort_keys=False)

    storage.put(f"policies/{policy_id}/v{new_version}.yaml", yaml_content.encode("utf-8"), content_type="application/x-yaml")

    meta["latest_version"] = new_version
    meta["status"] = policy_in.status
    if policy_in.status == "active":
        meta["active_version"] = new_version

    # Invalidate bundle hash
    manifest["bundle_hash"] = ""
    _write_manifest(storage, manifest)

    return doc


@router.delete("/{policy_id}")
async def archive_policy(policy_id: str, storage: StorageBackend = Depends(get_storage)):
    manifest = _read_manifest(storage)
    meta = manifest.get("policies", {}).get(policy_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Policy not found")

    if meta["status"] == "archived":
        return {"status": "archived"}

    new_version = meta["latest_version"] + 1
    
    # Read the latest to copy rules
    try:
        blob = storage.get(f"policies/{policy_id}/v{meta['latest_version']}.yaml")
        last_doc = yaml.safe_load(blob.data.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read latest policy version")

    doc = {
        "id": policy_id,
        "version": new_version,
        "status": "archived",
        "rules": last_doc.get("rules", []),
        "created_by": last_doc.get("created_by"),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    yaml_content = yaml.dump(doc, sort_keys=False)
    doc["content_hash"] = _compute_yaml_hash(yaml_content)
    yaml_content = yaml.dump(doc, sort_keys=False)

    storage.put(f"policies/{policy_id}/v{new_version}.yaml", yaml_content.encode("utf-8"), content_type="application/x-yaml")

    meta["latest_version"] = new_version
    meta["status"] = "archived"
    
    # Invalidate bundle hash
    manifest["bundle_hash"] = ""
    _write_manifest(storage, manifest)

    return doc
