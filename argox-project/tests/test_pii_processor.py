"""PROC-01 — PiiRedactionProcessor unit tests."""

from __future__ import annotations

import hashlib
from typing import List, Sequence

import pytest

from argox.core.context import RunContext
from argox.processors import (
    Detector,
    EntityMatch,
    PiiRedactionProcessor,
    RedactionMode,
)
from argox.processors.pii import _DefaultRegexDetector  # noqa: PLC2701


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

    def detect(self, text: str, entities: Sequence[str]) -> List[EntityMatch]:
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


# ---------------------------------------------------------------------------
# Custom detector contract
# ---------------------------------------------------------------------------


class _ConstantDetector:
    def detect(self, text: str, entities: Sequence[str]) -> List[EntityMatch]:
        out: List[EntityMatch] = []
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
