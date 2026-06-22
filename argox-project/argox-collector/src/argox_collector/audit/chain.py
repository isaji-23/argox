"""Hash-chain primitives for the WORM audit log (COL-08).

Each audit record is linked to its predecessor by a SHA-256 hash chain so that
any retroactive edit, reorder or deletion is detectable: tampering with one
record invalidates its own ``hash`` and every link that follows. The chain
satisfies the record-keeping evidence required by AI Act Art. 12.

The hashed material follows the contract in architecture §5.3::

    hash = sha256(prev_hash || canonical_json(record))

where ``record`` is the entry's content *excluding* its own ``hash`` field and
``canonical_json`` is a deterministic, key-sorted, whitespace-free encoding so
the digest is stable across processes and Python versions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

# prev_hash of the very first record in the chain. A fixed all-zero digest
# marks the genesis link so verification can recognise the chain's start
# without a special-case ``None``.
GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON encoding of ``value``.

    Keys are sorted and all insignificant whitespace is stripped so the same
    logical object always produces byte-identical output — a hard requirement
    for a reproducible hash chain. ``ensure_ascii`` is disabled so non-ASCII
    payloads hash by their UTF-8 bytes rather than ``\\uXXXX`` escapes.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_payload(payload: Any) -> str:
    """Return the SHA-256 hex digest of an arbitrary JSON-serialisable payload.

    The payload is canonicalised first so semantically equal payloads (e.g.
    dicts with differently ordered keys) yield the same digest. Raw ``bytes``
    are hashed directly without canonicalisation.
    """
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return hashlib.sha256(bytes(payload)).hexdigest()
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    """The signed content of one audit-log entry.

    Attributes:
        seq: Monotonic, gap-free sequence number assigned at append time.
        timestamp: RFC 3339 / ISO 8601 UTC timestamp of the event.
        kind: Discriminator for the kind of record in the unified chain
            (COL-14): ``"run"`` for a run record persisted by COL-11,
            ``"span_batch"`` for an ingested span batch, or ``"event"`` for a
            generic administrative event. Hashed like every other field so the
            kind itself is tamper-evident. ``None`` marks a legacy entry that
            predates COL-14 and carried no ``kind``; such entries are hashed
            *without* a ``kind`` field (see :meth:`signing_dict`) so the chain
            written before this field existed still verifies unchanged.
        actor: Identity that performed the action (user, service, system).
        action: What happened (e.g. ``policy.update``, ``trace.ingest``).
        target: The object the action applied to: a policy id for events, the
            ``run_id`` for a run record, the ``trace_id`` for a span batch.
        payload_digest: SHA-256 hex digest of the associated payload, kept
            instead of the payload itself so the log never stores raw PII.
        prev_hash: ``hash`` of the preceding record, or :data:`GENESIS_HASH`
            for the first record.
    """

    seq: int
    timestamp: str
    kind: Optional[str]
    actor: str
    action: str
    target: str
    payload_digest: str
    prev_hash: str

    def signing_dict(self) -> dict[str, Any]:
        """Return the field mapping that feeds the hash (excludes ``hash``).

        ``kind`` is included only when present. A legacy record (``kind is
        None``) was hashed before the field existed, so omitting it here keeps
        its recomputed hash byte-identical to the stored one; every record
        written since COL-14 carries a non-``None`` kind and hashes it.
        """
        data: dict[str, Any] = {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "payload_digest": self.payload_digest,
            "prev_hash": self.prev_hash,
        }
        if self.kind is not None:
            data["kind"] = self.kind
        return data

    def compute_hash(self) -> str:
        """Return ``sha256(prev_hash || canonical_json(record))`` as hex."""
        material = self.prev_hash + canonical_json(self.signing_dict())
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    """A persisted audit record together with its computed chain ``hash``."""

    record: AuditRecord
    hash: str

    @classmethod
    def seal(cls, record: AuditRecord) -> "AuditEntry":
        """Compute the chain hash for ``record`` and wrap it into an entry."""
        return cls(record=record, hash=record.compute_hash())

    def to_dict(self) -> dict[str, Any]:
        """Flatten the entry into the JSON object stored on one JSONL line."""
        data = self.record.signing_dict()
        data["hash"] = self.hash
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        """Rebuild an entry from a stored JSON object.

        Raises:
            KeyError: If a required field is missing from ``data``.
        """
        record = AuditRecord(
            seq=data["seq"],
            timestamp=data["timestamp"],
            # Pre-COL-14 entries carry no ``kind`` key; preserve that as ``None``
            # so ``signing_dict`` hashes them exactly as they were originally
            # written and the legacy chain still verifies. New entries always
            # carry an explicit kind.
            kind=data.get("kind"),
            actor=data["actor"],
            action=data["action"],
            target=data["target"],
            payload_digest=data["payload_digest"],
            prev_hash=data["prev_hash"],
        )
        return cls(record=record, hash=data["hash"])
