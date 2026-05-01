"""Tests for the core data model: ToolCallRecord, ApiCallRecord, AgentRunMetrics."""

from __future__ import annotations

import time
import uuid

import pytest

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord


class TestToolCallRecord:
    def test_duration_when_complete(self):
        rec = ToolCallRecord(name="search", start=1000.0, end=1002.5)
        assert rec.duration == pytest.approx(2.5)

    def test_duration_when_in_progress(self):
        rec = ToolCallRecord(name="search", start=1000.0)
        assert rec.duration == 0.0

    def test_defaults(self):
        rec = ToolCallRecord(name="my_tool", start=0.0)
        assert rec.end is None
        assert rec.result is None
        assert rec.blocked is False
        assert rec.block_reason is None

    def test_blocked_fields(self):
        rec = ToolCallRecord(
            name="exec",
            start=1.0,
            blocked=True,
            block_reason="policy POL-01",
        )
        assert rec.blocked is True
        assert rec.block_reason == "policy POL-01"


class TestApiCallRecord:
    def test_fields_stored(self):
        rec = ApiCallRecord(
            call_number=1,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
        )
        assert rec.call_number == 1
        assert rec.input_tokens == 100
        assert rec.output_tokens == 50
        assert rec.total_tokens == 150


class TestAgentRunMetrics:
    def test_default_construction(self):
        m = AgentRunMetrics(agent_name="bot")
        assert m.agent_name == "bot"
        assert m.api_calls == []
        assert m.tools_called == []
        assert m.tools_available == []
        assert m.tools_blocked == []
        assert m.policy_violations == []
        assert m.success is False
        assert m.input_policy_passed is True
        assert m.output_policy_passed is True

    def test_run_id_is_valid_uuid(self):
        m = AgentRunMetrics()
        uuid.UUID(m.run_id)  # raises ValueError if invalid

    def test_run_ids_are_unique(self):
        assert AgentRunMetrics().run_id != AgentRunMetrics().run_id

    def test_timestamp_is_iso8601(self):
        from datetime import datetime
        m = AgentRunMetrics()
        # Should not raise
        datetime.fromisoformat(m.timestamp)

    def test_duration_when_finished(self):
        m = AgentRunMetrics()
        m.start_time = 1000.0
        m.end_time = 1005.0
        assert m.duration == pytest.approx(5.0)

    def test_duration_when_running(self):
        m = AgentRunMetrics()
        m.end_time = None
        assert m.duration == 0.0

    def test_token_aggregation(self):
        m = AgentRunMetrics()
        m.api_calls = [
            ApiCallRecord(call_number=1, input_tokens=100, output_tokens=50, total_tokens=150),
            ApiCallRecord(call_number=2, input_tokens=200, output_tokens=80, total_tokens=280),
        ]
        assert m.total_input_tokens == 300
        assert m.total_output_tokens == 130
        assert m.total_tokens == 430

    def test_token_aggregation_empty(self):
        m = AgentRunMetrics()
        assert m.total_input_tokens == 0
        assert m.total_output_tokens == 0
        assert m.total_tokens == 0

    def test_collections_are_independent(self):
        """Two instances must not share the same list objects."""
        a = AgentRunMetrics()
        b = AgentRunMetrics()
        a.api_calls.append(ApiCallRecord(1, 1, 1, 2))
        assert b.api_calls == []

    def test_to_dict_structure(self):
        m = AgentRunMetrics(
            agent_name="bot",
            run_id="abc-123",
            agent_version="1.0.0",
            prompt="hello",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        m.start_time = 1000.0
        m.end_time = 1003.0
        m.final_output = "world"
        m.success = True
        m.api_calls = [ApiCallRecord(1, 10, 5, 15)]
        m.tools_available = ["search"]
        m.tools_blocked = [{"name": "exec", "reason": "blocked"}]
        m.tools_called = [ToolCallRecord(name="search", start=1000.0, end=1001.0, result="ok")]
        m.policy_violations = ["POL-01: foo"]

        d = m.to_dict()

        assert d["run_id"] == "abc-123"
        assert d["agent_name"] == "bot"
        assert d["agent_version"] == "1.0.0"
        assert d["prompt"] == "hello"
        assert d["final_output"] == "world"
        assert d["success"] is True
        assert d["duration_seconds"] == pytest.approx(3.0)

        tokens = d["tokens"]
        assert tokens["input"] == 10
        assert tokens["output"] == 5
        assert tokens["total"] == 15
        assert tokens["by_api_call"] == [{"call": 1, "input": 10, "output": 5, "total": 15}]

        tools = d["tools"]
        assert tools["available"] == ["search"]
        assert tools["blocked"] == [{"name": "exec", "reason": "blocked"}]
        assert len(tools["called"]) == 1
        assert tools["called"][0]["name"] == "search"
        assert tools["called"][0]["duration"] == pytest.approx(1.0)
        assert tools["called"][0]["result"] == "ok"
        assert tools["called"][0]["blocked"] is False

        policies = d["policies"]
        assert policies["input_passed"] is True
        assert policies["output_passed"] is True
        assert policies["violations"] == ["POL-01: foo"]

    def test_to_dict_empty_run(self):
        m = AgentRunMetrics(agent_name="bot")
        d = m.to_dict()
        assert d["tokens"]["by_api_call"] == []
        assert d["tools"]["called"] == []
        assert d["policies"]["violations"] == []
