"""Seed (or update) the local Collector's demo policy from ``demo_policy.yaml``.

The Collector's policy API takes JSON, not raw YAML, so this reads the YAML,
converts each rule to the ``PolicyCreate`` shape, and POSTs it. If the policy id
already exists (409) it issues a ``PUT`` to create a new active version, so
re-running is idempotent. Called by ``run.sh`` after the API key is minted.

Usage:
  python seed_policy.py <dashboard_url> <api_key>
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: seed_policy.py <dashboard_url> <api_key>", file=sys.stderr)
        return 2
    base = sys.argv[1].rstrip("/")
    api_key = sys.argv[2]

    doc = yaml.safe_load((HERE / "demo_policy.yaml").read_text(encoding="utf-8"))
    policy_id = doc["id"]
    rules = doc["rules"]
    headers = {"Authorization": f"Bearer {api_key}"}

    create_body = {
        "id": policy_id,
        "status": "active",
        "created_by": doc.get("created_by", "argox-local-demo"),
        "rules": rules,
    }
    with httpx.Client(timeout=10.0, headers=headers) as client:
        resp = client.post(f"{base}/api/v1/policies", json=create_body)
        if resp.status_code == 201:
            print(f"  created policy {policy_id!r} (v1, active)")
            return 0
        if resp.status_code == 409:
            update_body = {
                "status": "active",
                "created_by": create_body["created_by"],
                "rules": rules,
            }
            resp = client.put(f"{base}/api/v1/policies/{policy_id}", json=update_body)
            resp.raise_for_status()
            version = resp.json().get("version")
            print(f"  updated policy {policy_id!r} (v{version}, active)")
            return 0
        resp.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
