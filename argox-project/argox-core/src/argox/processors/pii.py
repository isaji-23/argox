"""Built-in PII redaction processor (PROC-01).

A pure-regex, dependency-free :class:`ArgoxProcessor` that scrubs common
personally-identifiable information from strings flowing through the
Argox pipeline. It covers all three lifecycle phases — ``process_input``
(opt-in), ``process_tool_args`` (with recursive traversal), and
``process_output`` — and emits an ``argox.pii.redacted`` span event
carrying per-entity redaction counts without ever leaking raw values.

The detector is pluggable via the :class:`Detector` protocol so a richer
backend (e.g. ``presidio-analyzer``) can be wired in later without
changing the public processor surface.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any, NamedTuple, Protocol

from opentelemetry import trace

from argox.core.context import RunContext
from argox.interfaces.processor import ArgoxProcessor
from argox.semconv.attributes import (
    ARGOX_PII_REDACTIONS,
    ARGOX_PROCESSOR_NAME,
    ARGOX_PROCESSOR_PHASE,
    ARGOX_PROCESSOR_TOOL_NAME,
    EVENT_PII_REDACTED,
)

_LOGGER = logging.getLogger(__name__)


class RedactionMode(str, enum.Enum):
    """How a detected PII span is replaced in the output text.

    Attributes:
        MASK: Replace the value with ``[REDACTED:<ENTITY>]``.
        HASH: Replace the value with the first 12 hex chars of
            ``sha256(value + salt)``, so downstream joins on the same
            value still collide deterministically.
        DROP: Replace the value with an empty string.
    """

    MASK = "mask"
    HASH = "hash"
    DROP = "drop"


class EntityMatch(NamedTuple):
    """A detected PII span.

    ``start`` and ``end`` are character offsets into the source string;
    ``entity`` is one of the catalogue labels (e.g. ``"EMAIL"``);
    ``value`` is the raw matched substring (needed by ``HASH`` mode and
    never logged).
    """

    start: int
    end: int
    entity: str
    value: str


class Detector(Protocol):
    """Pluggable detector contract.

    An implementation returns every PII match found in ``text``. Overlaps
    are resolved by the processor (entity precedence first per
    :data:`_ENTITY_PRECEDENCE`, ties broken by longest match then earliest
    start offset), so detectors do not need to deduplicate.
    """

    def detect(self, text: str, entities: Sequence[str]) -> list[EntityMatch]:
        ...


# ---------------------------------------------------------------------------
# Default regex-based detector
# ---------------------------------------------------------------------------


# Higher index = higher precedence when two matches overlap on the same span.
_ENTITY_PRECEDENCE: tuple[str, ...] = (
    "PHONE",
    "IPV4",
    "IPV6",
    "EMAIL",
    "ES_DNI",
    "ES_NIE",
    "IBAN",
    "CREDIT_CARD",
)


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# E.164: leading +, country digit 1-9, 7-14 more digits. Anchored so we don't
# eat the leading digit of a longer number that just happens to follow text.
_PHONE_RE = re.compile(r"(?<!\d)\+[1-9]\d{6,14}(?!\d)")
_IPV4_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
# IPv6 is permissive: full eight groups, ``::``-compressed forms, and the
# mixed IPv4-mapped tail. We require at least one colon to avoid matching
# bare hex words.
_IPV6_RE = re.compile(
    r"(?<![0-9A-Fa-f:])"
    r"(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}"
    r"|[0-9A-Fa-f]{1,4}:(?:(?::[0-9A-Fa-f]{1,4}){1,6})"
    r"|:(?:(?::[0-9A-Fa-f]{1,4}){1,7}|:)"
    r")"
    r"(?![0-9A-Fa-f:])"
)
# IBAN: 2 letters (country) + 2 digits (checksum) + 11–30 alphanumerics
# (BBAN). Accepted in two canonical forms:
#   - contiguous, e.g. ``ES9121000418450200051332``
#   - 4-char groups separated by single spaces, e.g.
#     ``ES91 2100 0418 4502 0005 1332``.
# Lowercase is allowed; the post-validator normalizes case before the
# shape check. Non-4-char trailing groups are intentionally not matched
# in v1 — keeping the boundary tight avoids the regex greedily swallowing
# the next word into the IBAN span.
_IBAN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Za-z]{2}\d{2}"
    r"(?:"
    r"[A-Za-z0-9]{11,30}"
    r"|"
    r"(?: [A-Za-z0-9]{4}){2,7}"
    r")"
    r"(?![A-Za-z0-9])"
)
# Credit card: 13–19 digits, optional single space or dash between digits.
_CC_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
_ES_DNI_RE = re.compile(r"(?<![A-Za-z0-9])\d{8}[A-HJ-NP-TV-Z](?![A-Za-z0-9])")
_ES_NIE_RE = re.compile(r"(?<![A-Za-z0-9])[XYZ]\d{7}[A-HJ-NP-TV-Z](?![A-Za-z0-9])")


def _valid_ipv4(value: str) -> bool:
    """Reject IPv4-shaped tokens whose octets fall outside ``0..255``."""
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or len(part) > 3:
            return False
        if int(part) > 255:
            return False
    return True


def _luhn_valid(digits: str) -> bool:
    """Return True if ``digits`` (already stripped of separators) passes Luhn."""
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        n = ord(ch) - 48
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _valid_iban(value: str) -> bool:
    """Validate IBAN shape after stripping whitespace.

    Mod-97 verification is intentionally out of scope for v1 — the regex
    plus shape check already gives high precision on real-world text.
    """
    compact = value.replace(" ", "")
    if not (15 <= len(compact) <= 34):
        return False
    if not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    return compact[4:].isalnum()


_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def _valid_es_dni(value: str) -> bool:
    """Check the control letter of a Spanish DNI (``8 digits + letter``)."""
    number = int(value[:8])
    expected = _DNI_LETTERS[number % 23]
    return value[8].upper() == expected


def _valid_es_nie(value: str) -> bool:
    """Check the control letter of a Spanish NIE (``[XYZ] + 7 digits + letter``)."""
    prefix_map = {"X": "0", "Y": "1", "Z": "2"}
    head = prefix_map[value[0].upper()] + value[1:8]
    expected = _DNI_LETTERS[int(head) % 23]
    return value[8].upper() == expected


class _DefaultRegexDetector:
    """Zero-dependency detector covering the v1 entity catalogue.

    Each entity is matched by a dedicated, anchored regex; numeric
    entities (CREDIT_CARD, ES_DNI, ES_NIE, IPV4) are post-validated
    so a regex hit alone is not enough to trigger redaction.
    """

    _PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("EMAIL", _EMAIL_RE),
        ("PHONE", _PHONE_RE),
        ("IPV4", _IPV4_RE),
        ("IPV6", _IPV6_RE),
        ("IBAN", _IBAN_RE),
        ("CREDIT_CARD", _CC_RE),
        ("ES_DNI", _ES_DNI_RE),
        ("ES_NIE", _ES_NIE_RE),
    )

    def detect(self, text: str, entities: Sequence[str]) -> list[EntityMatch]:
        enabled = set(entities)
        matches: list[EntityMatch] = []
        for entity, pattern in self._PATTERNS:
            if entity not in enabled:
                continue
            for m in pattern.finditer(text):
                raw = m.group(0)
                if entity == "IPV4" and not _valid_ipv4(raw):
                    continue
                if entity == "CREDIT_CARD":
                    digits = re.sub(r"[ \-]", "", raw)
                    if not _luhn_valid(digits):
                        continue
                if entity == "IBAN" and not _valid_iban(raw):
                    continue
                if entity == "ES_DNI" and not _valid_es_dni(raw):
                    continue
                if entity == "ES_NIE" and not _valid_es_nie(raw):
                    continue
                matches.append(EntityMatch(m.start(), m.end(), entity, raw))
        return matches


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


DEFAULT_ENTITIES: tuple[str, ...] = _ENTITY_PRECEDENCE


class PiiRedactionProcessor(ArgoxProcessor):
    """Built-in PII redaction processor.

    Scrubs the v1 entity catalogue (``EMAIL``, ``PHONE``, ``IPV4``, ``IPV6``,
    ``IBAN``, ``CREDIT_CARD``, ``ES_DNI``, ``ES_NIE``) from every string the
    Argox pipeline routes through it. ``process_tool_args`` recurses into
    nested ``dict``/``list``/``tuple`` payloads; non-string scalars pass
    through untouched.

    Failure mode is fail-open at the processor level: if the configured
    detector raises, the original value is returned and a warning is
    logged. The Manager's ``strict=`` registration flag is the contract
    for fail-closed semantics; this processor never crashes on its own.

    Args:
        entities: Iterable of entity labels to detect. Defaults to the
            full built-in catalogue. The default regex detector ignores
            any label outside its catalogue; a custom :class:`Detector`
            is free to recognize and emit additional labels, which the
            processor will then redact like any other entity.
        mode: One of :class:`RedactionMode`.
            ``MASK`` (default) replaces matches with ``[REDACTED:<ENTITY>]``;
            ``HASH`` replaces them with ``sha256(value + salt)[:12]``;
            ``DROP`` replaces them with an empty string.
        redact_input: If False (default), ``process_input`` passes the
            prompt through unchanged — most LLM flows need to see the
            original value to answer correctly. Set to True when input
            must be scrubbed end-to-end.
        hash_salt: Salt mixed into the SHA-256 digest when ``mode`` is
            :attr:`RedactionMode.HASH`. Ignored for the other modes.
        detector: Optional custom :class:`Detector`. Defaults to the
            pure-regex catalogue shipped with the SDK.
    """

    def __init__(
        self,
        entities: Iterable[str] | None = None,
        mode: RedactionMode = RedactionMode.MASK,
        redact_input: bool = False,
        hash_salt: str = "",
        detector: Detector | None = None,
    ) -> None:
        if isinstance(entities, str):
            # ``str`` is iterable in Python and would silently expand to its
            # individual characters, which never match a catalogue label and
            # would mute detection entirely. Reject it at the boundary so
            # ``entities="EMAIL"`` fails loudly instead of disabling redaction.
            raise TypeError(
                "entities must be an iterable of labels (e.g. ['EMAIL']), "
                "not a single string"
            )
        self._entities: tuple[str, ...] = (
            tuple(entities) if entities is not None else DEFAULT_ENTITIES
        )
        self._mode = mode
        self._redact_input = redact_input
        self._hash_salt = hash_salt
        self._detector: Detector = detector or _DefaultRegexDetector()

    # ------------------------------------------------------------------
    # ArgoxProcessor surface
    # ------------------------------------------------------------------

    async def process_input(self, text: str, ctx: RunContext) -> str:
        if not self._redact_input:
            return text
        return self._redact_string(text, phase="input")

    async def process_tool_args(
        self, tool_name: str, args: dict, ctx: RunContext,
    ) -> dict:
        counts: dict[str, int] = {}
        redacted = self._redact_any(args, counts)
        self._emit_event("tool_args", counts, tool_name=tool_name)
        # ``_redact_any`` always returns a dict for a dict input.
        return redacted  # type: ignore[return-value]

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return self._redact_string(text, phase="output")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _redact_string(self, text: str, phase: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        counts: dict[str, int] = {}
        out = self._apply(text, counts)
        self._emit_event(phase, counts)
        return out

    def _redact_any(self, value: Any, counts: dict[str, int]) -> Any:
        if isinstance(value, str):
            return self._apply(value, counts)
        if isinstance(value, dict):
            return {k: self._redact_any(v, counts) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_any(v, counts) for v in value]
        if isinstance(value, tuple):
            return tuple(self._redact_any(v, counts) for v in value)
        return value

    def _apply(self, text: str, counts: dict[str, int]) -> str:
        """Detect, deduplicate, and rewrite ``text`` in place.

        Overlapping matches are resolved by entity precedence first
        (:data:`_ENTITY_PRECEDENCE`); ties on precedence fall back to
        the longest span, then to the earliest start offset. ``counts``
        is mutated in place so the caller can emit a single aggregated
        span event per phase invocation.
        """
        try:
            matches = self._detector.detect(text, self._entities)
        except asyncio.CancelledError:
            # Cancellation is control-flow, not a detector failure — let it
            # propagate so the Manager can shut the run down cleanly. This
            # mirrors the pattern in ``ArgoxManager._run_processors``.
            raise
        except Exception as exc:
            # Log only the exception type — a detector's exception message
            # may quote the raw input and we must never leak PII into logs.
            _LOGGER.warning(
                "PII detector %s raised; returning original text",
                type(exc).__name__,
            )
            return text

        if not matches:
            return text

        chosen = _resolve_overlaps(matches)
        if not chosen:
            return text

        chosen.sort(key=lambda m: m.start, reverse=True)
        out = text
        for match in chosen:
            replacement = self._replacement(match)
            out = out[: match.start] + replacement + out[match.end :]
            counts[match.entity] = counts.get(match.entity, 0) + 1
        return out

    def _replacement(self, match: EntityMatch) -> str:
        if self._mode is RedactionMode.MASK:
            return f"[REDACTED:{match.entity}]"
        if self._mode is RedactionMode.HASH:
            normalized = _normalize_for_hash(match.entity, match.value)
            digest = hashlib.sha256(
                (normalized + self._hash_salt).encode("utf-8")
            ).hexdigest()
            return digest[:12]
        if self._mode is RedactionMode.DROP:
            return ""
        # Defensive — RedactionMode is closed; unreachable under normal use.
        return f"[REDACTED:{match.entity}]"  # pragma: no cover

    def _emit_event(
        self,
        phase: str,
        counts: dict[str, int],
        tool_name: str | None = None,
    ) -> None:
        """Attach an ``argox.pii.redacted`` event with per-entity counts.

        A dedicated event name is used (rather than the standard
        ``argox.processor.applied`` the Manager already emits) so a
        consumer can tell apart "this processor ran" from "this
        processor actually redacted something". No raw values are
        written; the event carries only the entity label and the
        number of redactions of that kind.
        """
        if not counts:
            return
        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        encoded = [f"{entity}:{count}" for entity, count in sorted(counts.items())]
        attributes: dict[str, Any] = {
            ARGOX_PROCESSOR_NAME: type(self).__name__,
            ARGOX_PROCESSOR_PHASE: phase,
            ARGOX_PII_REDACTIONS: encoded,
        }
        if tool_name is not None:
            attributes[ARGOX_PROCESSOR_TOOL_NAME] = tool_name
        span.add_event(EVENT_PII_REDACTED, attributes)


def _normalize_for_hash(entity: str, value: str) -> str:
    """Canonicalize a value before hashing so HASH mode supports stable joins.

    Without normalization, the same logical PII would hash differently
    when its textual form varies (``A@B.com`` vs ``a@b.com``,
    ``4111-1111-1111-1111`` vs ``4111 1111 1111 1111``, ``ES91 21...``
    vs ``ES9121...``). The contract for HASH mode is that downstream
    joins still collide on the underlying identity, so we strip
    formatting and apply the canonical case per entity.
    """
    if entity == "EMAIL":
        return value.lower()
    if entity == "CREDIT_CARD":
        return re.sub(r"[ \-]", "", value)
    if entity == "IBAN":
        return value.replace(" ", "").upper()
    if entity == "PHONE":
        return value.replace(" ", "")
    if entity in ("ES_DNI", "ES_NIE"):
        return value.upper()
    return value


def _resolve_overlaps(matches: Sequence[EntityMatch]) -> list[EntityMatch]:
    """Drop overlapping detections.

    Resolution rule, applied in order:

    1. Highest entity precedence wins (:data:`_ENTITY_PRECEDENCE`).
    2. Ties on precedence go to the longest span.
    3. Remaining ties go to the earliest start offset.

    This keeps the rewrite step's input deterministic so the output
    string only depends on the input text and the enabled entity set.
    """
    rank = {entity: i for i, entity in enumerate(_ENTITY_PRECEDENCE)}
    ordered = sorted(
        matches,
        key=lambda m: (
            -rank.get(m.entity, -1),
            -(m.end - m.start),
            m.start,
        ),
    )
    chosen: list[EntityMatch] = []
    for candidate in ordered:
        if any(
            not (candidate.end <= taken.start or candidate.start >= taken.end)
            for taken in chosen
        ):
            continue
        chosen.append(candidate)
    return chosen
