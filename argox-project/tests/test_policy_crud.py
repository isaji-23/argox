import pytest
from fastapi.testclient import TestClient

from argox_collector.app import create_app
from argox_collector.settings import CollectorSettings
from argox_collector.storage.local import LocalStorageBackend


@pytest.fixture
def memory_storage(tmp_path):
    return LocalStorageBackend(tmp_path)


@pytest.fixture
def client(memory_storage):
    settings = CollectorSettings()
    app = create_app(settings=settings, storage=memory_storage)
    return TestClient(app)


def test_create_and_get_policy(client):
    policy_data = {
        "id": "test_pol_1",
        "status": "active",
        "rules": [
            {
                "id": "rule_1",
                "trigger": "on_input",
                "condition": {
                    "metric": "prompt",
                    "operator": "contains",
                    "threshold": "secret"
                },
                "action": "block"
            }
        ]
    }
    
    # Create policy
    resp = client.post("/api/v1/policies", json=policy_data)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["id"] == "test_pol_1"
    assert data["version"] == 1
    assert "content_hash" in data

    # Get active policy
    resp = client.get("/api/v1/policies/test_pol_1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "test_pol_1"

    # Get bundle
    resp = client.get("/api/v1/policies/bundle")
    assert resp.status_code == 200
    assert "id: bundle_active" in resp.text
    assert "rule_1" in resp.text
    
    etag = resp.headers.get("ETag")
    assert etag
    
    # Test 304 Not Modified
    resp_304 = client.get("/api/v1/policies/bundle", headers={"If-None-Match": etag})
    assert resp_304.status_code == 304
    assert resp_304.headers.get("ETag") == etag


def test_bundle_etag_stability(client):
    policy_data = {
        "id": "test_pol_stable",
        "status": "active",
        "rules": []
    }
    client.post("/api/v1/policies", json=policy_data)
    
    # Get initial bundle
    resp1 = client.get("/api/v1/policies/bundle")
    assert resp1.status_code == 200
    etag1 = resp1.headers.get("ETag")
    
    # Get bundle again without ETag
    resp2 = client.get("/api/v1/policies/bundle")
    assert resp2.status_code == 200
    etag2 = resp2.headers.get("ETag")
    
    # ETag should be identical since no policies changed
    assert etag1 == etag2


def test_update_and_archive_policy(client):
    policy_data = {
        "id": "test_pol_2",
        "status": "draft",
        "rules": []
    }
    resp = client.post("/api/v1/policies", json=policy_data)
    assert resp.status_code == 201
    
    # Update policy
    update_data = {
        "status": "active",
        "rules": [
            {
                "id": "rule_2",
                "trigger": "on_output",
                "condition": {
                    "metric": "text",
                    "operator": "eq",
                    "threshold": "bad"
                },
                "action": "alert"
            }
        ]
    }
    resp = client.put("/api/v1/policies/test_pol_2", json=update_data)
    assert resp.status_code == 200
    assert resp.json()["version"] == 2
    
    # Archive policy
    resp = client.delete("/api/v1/policies/test_pol_2")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"
    assert resp.json()["version"] == 3

    # Check it's not in the bundle
    resp = client.get("/api/v1/policies/bundle")
    assert "rule_2" not in resp.text


def test_invalid_policy_id(client):
    # Invalid character in policy ID
    invalid_data = {
        "id": "bad/id",
        "status": "draft",
        "rules": []
    }
    resp = client.post("/api/v1/policies", json=invalid_data)
    assert resp.status_code in (400, 422)
    
    resp = client.get("/api/v1/policies/bad/id")
    # Due to routing /bad/id might not even match /policies/{policy_id} perfectly or matches as "bad", but let's test specific characters handled by backend
    
    invalid_data_2 = {
        "id": "bad..id",
        "status": "draft",
        "rules": []
    }
    resp2 = client.post("/api/v1/policies", json=invalid_data_2)
    assert resp2.status_code in (400, 422)
