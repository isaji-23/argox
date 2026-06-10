"""Residual-PII scan over span attributes and event payloads.

Tags a span with ``argox.pii.residual_detected = True`` when a high-confidence
regex matches any string value in the span attributes or in its event payload
attributes (COL-07). This is a *tag-only* check: the Collector never redacts
content (redaction is the SDK's job, see ``PiiRedactionProcessor`` and COL-11
non-goals). In particular, content that triggers the tag remains unredacted in
the raw blob — the tag exists so downstream consumers can find and handle it,
not to scrub it.

Event payloads carry full LLM content and arrive attacker-influenced, so the
scan is bounded: at most ``_MAX_EVENTS_SCANNED`` events are inspected and each
string is truncated to ``_MAX_SCAN_CHARS`` before the regexes run, keeping
ingest-path CPU bounded for pathological spans.

The detector is intentionally self-contained so the Collector stays independent
of ``argox-core``.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from argox_collector import semconv
from argox_collector.index.base import SpanRecord

# Scan bounds for attacker-influenced input (see module docstring). Truncation
# can miss a match that spans the cut, which is acceptable: this is a
# best-effort residual check, not the redaction layer.
_MAX_SCAN_CHARS = 16_384
_MAX_EVENTS_SCANNED = 100

# High-confidence patterns. Kept conservative to limit false positives.
_PATTERNS = {
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?(?:\d[ .-]?){9,11}\d(?!\d)"),
    "ES_DNI": re.compile(r"\b\d{8}[A-HJ-NP-TV-Z]\b"),
}


def contains_pii(text: str) -> bool:
    """Return ``True`` when any high-confidence PII pattern matches ``text``.

    Input is truncated to ``_MAX_SCAN_CHARS`` so oversized values cannot burn
    unbounded CPU on the ingest path.
    """
    text = text[:_MAX_SCAN_CHARS]
    return any(pattern.search(text) for pattern in _PATTERNS.values())


def scan(record: SpanRecord) -> SpanRecord:
    """Return ``record`` tagged with residual-PII detection when matches exist.

    Span attributes and event payload attributes are scanned (event names and
    timestamps are not — arbitrary event names would only feed false
    positives). Idempotent: a record already tagged is returned unchanged.
    """
    if record.attributes.get(semconv.ARGOX_PII_RESIDUAL_DETECTED):
        return record

    if not _any_value_has_pii(record.attributes) and not _events_have_pii(
        record.events
    ):
        return record

    attributes = {
        **record.attributes,
        semconv.ARGOX_PII_RESIDUAL_DETECTED: True,
    }
    return dataclasses.replace(record, attributes=attributes)


def _events_have_pii(events: Any) -> bool:
    """Scan event payload attributes, bounded to ``_MAX_EVENTS_SCANNED`` events."""
    return any(
        _any_value_has_pii(event.get("attributes"))
        for event in events[:_MAX_EVENTS_SCANNED]
        if isinstance(event, dict)
    )


def _any_value_has_pii(value: Any) -> bool:
    if isinstance(value, str):
        return contains_pii(value)
    if isinstance(value, dict):
        return any(_any_value_has_pii(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_any_value_has_pii(item) for item in value)
    return False
