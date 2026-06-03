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
    try:
        blob = storage.get("policies/manifest.json")
        return json.loads(blob.data.decode("utf-8")), blob.metadata.etag
    except BlobNotFoundError:
        return {"policies": {}}, None


def _write_manifest(storage: StorageBackend, manifest: dict, expected_etag: str | None) -> None:
    data = json.dumps(manifest, indent=2).encode("utf-8")
    storage.put("policies/manifest.json", data, content_type="application/json", expected_etag=expected_etag)


def _compute_yaml_hash(yaml_content: str) -> str:
    return "sha256:" + hashlib.sha256(yaml_content.encode("utf-8")).hexdigest()


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
        try:
            blob = storage.get(f"policies/{pid}/v{latest_ver}.yaml")
            doc = yaml.safe_load(blob.data.decode("utf-8"))
            result.append(doc)
        except BlobNotFoundError:
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
    # Active policies and their versions uniquely identify the bundle content
    active_policies = {
        pid: meta["active_version"]
        for pid, meta in policies_meta.items()
        if meta.get("status") == "active"
    }
    
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
        active_ver = active_policies[pid]
        try:
            blob = storage.get(f"policies/{pid}/v{active_ver}.yaml")
            doc = yaml.safe_load(blob.data.decode("utf-8"))
            all_rules.extend(doc.get("rules", []))
        except BlobNotFoundError:
            logger.error(f"Missing blob for active policy {pid} v{active_ver}")
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse active policy {pid} v{active_ver}: {e}")
        except Exception:
            logger.exception(f"Unexpected error loading active policy {pid} v{active_ver}")

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
        
    try:
        blob = storage.get(f"policies/{policy_id}/v{active_ver}.yaml")
        return yaml.safe_load(blob.data.decode("utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid policy ID") from None
    except BlobNotFoundError:
        raise HTTPException(status_code=404, detail="Policy version not found") from None
    except Exception:
        logger.exception(f"Unexpected error reading active policy {policy_id}")
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.get("/{policy_id}/v{version}")
def get_policy_version(policy_id: str, version: int, storage: StorageBackend = Depends(get_storage)) -> dict:
    try:
        blob = storage.get(f"policies/{policy_id}/v{version}.yaml")
        return yaml.safe_load(blob.data.decode("utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid policy ID") from None
    except BlobNotFoundError:
        raise HTTPException(status_code=404, detail="Policy version not found") from None
    except Exception:
        logger.exception(f"Unexpected error reading policy {policy_id} v{version}")
        raise HTTPException(status_code=500, detail="Internal server error") from None


@router.post("", status_code=201)
def create_policy(policy_in: PolicyCreate, storage: StorageBackend = Depends(get_storage)) -> dict:
    doc = {
        "id": policy_in.id,
        "version": 1,
        "status": policy_in.status,
        "rules": [r.model_dump() for r in policy_in.rules],
        "created_by": policy_in.created_by,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    yaml_content = yaml.safe_dump(doc, sort_keys=False)
    doc["content_hash"] = _compute_yaml_hash(yaml_content)
    
    # Re-dump to include content_hash
    yaml_content = yaml.safe_dump(doc, sort_keys=False)

    try:
        storage.put(f"policies/{policy_in.id}/v1.yaml", yaml_content.encode("utf-8"), content_type="application/x-yaml")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid policy ID") from None

    for _ in range(5):
        manifest, etag = _read_manifest(storage)
        if policy_in.id in manifest.get("policies", {}):
            raise HTTPException(status_code=400, detail="Policy already exists")

        if "policies" not in manifest:
            manifest["policies"] = {}
            
        manifest["policies"][policy_in.id] = {
            "latest_version": 1,
            "active_version": 1 if policy_in.status == "active" else None,
            "status": policy_in.status
        }
        
        try:
            _write_manifest(storage, manifest, expected_etag=etag)
            return doc
        except ConditionNotMetError:
            continue
            
    raise HTTPException(status_code=409, detail="Concurrent modification error")


@router.put("/{policy_id}")
def update_policy(policy_id: str, policy_in: PolicyUpdate, storage: StorageBackend = Depends(get_storage)) -> dict:
    for _ in range(5):
        manifest, etag = _read_manifest(storage)
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
        yaml_content = yaml.safe_dump(doc, sort_keys=False)
        doc["content_hash"] = _compute_yaml_hash(yaml_content)
        
        yaml_content = yaml.safe_dump(doc, sort_keys=False)

        try:
            storage.put(f"policies/{policy_id}/v{new_version}.yaml", yaml_content.encode("utf-8"), content_type="application/x-yaml")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid policy ID") from None

        meta["latest_version"] = new_version
        meta["status"] = policy_in.status
        if policy_in.status == "active":
            meta["active_version"] = new_version
        else:
            meta["active_version"] = None

        try:
            _write_manifest(storage, manifest, expected_etag=etag)
            return doc
        except ConditionNotMetError:
            continue
            
    raise HTTPException(status_code=409, detail="Concurrent modification error")


@router.delete("/{policy_id}")
def archive_policy(policy_id: str, storage: StorageBackend = Depends(get_storage)) -> dict:
    for _ in range(5):
        manifest, etag = _read_manifest(storage)
        meta = manifest.get("policies", {}).get(policy_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Policy not found")

        if meta["status"] == "archived":
            try:
                blob = storage.get(f"policies/{policy_id}/v{meta['latest_version']}.yaml")
                return yaml.safe_load(blob.data.decode("utf-8"))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid policy ID") from None
            except BlobNotFoundError:
                raise HTTPException(status_code=404, detail="Policy version not found") from None
            except Exception:
                logger.exception("Failed to read latest policy version during archive")
                raise HTTPException(status_code=500, detail="Failed to read latest policy version") from None

        new_version = meta["latest_version"] + 1
        
        # Read the latest to copy rules
        try:
            blob = storage.get(f"policies/{policy_id}/v{meta['latest_version']}.yaml")
            last_doc = yaml.safe_load(blob.data.decode("utf-8"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid policy ID") from None
        except BlobNotFoundError:
            raise HTTPException(status_code=404, detail="Policy version not found") from None
        except Exception:
            logger.exception("Failed to read latest policy version during archive")
            raise HTTPException(status_code=500, detail="Failed to read latest policy version") from None

        doc = {
            "id": policy_id,
            "version": new_version,
            "status": "archived",
            "rules": last_doc.get("rules", []),
            "created_by": last_doc.get("created_by"),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        yaml_content = yaml.safe_dump(doc, sort_keys=False)
        doc["content_hash"] = _compute_yaml_hash(yaml_content)
        yaml_content = yaml.safe_dump(doc, sort_keys=False)

        try:
            storage.put(f"policies/{policy_id}/v{new_version}.yaml", yaml_content.encode("utf-8"), content_type="application/x-yaml")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid policy ID") from None

        meta["latest_version"] = new_version
        meta["status"] = "archived"
        meta["active_version"] = None
        
        try:
            _write_manifest(storage, manifest, expected_etag=etag)
            return doc
        except ConditionNotMetError:
            continue
            
    raise HTTPException(status_code=409, detail="Concurrent modification error")