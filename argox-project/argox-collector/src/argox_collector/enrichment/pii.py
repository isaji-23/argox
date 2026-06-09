"""Minimal residual-PII scan over span attributes.

Tags a span with ``argox.pii.residual_detected = True`` when a high-confidence
regex matches any string attribute value. This is a *tag-only* check: the
Collector never redacts content (redaction is the SDK's job, see
``PiiRedactionProcessor`` and COL-11 non-goals). The richer scan over event
payloads with normalisation lands in COL-07 (#92).

The detector is intentionally self-contained so the Collector stays independent
of ``argox-core``.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from argox_collector import semconv
from argox_collector.index.base import SpanRecord

# High-confidence patterns. Kept conservative to limit false positives.
_PATTERNS = {
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?(?:\d[ .-]?){9,11}\d(?!\d)"),
    "ES_DNI": re.compile(r"\b\d{8}[A-HJ-NP-TV-Z]\b"),
}


def contains_pii(text: str) -> bool:
    """Return ``True`` when any high-confidence PII pattern matches ``text``."""
    return any(pattern.search(text) for pattern in _PATTERNS.values())


def scan(record: SpanRecord) -> SpanRecord:
    """Return ``record`` tagged with residual-PII detection when matches exist.

    Idempotent: a record already tagged is returned unchanged.
    """
    if record.attributes.get(semconv.ARGOX_PII_RESIDUAL_DETECTED):
        return record

    if not _any_value_has_pii(record.attributes):
        return record

    attributes = {
        **record.attributes,
        semconv.ARGOX_PII_RESIDUAL_DETECTED: True,
    }
    return dataclasses.replace(record, attributes=attributes)


def _any_value_has_pii(value: Any) -> bool:
    if isinstance(value, str):
        return contains_pii(value)
    if isinstance(value, dict):
        return any(_any_value_has_pii(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_any_value_has_pii(item) for item in value)
    return False
