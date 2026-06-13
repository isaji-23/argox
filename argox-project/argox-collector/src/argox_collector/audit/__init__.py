"""Immutable, hash-chained audit log for the Argox Collector (COL-08).

Provides a WORM-style append-only log over the Collector's blob storage. Each
entry is linked into a SHA-256 hash chain so retroactive tampering is
detectable, satisfying the record-keeping requirement of AI Act Art. 12.
"""

from argox_collector.audit.chain import (
    GENESIS_HASH,
    AuditEntry,
    AuditRecord,
    canonical_json,
    digest_payload,
)
from argox_collector.audit.log import (
    LIFECYCLE_COOL_DAYS,
    LIFECYCLE_HOT_DAYS,
    AuditLog,
    AuditLogError,
    AuditVerificationResult,
    SegmentInfo,
    lifecycle_tier,
    validate_digest,
)

__all__ = [
    "GENESIS_HASH",
    "AuditEntry",
    "AuditRecord",
    "AuditLog",
    "AuditLogError",
    "AuditVerificationResult",
    "SegmentInfo",
    "LIFECYCLE_HOT_DAYS",
    "LIFECYCLE_COOL_DAYS",
    "canonical_json",
    "digest_payload",
    "lifecycle_tier",
    "validate_digest",
]
