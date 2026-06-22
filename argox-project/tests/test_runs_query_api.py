"""Tests for the COL-13 run Query API: run lists, detail and span-to-run join."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from argox_collector.app import create_app
from argox_collector.index.base import RunRecord
from argox_collector.index.duckdb import DuckDBTraceIndex
from argox_collector.settings import CollectorSettings
from fastapi.testclient import TestClient

NOW = datetime.now(timezone.utc)


def _runs() -> list[RunRecord]:
    """Three runs across two agents and both success outcomes."""
    return [
        RunRecord(
            run_id="r1",
            trace_id="t1",
            agent_name="agent-a",
            agent_version="1.0",
            timestamp="2026-06-22T10:00:00Z",
            success=True,
            total_input_tokens=100,
            total_output_tokens=20,
            duration_seconds=1.5,
            cost_usd=0.05,
            blob_path="runs/2026-06-22/r1.json",
            model="gpt-4o",
        ),
        RunRecord(
            run_id="r2",
            trace_id="t2",
            agent_name="agent-b",
            agent_version="2.0",
            timestamp="2026-06-22T09:00:00Z",
            success=False,
            blob_path="runs/2026-06-22/r2.json",
        ),
        RunRecord(
            run_id="r3",
            trace_id="t3",
            agent_name="agent-a",
            agent_version="1.0",
            timestamp="2026-06-22T08:00:00Z",
            success=True,
            blob_path="runs/2026-06-22/r3.json",
        ),
    ]


def _set_ingested_at(index: DuckDBTraceIndex, run_id: str, when: datetime) -> None:
    """Force a run's ingest time so window filtering and ordering are testable.

    ``insert_run`` stamps ``ingested_at`` with the wall clock, which would put
    every test run inside the same instant; overriding it lets the tests assert
    the ingest-time sort and the half-open ``[from, to)`` window.
    """
    naive = when.astimezone(timezone.utc).replace(tzinfo=None)
    with index._lock:
        index._conn.execute(
            "UPDATE runs SET ingested_at = ? WHERE run_id = ?", (naive, run_id)
        )


@pytest.fixture
def index(tmp_path: Path) -> DuckDBTraceIndex:
    idx = DuckDBTraceIndex(tmp_path / "test.duckdb")
    for record in _runs():
        idx.insert_run(record)
    # r1 newest, r3 oldest, each an hour apart.
    _set_ingested_at(idx, "r1", NOW - timedelta(minutes=5))
    _set_ingested_at(idx, "r2", NOW - timedelta(hours=1))
    _set_ingested_at(idx, "r3", NOW - timedelta(hours=2))
    return idx


@pytest.fixture
def client(index: DuckDBTraceIndex, tmp_path: Path) -> TestClient:
    settings = CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "unused.duckdb",
    )
    app = create_app(settings, index=index)
    # Seed the blob store with the immutable run records the detail endpoint
    # reads back byte-for-byte. r3's blob is deliberately omitted to exercise
    # the index-row fallback.
    storage = app.state.storage
    storage.put(
        "runs/2026-06-22/r1.json",
        json.dumps({"run_id": "r1", "prompt": "hi", "final_output": "yo"}).encode(),
        content_type="application/json",
    )
    storage.put(
        "runs/2026-06-22/r2.json",
        json.dumps({"run_id": "r2", "prompt": "fail"}).encode(),
        content_type="application/json",
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Index layer
# ---------------------------------------------------------------------------


def test_index_list_runs_sorts_newest_first(index: DuckDBTraceIndex) -> None:
    runs, total = index.list_runs()
    assert total == 3
    assert [r.run_id for r in runs] == ["r1", "r2", "r3"]


def test_index_list_runs_paginates(index: DuckDBTraceIndex) -> None:
    runs, total = index.list_runs(skip=1, limit=1)
    assert total == 3
    assert [r.run_id for r in runs] == ["r2"]


def test_index_list_runs_filters_agent(index: DuckDBTraceIndex) -> None:
    runs, total = index.list_runs(agent_name="agent-a")
    assert total == 2
    assert [r.run_id for r in runs] == ["r1", "r3"]


def test_index_list_runs_filters_success(index: DuckDBTraceIndex) -> None:
    runs, total = index.list_runs(success=False)
    assert total == 1
    assert runs[0].run_id == "r2"


def test_index_list_runs_filters_window(index: DuckDBTraceIndex) -> None:
    # [start, end): only r1 (5m ago); r2 (1h ago) and r3 (2h ago) fall before.
    runs, total = index.list_runs(
        start=NOW - timedelta(minutes=30), end=NOW
    )
    assert total == 1
    assert runs[0].run_id == "r1"


def test_index_list_runs_empty(tmp_path: Path) -> None:
    idx = DuckDBTraceIndex(tmp_path / "empty.duckdb")
    assert idx.list_runs() == ([], 0)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


def test_list_runs_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/runs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert [item["run_id"] for item in data["items"]] == ["r1", "r2", "r3"]
    # Rows are lightweight: no prompt/final_output payload.
    assert "prompt" not in data["items"][0]
    assert data["items"][0]["cost_usd"] == pytest.approx(0.05)


def test_list_runs_endpoint_paginates(client: TestClient) -> None:
    response = client.get("/api/v1/runs", params={"page": 2, "page_size": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["run_id"] for item in data["items"]] == ["r2"]


def test_list_runs_endpoint_filters(client: TestClient) -> None:
    response = client.get("/api/v1/runs", params={"agent": "agent-a", "success": True})
    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["items"]] == ["r1", "r3"]


def test_list_runs_endpoint_filters_window(client: TestClient) -> None:
    response = client.get(
        "/api/v1/runs",
        params={"from": (NOW - timedelta(minutes=30)).isoformat(), "to": NOW.isoformat()},
    )
    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["items"]] == ["r1"]


def test_list_runs_endpoint_validates_pagination(client: TestClient) -> None:
    assert client.get("/api/v1/runs", params={"page": 0}).status_code == 422
    assert client.get("/api/v1/runs", params={"page_size": 0}).status_code == 422
    assert client.get("/api/v1/runs", params={"page_size": 1001}).status_code == 422


def test_list_runs_endpoint_rejects_inverted_window(client: TestClient) -> None:
    response = client.get(
        "/api/v1/runs",
        params={"from": NOW.isoformat(), "to": (NOW - timedelta(hours=1)).isoformat()},
    )
    assert response.status_code == 422


def test_get_run_endpoint_returns_blob_content(client: TestClient) -> None:
    response = client.get("/api/v1/runs/r1")
    assert response.status_code == 200
    data = response.json()
    # Blob content (prompt/final_output) is preserved...
    assert data["prompt"] == "hi"
    assert data["final_output"] == "yo"
    # ...and the collector-derived cost_usd is overlaid from the index so the
    # detail view matches the list view (the blob itself has no cost_usd).
    assert data["cost_usd"] == pytest.approx(0.05)
    assert response.headers["x-content-type-options"] == "nosniff"


def test_get_run_endpoint_detail_cost_matches_list(client: TestClient) -> None:
    # The list (index) and detail (blob) must report the same cost for a run.
    listed = next(
        item
        for item in client.get("/api/v1/runs").json()["items"]
        if item["run_id"] == "r1"
    )
    detail = client.get("/api/v1/runs/r1").json()
    assert detail["cost_usd"] == listed["cost_usd"]


def test_get_run_endpoint_falls_back_on_corrupt_blob(client: TestClient) -> None:
    # A blob that is valid bytes but not a JSON object must not be served as
    # JSON; the detail degrades to the index-row projection.
    client.app.state.storage.put(
        "runs/2026-06-22/r1.json", b"not json", content_type="application/json"
    )
    data = client.get("/api/v1/runs/r1").json()
    assert data["run_id"] == "r1"
    assert data["tokens"] == {"input": 100, "output": 20}


def test_get_run_endpoint_falls_back_to_index_row(client: TestClient) -> None:
    # r3 has an index row but no blob: the detail degrades to the row.
    response = client.get("/api/v1/runs/r3")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "r3"
    assert data["agent_name"] == "agent-a"
    assert data["tokens"] == {"input": 0, "output": 0}


def test_get_run_endpoint_404(client: TestClient) -> None:
    assert client.get("/api/v1/runs/missing").status_code == 404


def test_get_run_by_trace_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/runs/by-trace/t2")
    assert response.status_code == 200
    assert response.json()["run_id"] == "r2"


def test_get_run_by_trace_endpoint_404(client: TestClient) -> None:
    assert client.get("/api/v1/runs/by-trace/no-such-trace").status_code == 404
