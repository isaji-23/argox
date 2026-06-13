"""Tests for the COL-08 WORM audit log and its hash chain.

Covers the acceptance criteria from issue #93: the append API and recorded
fields, the per-record hash chain, the verification endpoint reporting the
first broken link, lifecycle tiering without deletion, and chain continuity
across segment rollover (plus tampering and out-of-band edits).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from argox_collector.app import create_app
from argox_collector.audit import (
    GENESIS_HASH,
    AuditLog,
    canonical_json,
    digest_payload,
    lifecycle_tier,
)
from argox_collector.storage.local import LocalStorageBackend
from fastapi.testclient import TestClient


@pytest.fixture
def storage(tmp_path) -> LocalStorageBackend:
    return LocalStorageBackend(tmp_path / "blobs")


@pytest.fixture
def audit(storage: LocalStorageBackend) -> AuditLog:
    return AuditLog(storage, prefix="audit-log", max_segment_records=1000)


# -- append + hash chain ---------------------------------------------------


def test_append_records_required_fields(audit: AuditLog) -> None:
    entry = audit.append(
        actor="alice",
        action="policy.update",
        target="pol-1",
        payload={"rule": "deny"},
    )
    rec = entry.record
    assert rec.seq == 1
    assert rec.actor == "alice"
    assert rec.action == "policy.update"
    assert rec.target == "pol-1"
    # Timestamp is a valid UTC ISO-8601 string.
    parsed = datetime.fromisoformat(rec.timestamp)
    assert parsed.tzinfo is not None
    # Payload is stored only as a digest, never raw.
    assert rec.payload_digest == digest_payload({"rule": "deny"})


def test_genesis_prev_hash_and_linking(audit: AuditLog) -> None:
    first = audit.append(actor="a", action="x", target="t", payload=1)
    second = audit.append(actor="a", action="y", target="t", payload=2)
    assert first.record.prev_hash == GENESIS_HASH
    assert second.record.prev_hash == first.hash
    # Stored hash equals the spec formula sha256(prev_hash || canonical_json).
    assert first.hash == first.record.compute_hash()


def test_payload_and_digest_are_mutually_exclusive(audit: AuditLog) -> None:
    with pytest.raises(ValueError):
        audit.append(actor="a", action="x", target="t", payload=1, payload_digest="ff")


def test_verify_happy_path(audit: AuditLog) -> None:
    for i in range(5):
        audit.append(actor="a", action="act", target=f"t{i}", payload=i)
    result = audit.verify()
    assert result.ok is True
    assert result.total_entries == 5
    assert result.broken_seq is None


# -- tampering detection ---------------------------------------------------


def test_verify_detects_payload_tampering(
    audit: AuditLog, storage: LocalStorageBackend
) -> None:
    for i in range(3):
        audit.append(actor="a", action="act", target=f"t{i}", payload=i)
    segment = audit.list_segments()[0]
    lines = storage.get(segment.key).data.decode().splitlines()
    # Edit the middle record's target but leave its stored hash intact.
    record = json.loads(lines[1])
    record["target"] = "tampered"
    lines[1] = canonical_json(record)
    storage.put(segment.key, ("\n".join(lines) + "\n").encode())

    result = audit.verify()
    assert result.ok is False
    assert result.broken_seq == 2
    assert "hash" in result.reason


def test_verify_detects_deleted_record(
    audit: AuditLog, storage: LocalStorageBackend
) -> None:
    for i in range(3):
        audit.append(actor="a", action="act", target=f"t{i}", payload=i)
    segment = audit.list_segments()[0]
    lines = storage.get(segment.key).data.decode().splitlines()
    del lines[1]  # remove seq=2, creating a gap
    storage.put(segment.key, ("\n".join(lines) + "\n").encode())

    result = audit.verify()
    assert result.ok is False
    assert result.broken_seq == 3
    assert "sequence gap" in result.reason


def test_verify_detects_rehashed_record(
    audit: AuditLog, storage: LocalStorageBackend
) -> None:
    """An attacker who recomputes the edited record's own hash still breaks
    the next link because its ``prev_hash`` no longer matches."""
    for i in range(3):
        audit.append(actor="a", action="act", target=f"t{i}", payload=i)
    segment = audit.list_segments()[0]
    lines = storage.get(segment.key).data.decode().splitlines()
    entry = json.loads(lines[0])
    entry["target"] = "tampered"
    # Recompute a self-consistent hash for the edited record.
    signing = {k: v for k, v in entry.items() if k != "hash"}
    import hashlib

    material = entry["prev_hash"] + canonical_json(signing)
    entry["hash"] = hashlib.sha256(material.encode()).hexdigest()
    lines[0] = canonical_json(entry)
    storage.put(segment.key, ("\n".join(lines) + "\n").encode())

    result = audit.verify()
    assert result.ok is False
    # seq=1 is now internally consistent; the break surfaces at seq=2.
    assert result.broken_seq == 2
    assert "prev_hash" in result.reason


# -- segment rollover ------------------------------------------------------


def test_chain_continues_across_rollover(storage: LocalStorageBackend) -> None:
    audit = AuditLog(storage, max_segment_records=2)
    entries = [
        audit.append(actor="a", action="act", target=f"t{i}", payload=i)
        for i in range(5)
    ]
    segments = audit.list_segments()
    # 5 records / 2 per segment -> two sealed segments + one open.
    assert len(segments) == 3
    assert segments[0].sealed and segments[0].seq_start == 1
    assert segments[1].sealed and segments[1].seq_start == 3
    assert not segments[-1].sealed  # open tail with seq 5

    # The chain is unbroken across the file boundaries: each entry links to
    # the previous one regardless of which segment it lives in.
    for prev, cur in zip(entries, entries[1:]):
        assert cur.record.prev_hash == prev.hash
    assert audit.verify().ok is True


def test_tamper_in_sealed_segment_detected(
    storage: LocalStorageBackend,
) -> None:
    audit = AuditLog(storage, max_segment_records=2)
    for i in range(5):
        audit.append(actor="a", action="act", target=f"t{i}", payload=i)
    sealed = audit.list_segments()[0]
    lines = storage.get(sealed.key).data.decode().splitlines()
    record = json.loads(lines[0])
    record["actor"] = "mallory"
    lines[0] = canonical_json(record)
    storage.put(sealed.key, ("\n".join(lines) + "\n").encode())

    result = audit.verify()
    assert result.ok is False
    assert result.broken_seq == 1


# -- recovery across process restart ---------------------------------------


def test_state_recovered_by_new_instance(
    storage: LocalStorageBackend,
) -> None:
    first = AuditLog(storage, max_segment_records=2)
    for i in range(3):
        first.append(actor="a", action="act", target=f"t{i}", payload=i)

    # A fresh AuditLog over the same storage resumes the chain seamlessly.
    second = AuditLog(storage, max_segment_records=2)
    fourth = second.append(actor="a", action="act", target="t3", payload=3)
    assert fourth.record.seq == 4
    assert second.count() == 4
    assert second.verify().ok is True


# -- lifecycle -------------------------------------------------------------


def test_lifecycle_tiers() -> None:
    now = datetime(2026, 6, 13, tzinfo=timezone.utc)
    assert lifecycle_tier(now - timedelta(days=10), now=now) == "hot"
    assert lifecycle_tier(now - timedelta(days=120), now=now) == "cool"
    assert lifecycle_tier(now - timedelta(days=400), now=now) == "archive"


def test_audit_log_has_no_delete_api(audit: AuditLog) -> None:
    # Compliance: the audit log must not expose a way to erase entries.
    assert not hasattr(audit, "delete")
    assert not hasattr(audit, "remove")


# -- input validation & robustness -----------------------------------------


def test_append_rejects_malformed_digest(audit: AuditLog) -> None:
    with pytest.raises(ValueError):
        audit.append(actor="a", action="x", target="t", payload_digest="ZZZ")
    # Uppercase hex is rejected too: digests are canonicalised lowercase.
    with pytest.raises(ValueError):
        audit.append(actor="a", action="x", target="t", payload_digest="A" * 64)


def test_append_accepts_valid_digest(audit: AuditLog) -> None:
    entry = audit.append(actor="a", action="x", target="t", payload_digest="a" * 64)
    assert entry.record.payload_digest == "a" * 64


def test_concurrent_writer_detected(storage: LocalStorageBackend) -> None:
    """Two AuditLog instances over the same storage simulate two processes.

    Both load the same tail and try to extend the same open segment; the
    ETag-guarded write rejects the loser instead of silently corrupting."""
    from argox_collector.audit import AuditLogError

    writer_a = AuditLog(storage, max_segment_records=100)
    writer_b = AuditLog(storage, max_segment_records=100)
    writer_a.append(actor="a", action="x", target="t0", payload=0)
    # writer_b loaded no state yet; force it to load the current tail.
    writer_b.append(actor="b", action="x", target="t1", payload=1)
    # writer_a still holds a stale ETag for the segment writer_b just rewrote.
    with pytest.raises(AuditLogError):
        writer_a.append(actor="a", action="x", target="t2", payload=2)
    # The log on storage is still a valid chain (no torn write).
    assert AuditLog(storage).verify().ok is True


def test_verify_tolerates_malformed_line(
    audit: AuditLog, storage: LocalStorageBackend
) -> None:
    for i in range(3):
        audit.append(actor="a", action="act", target=f"t{i}", payload=i)
    segment = audit.list_segments()[0]
    lines = storage.get(segment.key).data.decode().splitlines()
    lines[1] = "{not valid json"
    storage.put(segment.key, ("\n".join(lines) + "\n").encode())

    result = audit.verify()
    assert result.ok is False
    assert result.broken_seq == 2
    assert "malformed" in result.reason


def test_corrupt_tail_blocks_append(
    storage: LocalStorageBackend,
) -> None:
    from argox_collector.audit import AuditLogError

    first = AuditLog(storage, max_segment_records=100)
    first.append(actor="a", action="x", target="t", payload=1)
    segment = first.list_segments()[0]
    storage.put(segment.key, b"{corrupt tail\n")

    fresh = AuditLog(storage, max_segment_records=100)
    with pytest.raises(AuditLogError):
        fresh.append(actor="a", action="x", target="t2", payload=2)
    # verify still runs (it never loads writer state) to diagnose the damage.
    assert fresh.verify().ok is False


# -- HTTP API --------------------------------------------------------------


@pytest.fixture
def client(storage: LocalStorageBackend) -> TestClient:
    audit = AuditLog(storage, max_segment_records=2)
    app = create_app(storage=storage, audit_log=audit)
    return TestClient(app)


def test_api_append_and_verify(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/audit",
        json={
            "actor": "alice",
            "action": "policy.update",
            "target": "pol-1",
            "payload": {"rule": "deny"},
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["seq"] == 1
    assert body["prev_hash"] == GENESIS_HASH
    assert body["payload_digest"] == digest_payload({"rule": "deny"})

    client.post(
        "/api/v1/audit",
        json={"actor": "bob", "action": "trace.ingest", "target": "t-2"},
    )

    verify = client.get("/api/v1/audit/verify").json()
    assert verify["ok"] is True
    assert verify["total_entries"] == 2


def test_api_list_entries(client: TestClient) -> None:
    for i in range(3):
        client.post(
            "/api/v1/audit",
            json={"actor": "a", "action": "act", "target": f"t{i}"},
        )
    listed = client.get("/api/v1/audit", params={"limit": 2}).json()
    assert listed["returned"] == 2
    assert listed["offset"] == 0
    assert [item["seq"] for item in listed["items"]] == [1, 2]


def test_api_list_entries_offset(client: TestClient) -> None:
    for i in range(5):
        client.post(
            "/api/v1/audit",
            json={"actor": "a", "action": "act", "target": f"t{i}"},
        )
    listed = client.get("/api/v1/audit", params={"offset": 2, "limit": 2}).json()
    assert listed["offset"] == 2
    assert [item["seq"] for item in listed["items"]] == [3, 4]


def test_api_rejects_malformed_digest(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/audit",
        json={
            "actor": "a",
            "action": "act",
            "target": "t",
            "payload_digest": "not-a-hex-digest",
        },
    )
    assert resp.status_code == 422


def test_api_rejects_payload_and_digest_together(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/audit",
        json={
            "actor": "a",
            "action": "act",
            "target": "t",
            "payload": {"x": 1},
            "payload_digest": "a" * 64,
        },
    )
    assert resp.status_code == 422


def test_api_verify_reports_break_after_tampering(
    client: TestClient, storage: LocalStorageBackend
) -> None:
    for i in range(3):
        client.post(
            "/api/v1/audit",
            json={"actor": "a", "action": "act", "target": f"t{i}"},
        )
    # Tamper directly with the first sealed segment.
    audit = AuditLog(storage, max_segment_records=2)
    segment = audit.list_segments()[0]
    lines = storage.get(segment.key).data.decode().splitlines()
    record = json.loads(lines[0])
    record["target"] = "tampered"
    lines[0] = canonical_json(record)
    storage.put(segment.key, ("\n".join(lines) + "\n").encode())

    verify = client.get("/api/v1/audit/verify").json()
    assert verify["ok"] is False
    assert verify["broken_seq"] == 1
    assert verify["reason"]
