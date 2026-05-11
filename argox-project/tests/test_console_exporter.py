"""Tests for the human-readable ConsoleSpanExporter wrapper."""

from __future__ import annotations

import io

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import StatusCode

from argox.exporters import ConsoleSpanExporter
from argox.semconv.attributes import (
    ARGOX_POLICY_DECISION,
    ARGOX_POLICY_RULE_ID,
    ARGOX_RUN_BLOCKED_TOOLS,
)


def _make_tracer(exporter: ConsoleSpanExporter):
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test")


class TestConsoleSpanExporter:
    def test_emits_span_name(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("argox.agent.run"):
            pass
        out = buf.getvalue()
        assert "[argox]" in out
        assert "argox.agent.run" in out

    def test_emits_duration(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("op"):
            pass
        out = buf.getvalue()
        assert "ms)" in out

    def test_emits_token_usage(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("llm.call") as span:
            span.set_attribute("gen_ai.usage.input_tokens", 120)
            span.set_attribute("gen_ai.usage.output_tokens", 45)
        out = buf.getvalue()
        assert "tokens=120/45" in out

    def test_emits_policy_decision(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("policy.input") as span:
            span.set_attribute(ARGOX_POLICY_DECISION, "block")
            span.set_attribute(ARGOX_POLICY_RULE_ID, "R-42")
        out = buf.getvalue()
        assert "policy=block[R-42]" in out

    def test_policy_without_rule_id(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("policy.output") as span:
            span.set_attribute(ARGOX_POLICY_DECISION, "ok")
        out = buf.getvalue()
        assert "policy=ok" in out
        assert "policy=ok[" not in out

    def test_emits_blocked_tools(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("agent.run") as span:
            span.set_attribute(ARGOX_RUN_BLOCKED_TOOLS, ["shell", "fs.write"])
        out = buf.getvalue()
        assert "blocked_tools=" in out
        assert "shell" in out
        assert "fs.write" in out

    def test_emits_status_ok_by_default(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("op"):
            pass
        out = buf.getvalue()
        # OTel default is UNSET; explicit OK or UNSET are both acceptable values.
        assert "status=" in out

    def test_emits_status_error(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("op") as span:
            from opentelemetry.trace import Status
            span.set_status(Status(StatusCode.ERROR, "boom"))
        out = buf.getvalue()
        assert "status=ERROR" in out

    def test_single_line_per_span(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("a"):
            pass
        with tracer.start_as_current_span("b"):
            pass
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        assert len(lines) == 2

    def test_no_token_section_when_attrs_absent(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("op"):
            pass
        assert "tokens=" not in buf.getvalue()

    def test_no_policy_section_when_attrs_absent(self):
        buf = io.StringIO()
        tracer = _make_tracer(ConsoleSpanExporter(out=buf))
        with tracer.start_as_current_span("op"):
            pass
        assert "policy=" not in buf.getvalue()
