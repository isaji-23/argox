"""Strategy A (isolated): microbenchmarks per component in isolation.

Each benchmark tests a single processor or interface method without
going through the full manager lifecycle.
"""

from __future__ import annotations

import pytest

from argox.processors.pii import PiiRedactionProcessor


@pytest.mark.benchmark(group="processors")
def test_pii_processor_short_input(benchmark, bench_loop, run_context):
    """PII redaction on a short string (<100 chars) containing one phone number."""
    processor = PiiRedactionProcessor()
    benchmark(
        lambda: bench_loop.run_until_complete(
            processor.process_input("Call me at 555-1234", run_context)
        )
    )


@pytest.mark.benchmark(group="processors")
def test_pii_processor_medium_input(benchmark, bench_loop, run_context):
    """PII redaction on a medium string (~500 chars) with mixed PII."""
    processor = PiiRedactionProcessor()
    text = "Email a@b.com or call 555-1234. " * 15
    benchmark(lambda: bench_loop.run_until_complete(processor.process_input(text, run_context)))


@pytest.mark.benchmark(group="processors")
def test_pii_processor_long_input(benchmark, bench_loop, run_context):
    """PII redaction on a long string (~10k chars)."""
    processor = PiiRedactionProcessor()
    long_text = "My email is test@example.com. " * 333
    benchmark(lambda: bench_loop.run_until_complete(processor.process_input(long_text, run_context)))


@pytest.mark.benchmark(group="processors")
def test_pii_processor_clean_input(benchmark, bench_loop, run_context):
    """PII redaction on text with no PII — measures regex-scan baseline cost."""
    processor = PiiRedactionProcessor()
    clean_text = "The quick brown fox jumps over the lazy dog. " * 100
    benchmark(lambda: bench_loop.run_until_complete(processor.process_input(clean_text, run_context)))


@pytest.mark.benchmark(group="processors")
def test_pii_processor_tool_args(benchmark, bench_loop, run_context):
    """PII redaction on a tool-args dict with nested strings."""
    processor = PiiRedactionProcessor()
    args = {
        "message": "Contact me at user@example.com",
        "metadata": {"phone": "555-9876", "note": "no pii here"},
    }
    benchmark(
        lambda: bench_loop.run_until_complete(
            processor.process_tool_args("send_email", args, run_context)
        )
    )
