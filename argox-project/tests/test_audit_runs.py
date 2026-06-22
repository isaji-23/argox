"""Tests for COL-14: run records in the unified WORM audit chain (#109).

Run records persisted by COL-11 must be appended to the same hash-chained
``audit-log`` as administrative events, tagged ``kind="run"``, so the AI Act
Art. 12/13 content they carry (prompt, output, tokens, violations) is
tamper-evident. The verification endpoint must walk every kind and report which
kind/target broke the chain.

The TestClient runs FastAPI background tasks synchronously after the response,
so a plain ``202`` ingest has already appended to the chain by the time the
call returns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from argox_collector.app import create_app
from argox_collector.audit import AUDIT_KIND_RUN, digest_payload
from argox_collector.settings import CollectorSettings
from fastapi.testclient import TestClient


@pytest.fixture
def settings(tmp_path: Path) -> CollectorSettings:
    return CollectorSettings(
        storage_local_root=tmp_path / "blobs",
        index_duckdb_path=tmp_path / "index.duckdb",
    )


@pytest.fixture
def client(settings: CollectorSettings) -> TestClient:
    return TestClient(create_app(settings))


def _run_payload(run_id: str, trace_id: str | None = None) -> dict:
    payload: dict = {
        "run_id": run_id,
        "agent_name": "demo",
        "prompt": "hello",
        "final_output": "world",
        "tokens": {"input": 10, "output": 5},
    }
    if trace_id is not None:
        payload["trace_id"] = trace_id
    return payload


def _ingest_run(client: TestClient, payload: dict, durable: bool = False):
    headers = {"X-Argox-Durable": "true"} if durable else {}
    return client.post("/v1/runs", json=payload, headers=headers)


def _post_event(client: TestClient, target: str, kind: str = "event"):
    return client.post(
        "/api/v1/audit",
        json={"action": "act", "target": target, "kind": kind},
    )


def _segment_lines(client: TestClient, index: int = 0) -> list[str]:
    audit = client.app.state.audit
    segment = audit.list_segments()[index]
    return client.app.state.storage.get(segment.key).data.decode().splitlines()


def _rewrite_segment(client: TestClient, index: int, lines: list[str]) -> None:
    audit = client.app.state.audit
    segment = audit.list_segments()[index]
    body = ("\n".join(lines) + "\n").encode()
    client.app.state.storage.put(segment.key, body)


# -- run records enter the chain -------------------------------------------


def test_ingested_run_appears_in_chain(client: TestClient) -> None:
    resp = _ingest_run(client, _run_payload("run-1"))
    assert resp.status_code == 202

    listed = client.get("/api/v1/audit").json()
    assert listed["returned"] == 1
    entry = listed["items"][0]
    assert entry["kind"] == AUDIT_KIND_RUN
    assert entry["target"] == "run-1"
    assert entry["action"] == "run.ingest"
    # The chained digest is the digest of the exact stored blob bytes; the blob
    # path carries today's date, so fetch it from the index row.
    record = client.app.state.index.get_run("run-1")
    stored = client.app.state.storage.get(record.blob_path).data
    assert entry["payload_digest"] == digest_payload(stored)

    assert client.get("/api/v1/audit/verify").json()["ok"] is True


def test_durable_ingest_chains_run(client: TestClient) -> None:
    resp = _ingest_run(client, _run_payload("run-d"), durable=True)
    assert resp.status_code == 200
    listed = client.get("/api/v1/audit").json()
    assert [i["kind"] for i in listed["items"]] == [AUDIT_KIND_RUN]


def test_reingest_does_not_duplicate_chain_entry(client: TestClient) -> None:
    _ingest_run(client, _run_payload("run-1"))
    _ingest_run(client, _run_payload("run-1"))  # blob already exists
    listed = client.get("/api/v1/audit").json()
    # The immutable blob is written once, so the run is chained exactly once.
    assert listed["returned"] == 1


def test_run_only_chain_verifies(client: TestClient) -> None:
    for i in range(4):
        _ingest_run(client, _run_payload(f"run-{i}"))
    verify = client.get("/api/v1/audit/verify").json()
    assert verify["ok"] is True
    assert verify["total_entries"] == 4


def test_span_only_chain_verifies(client: TestClient) -> None:
    for i in range(3):
        assert _post_event(client, f"trace-{i}", kind="span_batch").status_code == 201
    verify = client.get("/api/v1/audit/verify").json()
    assert verify["ok"] is True
    assert verify["total_entries"] == 3


def test_interleaved_run_and_span_chain_verifies(client: TestClient) -> None:
    _ingest_run(client, _run_payload("run-a"))
    _post_event(client, "trace-a", kind="span_batch")
    _ingest_run(client, _run_payload("run-b"))
    _post_event(client, "trace-b", kind="span_batch")

    listed = client.get("/api/v1/audit").json()["items"]
    assert [i["kind"] for i in listed] == ["run", "span_batch", "run", "span_batch"]
    assert client.get("/api/v1/audit/verify").json()["ok"] is True


# -- tamper detection reports the kind -------------------------------------


def test_tampered_run_record_reports_kind_and_target(client: TestClient) -> None:
    _ingest_run(client, _run_payload("run-a"))
    _post_event(client, "trace-a", kind="span_batch")
    _ingest_run(client, _run_payload("run-b"))

    # Tamper the run record at seq 1 (offset 0) without fixing its hash.
    lines = _segment_lines(client, 0)
    record = json.loads(lines[0])
    assert record["kind"] == "run"
    record["payload_digest"] = "f" * 64
    lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    _rewrite_segment(client, 0, lines)

    verify = client.get("/api/v1/audit/verify").json()
    assert verify["ok"] is False
    assert verify["broken_seq"] == 1
    assert verify["broken_offset"] == 0
    assert verify["broken_kind"] == "run"
    assert verify["broken_target"] == "run-a"
    assert verify["reason"]


def test_tampered_span_record_reports_span_kind(client: TestClient) -> None:
    _ingest_run(client, _run_payload("run-a"))
    _post_event(client, "trace-x", kind="span_batch")

    lines = _segment_lines(client, 0)
    record = json.loads(lines[1])  # seq 2, the span_batch
    record["target"] = "tampered"
    lines[1] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    _rewrite_segment(client, 0, lines)

    verify = client.get("/api/v1/audit/verify").json()
    assert verify["ok"] is False
    assert verify["broken_seq"] == 2
    assert verify["broken_kind"] == "span_batch"
