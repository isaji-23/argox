"""WORM audit log built on the Collector's blob :class:`StorageBackend` (COL-08).

Entries are appended to JSONL segments under
``audit-log/{YYYY}/{MM}/{seq_start}-{seq_end}.jsonl`` (architecture §5.3). Each
record is linked into a SHA-256 :mod:`hash chain <argox_collector.audit.chain>`
so the log is tamper-evident, and the store exposes no delete operation: AI Act
Art. 12 requires audit data to be retained, not erased.

The blob abstraction overwrites whole objects rather than appending in place, so
a segment is rewritten on every append. Segments are capped at
``max_segment_records`` entries to bound that rewrite cost; the chain continues
seamlessly across the rollover because the first record of a new segment carries
the ``prev_hash`` of the last record in the previous one.

A single writer is assumed (the Collector process). Appends are serialised with
an in-process lock; the hash chain itself makes any concurrent or out-of-band
write detectable at verification time.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional

from argox_collector.audit.chain import (
    GENESIS_HASH,
    AuditEntry,
    AuditRecord,
    canonical_json,
    digest_payload,
)
from argox_collector.storage import (
    BlobNotFoundError,
    StorageBackend,
)

_SEGMENT_SUFFIX = ".jsonl"
_OPEN_MARKER = "open"
_CONTENT_TYPE = "application/x-ndjson"

# Lifecycle tiers (architecture §5.4). Audit data is never deleted.
LIFECYCLE_HOT_DAYS = 90
LIFECYCLE_COOL_DAYS = 365

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class AuditVerificationResult:
    """Outcome of walking the whole chain.

    Attributes:
        ok: ``True`` when every link verified.
        total_entries: Number of entries inspected.
        broken_seq: Sequence number of the first record that failed, or
            ``None`` when the chain is intact.
        reason: Human-readable explanation of the first break, or ``None``.
    """

    ok: bool
    total_entries: int
    broken_seq: Optional[int] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class SegmentInfo:
    """Descriptor of one persisted JSONL segment."""

    key: str
    seq_start: int
    seq_end: Optional[int]  # ``None`` while the segment is still open.
    sealed: bool


def lifecycle_tier(timestamp: datetime, *, now: Optional[datetime] = None) -> str:
    """Return the storage tier an entry of ``timestamp`` belongs to.

    Mirrors the Azure lifecycle policy: ``hot`` for the first 90 days, ``cool``
    until 365 days, then ``archive`` indefinitely. There is no ``delete`` tier;
    audit data is retained for the lifetime of the deployment.
    """
    reference = now or datetime.now(timezone.utc)
    age_days = (reference - timestamp).total_seconds() / 86_400
    if age_days < LIFECYCLE_HOT_DAYS:
        return "hot"
    if age_days < LIFECYCLE_COOL_DAYS:
        return "cool"
    return "archive"


class AuditLog:
    """Append-only, hash-chained audit log over a :class:`StorageBackend`."""

    def __init__(
        self,
        storage: StorageBackend,
        *,
        prefix: str = "audit-log",
        max_segment_records: int = 1000,
        clock: Optional[Clock] = None,
    ) -> None:
        if max_segment_records < 1:
            raise ValueError("max_segment_records must be >= 1")
        self._storage = storage
        self._prefix = prefix.strip("/")
        self._max = max_segment_records
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

        # Recovered lazily on first use so construction never touches storage.
        self._loaded = False
        self._last_seq = 0
        self._last_hash = GENESIS_HASH
        # Active (unsealed) segment, or ``None`` when the next append must
        # open a fresh segment.
        self._active_key: Optional[str] = None
        self._active_start: Optional[int] = None
        self._active_lines: list[str] = []

    # -- public API --------------------------------------------------------

    def append(
        self,
        *,
        actor: str,
        action: str,
        target: str,
        payload: Any = None,
        payload_digest: Optional[str] = None,
    ) -> AuditEntry:
        """Record an event and return the sealed, chained entry.

        Exactly one of ``payload`` or ``payload_digest`` should be supplied.
        ``payload`` is hashed into a digest so the log never stores the raw
        (possibly sensitive) value; ``payload_digest`` lets callers that have
        already hashed the payload pass the digest directly. If neither is
        given the digest of an empty payload is recorded.

        Raises:
            ValueError: If both ``payload`` and ``payload_digest`` are given.
        """
        if payload is not None and payload_digest is not None:
            raise ValueError("pass either payload or payload_digest, not both")
        if payload_digest is None:
            payload_digest = digest_payload(payload)

        with self._lock:
            self._ensure_loaded()
            seq = self._last_seq + 1
            record = AuditRecord(
                seq=seq,
                timestamp=self._now_iso(),
                actor=actor,
                action=action,
                target=target,
                payload_digest=payload_digest,
                prev_hash=self._last_hash,
            )
            entry = AuditEntry.seal(record)
            self._append_entry(entry)
            self._last_seq = seq
            self._last_hash = entry.hash
            return entry

    def iter_entries(self) -> Iterator[AuditEntry]:
        """Yield every entry across all segments in sequence order.

        Reads straight from storage (not the in-memory append cache) so that
        verification reflects exactly what is persisted, including any
        out-of-band tampering.
        """
        self._ensure_loaded()
        for segment in self.list_segments():
            for line in self._read_lines(segment.key):
                yield AuditEntry.from_dict(_parse_line(line))

    def verify(self) -> AuditVerificationResult:
        """Walk the chain and report the first broken link, if any."""
        prev_hash = GENESIS_HASH
        expected_seq = 1
        count = 0
        for entry in self.iter_entries():
            count += 1
            rec = entry.record
            if rec.seq != expected_seq:
                return AuditVerificationResult(
                    ok=False,
                    total_entries=count,
                    broken_seq=rec.seq,
                    reason=(f"sequence gap: expected {expected_seq}, got {rec.seq}"),
                )
            if rec.prev_hash != prev_hash:
                return AuditVerificationResult(
                    ok=False,
                    total_entries=count,
                    broken_seq=rec.seq,
                    reason="prev_hash does not match previous record",
                )
            if rec.compute_hash() != entry.hash:
                return AuditVerificationResult(
                    ok=False,
                    total_entries=count,
                    broken_seq=rec.seq,
                    reason="record hash does not match its content",
                )
            prev_hash = entry.hash
            expected_seq += 1
        return AuditVerificationResult(ok=True, total_entries=count)

    def list_segments(self) -> list[SegmentInfo]:
        """Return all segments ordered by their starting sequence number.

        When a sealed segment and an open segment share the same start (which
        can only happen if the process crashed between sealing and removing
        the open marker), the sealed one wins: its content is identical and
        finalised.
        """
        by_start: dict[int, SegmentInfo] = {}
        for meta in self._storage.list(prefix=f"{self._prefix}/"):
            parsed = _parse_segment_key(meta.key, self._prefix)
            if parsed is None:
                continue
            existing = by_start.get(parsed.seq_start)
            # Prefer the sealed segment over a leftover open marker.
            if existing is None or (parsed.sealed and not existing.sealed):
                by_start[parsed.seq_start] = parsed
        return [by_start[start] for start in sorted(by_start)]

    def count(self) -> int:
        """Return the total number of entries currently appended."""
        self._ensure_loaded()
        return self._last_seq

    # -- internals ---------------------------------------------------------

    def _now_iso(self) -> str:
        moment = self._clock()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()

    def _append_entry(self, entry: AuditEntry) -> None:
        """Persist ``entry`` into the active segment, rolling over when full."""
        if self._active_key is None:
            self._open_segment(entry.record.seq)
        self._active_lines.append(canonical_json(entry.to_dict()))
        body = self._encode(self._active_lines)
        assert self._active_key is not None  # set by _open_segment
        self._storage.put(self._active_key, body, content_type=_CONTENT_TYPE)
        if len(self._active_lines) >= self._max:
            self._seal_segment(entry.record.seq, body)

    def _open_segment(self, seq_start: int) -> None:
        partition = self._clock().astimezone(timezone.utc).strftime("%Y/%m")
        self._active_start = seq_start
        self._active_key = (
            f"{self._prefix}/{partition}/"
            f"{seq_start:012d}-{_OPEN_MARKER}{_SEGMENT_SUFFIX}"
        )
        self._active_lines = []

    def _seal_segment(self, seq_end: int, body: bytes) -> None:
        """Finalise the active segment under its ``{start}-{end}`` name.

        The sealed blob is written first, then the transient open marker is
        removed. A crash in between leaves both blobs with identical content;
        :meth:`list_segments` deduplicates them in favour of the sealed one.
        """
        assert self._active_key is not None and self._active_start is not None
        partition = self._active_key.rsplit("/", 1)[0]
        sealed_key = (
            f"{partition}/{self._active_start:012d}-{seq_end:012d}{_SEGMENT_SUFFIX}"
        )
        self._storage.put(sealed_key, body, content_type=_CONTENT_TYPE)
        self._storage.delete(self._active_key)
        self._active_key = None
        self._active_start = None
        self._active_lines = []

    def _ensure_loaded(self) -> None:
        """Reconstruct chain state from storage on first use."""
        if self._loaded:
            return
        segments = self.list_segments()
        if segments:
            last = segments[-1]
            lines = self._read_lines(last.key)
            if lines:
                tail = AuditEntry.from_dict(_parse_line(lines[-1]))
                self._last_seq = tail.record.seq
                self._last_hash = tail.hash
                # Resume an unsealed tail so its existing lines are preserved
                # on the next append rather than overwritten.
                if not last.sealed:
                    self._active_key = last.key
                    self._active_start = last.seq_start
                    self._active_lines = lines
        self._loaded = True

    def _read_lines(self, key: str) -> list[str]:
        try:
            blob = self._storage.get(key)
        except BlobNotFoundError:
            return []
        text = blob.data.decode("utf-8")
        return [line for line in text.splitlines() if line]

    @staticmethod
    def _encode(lines: list[str]) -> bytes:
        return ("\n".join(lines) + "\n").encode("utf-8")


def _parse_line(line: str) -> dict[str, Any]:
    return json.loads(line)


def _parse_segment_key(key: str, prefix: str) -> Optional[SegmentInfo]:
    """Parse a segment blob key into a :class:`SegmentInfo`, or ``None``.

    Keys that do not match ``{prefix}/{YYYY}/{MM}/{start}-{end|open}.jsonl``
    are ignored so unrelated blobs under the prefix never break iteration.
    """
    if not key.startswith(f"{prefix}/") or not key.endswith(_SEGMENT_SUFFIX):
        return None
    name = key[len(prefix) + 1 :].rsplit("/", 1)[-1]
    stem = name[: -len(_SEGMENT_SUFFIX)]
    start_str, _, end_str = stem.partition("-")
    if not end_str or not start_str.isdigit():
        return None
    try:
        seq_start = int(start_str)
    except ValueError:
        return None
    if end_str == _OPEN_MARKER:
        return SegmentInfo(key=key, seq_start=seq_start, seq_end=None, sealed=False)
    if not end_str.isdigit():
        return None
    return SegmentInfo(key=key, seq_start=seq_start, seq_end=int(end_str), sealed=True)
