"""PROC-01 — PiiRedactionProcessor unit tests."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import pytest
from argox.core.context import RunContext
from argox.processors import (
    Detector,
    EntityMatch,
    PiiRedactionProcessor,
    RedactionMode,
)
from argox.processors.pii import _DefaultRegexDetector  # noqa: PLC2701
from argox.semconv.attributes import (
    ARGOX_PII_REDACTIONS,
    ARGOX_PROCESSOR_NAME,
    ARGOX_PROCESSOR_PHASE,
    ARGOX_PROCESSOR_TOOL_NAME,
    EVENT_PII_REDACTED,
)
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(run_id="run-1", agent_name="test-agent")


# ---------------------------------------------------------------------------
# Entity coverage — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,entity",
    [
        ("contact john.doe@example.com today", "EMAIL"),
        ("call +14155552671 now", "PHONE"),
        ("server 192.168.1.1 responded", "IPV4"),
        (
            "addr 2001:0db8:85a3:0000:0000:8a2e:0370:7334 ok",
            "IPV6",
        ),
        ("iban ES9121000418450200051332 here", "IBAN"),
        ("card 4111 1111 1111 1111 expires", "CREDIT_CARD"),
        ("dni 12345678Z citizen", "ES_DNI"),
        ("nie X1234567L resident", "ES_NIE"),
    ],
)
async def test_redacts_each_entity_in_mask_mode(
    text: str, entity: str, ctx: RunContext
) -> None:
    processor = PiiRedactionProcessor()
    out = await processor.process_output(text, ctx)
    assert f"[REDACTED:{entity}]" in out


# ---------------------------------------------------------------------------
# Luhn enforcement on credit cards
# ---------------------------------------------------------------------------


async def test_credit_card_invalid_luhn_is_not_redacted(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["CREDIT_CARD"])
    out = await processor.process_output("card 4111 1111 1111 1112 done", ctx)
    assert "[REDACTED:CREDIT_CARD]" not in out
    assert "4111 1111 1111 1112" in out


async def test_credit_card_valid_luhn_with_dashes(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["CREDIT_CARD"])
    out = await processor.process_output("card 4111-1111-1111-1111 ok", ctx)
    assert "[REDACTED:CREDIT_CARD]" in out


# ---------------------------------------------------------------------------
# IBAN formats — spaced, lowercase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "iban ES9121000418450200051332 ok",
        "iban ES91 2100 0418 4502 0005 1332 ok",
        "iban es91 2100 0418 4502 0005 1332 ok",
    ],
)
async def test_iban_accepts_grouped_and_lowercase_formats(
    text: str, ctx: RunContext,
) -> None:
    processor = PiiRedactionProcessor(entities=["IBAN"])
    out = await processor.process_output(text, ctx)
    assert "[REDACTED:IBAN]" in out


async def test_iban_rejects_too_short_strings(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["IBAN"])
    # 14 alphanumerics after stripping is below the 15-char minimum.
    out = await processor.process_output("code ES912100041845 hi", ctx)
    assert "[REDACTED:IBAN]" not in out


async def test_iban_rejects_failing_mod97_checksum(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["IBAN"])
    # Same shape as a real IBAN but the ISO 13616 mod-97 check fails.
    out = await processor.process_output("ref ES0021000418450200051332 hi", ctx)
    assert "[REDACTED:IBAN]" not in out


async def test_iban_mod97_accepts_other_countries(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["IBAN"])
    out = await processor.process_output("iban DE89370400440532013000 ok", ctx)
    assert "[REDACTED:IBAN]" in out


# ---------------------------------------------------------------------------
# IPv4 octet validation
# ---------------------------------------------------------------------------


async def test_invalid_ipv4_octets_are_not_redacted(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["IPV4"])
    out = await processor.process_output("bad 999.1.1.1 here", ctx)
    assert "[REDACTED:IPV4]" not in out


# ---------------------------------------------------------------------------
# Spanish DNI / NIE control-letter validation
# ---------------------------------------------------------------------------


async def test_dni_wrong_control_letter_is_not_redacted(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["ES_DNI"])
    out = await processor.process_output("dni 12345678A bad", ctx)
    assert "[REDACTED:ES_DNI]" not in out


async def test_nie_wrong_control_letter_is_not_redacted(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["ES_NIE"])
    out = await processor.process_output("nie X1234567A bad", ctx)
    assert "[REDACTED:ES_NIE]" not in out


# ---------------------------------------------------------------------------
# Recursion through nested tool_args structures
# ---------------------------------------------------------------------------


async def test_process_tool_args_recurses_into_nested_dicts_and_lists(
    ctx: RunContext,
) -> None:
    processor = PiiRedactionProcessor(entities=["EMAIL", "IPV4"])
    args = {
        "user": {"email": "user@example.com", "id": 42},
        "ips": ["10.0.0.1", "not-an-ip"],
        "tags": ("admin", "owner@example.com"),
        "count": 7,
    }
    out = await processor.process_tool_args("log", args, ctx)
    assert out["user"]["email"] == "[REDACTED:EMAIL]"
    assert out["user"]["id"] == 42
    assert out["ips"] == ["[REDACTED:IPV4]", "not-an-ip"]
    assert out["tags"] == ("admin", "[REDACTED:EMAIL]")
    assert out["count"] == 7


async def test_process_tool_args_non_string_scalars_pass_through(
    ctx: RunContext,
) -> None:
    processor = PiiRedactionProcessor()
    args = {"flag": True, "count": 3, "ratio": 1.5, "missing": None}
    out = await processor.process_tool_args("op", args, ctx)
    assert out == args


# ---------------------------------------------------------------------------
# Replacement modes
# ---------------------------------------------------------------------------


async def test_mode_mask_uses_entity_label(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(mode=RedactionMode.MASK)
    out = await processor.process_output("ping a@b.com", ctx)
    assert out == "ping [REDACTED:EMAIL]"


async def test_mode_hash_is_deterministic_with_salt(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(
        mode=RedactionMode.HASH, hash_salt="pepper", entities=["EMAIL"],
    )
    out1 = await processor.process_output("a@b.com a@b.com", ctx)
    out2 = await processor.process_output("a@b.com", ctx)
    expected = hashlib.sha256(("a@b.com" + "pepper").encode("utf-8")).hexdigest()[:12]
    assert out1 == f"{expected} {expected}"
    assert out2 == expected


@pytest.mark.parametrize(
    "entity,value_a,value_b",
    [
        ("EMAIL", "user@example.com", "USER@Example.COM"),
        ("CREDIT_CARD", "4111 1111 1111 1111", "4111-1111-1111-1111"),
        ("IBAN", "ES9121000418450200051332", "ES91 2100 0418 4502 0005 1332"),
        ("IBAN", "ES9121000418450200051332", "es91 2100 0418 4502 0005 1332"),
    ],
)
async def test_mode_hash_normalizes_per_entity(
    entity: str, value_a: str, value_b: str, ctx: RunContext,
) -> None:
    """The same logical PII hashes identically regardless of formatting."""
    processor = PiiRedactionProcessor(
        mode=RedactionMode.HASH, hash_salt="s", entities=[entity],
    )
    out_a = await processor.process_output(value_a, ctx)
    out_b = await processor.process_output(value_b, ctx)
    assert out_a == out_b
    assert value_a not in out_a  # raw value never appears in the digest


async def test_mode_hash_changes_with_different_salt(ctx: RunContext) -> None:
    a = PiiRedactionProcessor(mode=RedactionMode.HASH, hash_salt="x", entities=["EMAIL"])
    b = PiiRedactionProcessor(mode=RedactionMode.HASH, hash_salt="y", entities=["EMAIL"])
    out_a = await a.process_output("a@b.com", ctx)
    out_b = await b.process_output("a@b.com", ctx)
    assert out_a != out_b


async def test_mode_drop_removes_the_match(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(mode=RedactionMode.DROP, entities=["EMAIL"])
    out = await processor.process_output("from a@b.com end", ctx)
    assert out == "from  end"


# ---------------------------------------------------------------------------
# Opt-in input redaction
# ---------------------------------------------------------------------------


async def test_process_input_pass_through_by_default(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor()
    out = await processor.process_input("hello a@b.com world", ctx)
    assert out == "hello a@b.com world"


async def test_process_input_redacts_when_enabled(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(redact_input=True)
    out = await processor.process_input("hello a@b.com world", ctx)
    assert out == "hello [REDACTED:EMAIL] world"


# ---------------------------------------------------------------------------
# Fail-open semantics — detector errors do not propagate
# ---------------------------------------------------------------------------


class _ExplodingDetector:
    """Detector that always raises — used to exercise fail-open."""

    def detect(self, text: str, entities: Sequence[str]) -> list[EntityMatch]:
        raise RuntimeError("boom")


async def test_detector_failure_returns_original_text(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(detector=_ExplodingDetector())
    out = await processor.process_output("contact a@b.com please", ctx)
    assert out == "contact a@b.com please"


async def test_detector_failure_in_tool_args_returns_original(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(detector=_ExplodingDetector())
    args = {"email": "a@b.com"}
    out = await processor.process_tool_args("op", args, ctx)
    assert out == {"email": "a@b.com"}


# ---------------------------------------------------------------------------
# Entity filtering — explicit catalogue is honored
# ---------------------------------------------------------------------------


async def test_entities_filter_skips_disabled_kinds(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(entities=["EMAIL"])
    out = await processor.process_output("a@b.com and +14155552671", ctx)
    assert "[REDACTED:EMAIL]" in out
    assert "+14155552671" in out
    assert "[REDACTED:PHONE]" not in out


def test_entities_as_string_raises_type_error() -> None:
    """A bare string would silently iterate as characters; reject it loudly."""
    with pytest.raises(TypeError, match="iterable of labels"):
        PiiRedactionProcessor(entities="EMAIL")


async def test_mode_accepts_raw_string_value(ctx: RunContext) -> None:
    """A raw mode string ('hash') must be coerced to the enum member.

    Without coercion, the ``is`` comparisons in ``_replacement`` would
    miss the string and fall through to the defensive MASK branch.
    """
    processor = PiiRedactionProcessor(
        mode="hash", hash_salt="x", entities=["EMAIL"],
    )
    out = await processor.process_output("a@b.com", ctx)
    assert out != "a@b.com"
    assert not out.startswith("[REDACTED")


def test_mode_unknown_string_raises_type_error() -> None:
    with pytest.raises(TypeError, match="RedactionMode"):
        PiiRedactionProcessor(mode="hashh")


def test_mode_non_string_non_enum_raises_type_error() -> None:
    with pytest.raises(TypeError, match="RedactionMode"):
        PiiRedactionProcessor(mode=42)


# ---------------------------------------------------------------------------
# Custom detector contract
# ---------------------------------------------------------------------------


class _ConstantDetector:
    def detect(self, text: str, entities: Sequence[str]) -> list[EntityMatch]:
        out: list[EntityMatch] = []
        marker = "SECRET"
        start = text.find(marker)
        if start >= 0:
            out.append(EntityMatch(start, start + len(marker), "CUSTOM", marker))
        return out


async def test_custom_detector_drives_redaction(ctx: RunContext) -> None:
    processor = PiiRedactionProcessor(
        detector=_ConstantDetector(), entities=["CUSTOM"],
    )
    out = await processor.process_output("the SECRET is safe", ctx)
    assert out == "the [REDACTED:CUSTOM] is safe"


# ---------------------------------------------------------------------------
# Detector returns deterministic matches for the default catalogue
# ---------------------------------------------------------------------------


def test_default_detector_implements_protocol() -> None:
    detector: Detector = _DefaultRegexDetector()
    matches = detector.detect("see a@b.com now", ["EMAIL"])
    assert len(matches) == 1
    assert matches[0].entity == "EMAIL"
    assert matches[0].value == "a@b.com"


# ---------------------------------------------------------------------------
# Span event emission — argox.pii.redacted carries counts, never raw PII
# ---------------------------------------------------------------------------


_TRACE_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _install_in_memory_tracer_provider():
    """Install an in-memory TracerProvider for this module only.

    OTel's ``set_tracer_provider`` is set-once globally, so we bypass the
    guard via the private ``_TRACER_PROVIDER_SET_ONCE`` attribute and
    restore the previous state when the module's tests finish, matching
    the pattern used by ``tests/test_processor_pipeline.py``.
    """
    saved_provider = trace._TRACER_PROVIDER  # type: ignore[attr-defined]
    saved_set_once = trace._TRACER_PROVIDER_SET_ONCE._done  # type: ignore[attr-defined]

    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(_TRACE_EXPORTER))
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace.set_tracer_provider(provider)

    yield

    trace._TRACER_PROVIDER = saved_provider  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE._done = saved_set_once  # type: ignore[attr-defined]
    _TRACE_EXPORTER.clear()


@pytest.fixture
def span_exporter():
    _TRACE_EXPORTER.clear()
    yield _TRACE_EXPORTER
    _TRACE_EXPORTER.clear()


async def _run_in_span(coro_fn):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-span"):
        return await coro_fn()


async def test_output_emits_redaction_event_with_counts_no_raw_pii(
    ctx: RunContext, span_exporter: InMemorySpanExporter,
) -> None:
    processor = PiiRedactionProcessor()

    async def run():
        return await processor.process_output(
            "mail a@b.com and a@c.com and ip 10.0.0.1", ctx,
        )

    out = await _run_in_span(run)
    assert "[REDACTED:EMAIL]" in out
    assert "[REDACTED:IPV4]" in out

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    events = [e for e in spans[0].events if e.name == EVENT_PII_REDACTED]
    assert len(events) == 1
    attrs = dict(events[0].attributes or {})
    assert attrs[ARGOX_PROCESSOR_NAME] == "PiiRedactionProcessor"
    assert attrs[ARGOX_PROCESSOR_PHASE] == "output"
    assert set(attrs[ARGOX_PII_REDACTIONS]) == {"EMAIL:2", "IPV4:1"}
    # Tool name attribute is omitted on output/input phases.
    assert ARGOX_PROCESSOR_TOOL_NAME not in attrs
    # Raw PII must not appear anywhere in the event attributes.
    for value in attrs.values():
        rendered = str(value)
        assert "a@b.com" not in rendered
        assert "a@c.com" not in rendered
        assert "10.0.0.1" not in rendered


async def test_tool_args_event_includes_tool_name(
    ctx: RunContext, span_exporter: InMemorySpanExporter,
) -> None:
    processor = PiiRedactionProcessor(entities=["EMAIL"])

    async def run():
        return await processor.process_tool_args(
            "log_user_activity", {"email": "user@example.com"}, ctx,
        )

    await _run_in_span(run)

    spans = span_exporter.get_finished_spans()
    events = [e for e in spans[0].events if e.name == EVENT_PII_REDACTED]
    assert len(events) == 1
    attrs = dict(events[0].attributes or {})
    assert attrs[ARGOX_PROCESSOR_PHASE] == "tool_args"
    assert attrs[ARGOX_PROCESSOR_TOOL_NAME] == "log_user_activity"
    assert attrs[ARGOX_PROCESSOR_NAME] == "PiiRedactionProcessor"
    assert list(attrs[ARGOX_PII_REDACTIONS]) == ["EMAIL:1"]


async def test_no_redactions_emits_no_event(
    ctx: RunContext, span_exporter: InMemorySpanExporter,
) -> None:
    processor = PiiRedactionProcessor()

    async def run():
        return await processor.process_output("nothing to scrub here", ctx)

    await _run_in_span(run)

    spans = span_exporter.get_finished_spans()
    pii_events = [e for e in spans[0].events if e.name == EVENT_PII_REDACTED]
    assert pii_events == []
