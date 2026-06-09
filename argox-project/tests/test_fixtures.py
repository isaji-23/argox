"""Verify shared fixtures satisfy their interface contracts."""

from __future__ import annotations

import pytest

from argox.core.state import AgentRunMetrics


class TestFakeLLMResponse:
    def test_has_non_empty_text(self, fake_llm_response):
        assert isinstance(fake_llm_response.text, str)
        assert fake_llm_response.text

    def test_token_counts_are_positive(self, fake_llm_response):
        assert fake_llm_response.input_tokens > 0
        assert fake_llm_response.output_tokens > 0

    def test_total_tokens_is_sum(self, fake_llm_response):
        assert fake_llm_response.total_tokens == (
            fake_llm_response.input_tokens + fake_llm_response.output_tokens
        )


class TestFakeOpenAIAgent:
    def test_has_name(self, fake_agent):
        assert fake_agent.name == "test-agent"

    def test_tools_list_is_empty_by_default(self, fake_agent):
        assert fake_agent.tools == []


class TestAgentMetrics:
    def test_starts_with_empty_collections(self, agent_metrics):
        assert agent_metrics.api_calls == []
        assert agent_metrics.tools_called == []
        assert agent_metrics.policy_violations == []


class TestStubPlugin:
    def test_name(self, stub_plugin):
        assert stub_plugin.name == "stub"

    def test_instrument_returns_target_unchanged(self, stub_plugin, fake_agent, agent_metrics):
        result = stub_plugin.instrument(fake_agent, agent_metrics)
        assert result is fake_agent

    def test_extract_tokens_populates_api_calls(self, stub_plugin, fake_llm_response, agent_metrics):
        stub_plugin.extract_tokens(fake_llm_response, agent_metrics)
        assert len(agent_metrics.api_calls) == 1
        record = agent_metrics.api_calls[0]
        assert record.call_number == 1
        assert record.input_tokens == fake_llm_response.input_tokens
        assert record.output_tokens == fake_llm_response.output_tokens
        assert record.total_tokens == fake_llm_response.total_tokens

    def test_extract_output_returns_response_text(self, stub_plugin, fake_llm_response):
        assert stub_plugin.extract_output(fake_llm_response) == fake_llm_response.text


class TestStubProcessor:
    async def test_process_input_is_passthrough(self, stub_processor):
        result = await stub_processor.process_input("hello", ctx=None)
        assert result == "hello"

    async def test_process_tool_args_is_passthrough(self, stub_processor):
        args = {"key": "value"}
        result = await stub_processor.process_tool_args("my_tool", args, ctx=None)
        assert result == args

    async def test_process_output_is_passthrough(self, stub_processor):
        result = await stub_processor.process_output("response", ctx=None)
        assert result == "response"


class TestStubPolicyClient:
    async def test_check_input_passes(self, stub_policy):
        result = await stub_policy.check_input("any input")
        assert result.passed is True

    async def test_is_tool_allowed_passes(self, stub_policy):
        result = await stub_policy.is_tool_allowed("any_tool")
        assert result.passed is True

    async def test_check_output_passes(self, stub_policy):
        result = await stub_policy.check_output("any output")
        assert result.passed is True


class TestCapturingExporter:
    def test_starts_with_no_exports(self, capturing_exporter):
        assert capturing_exporter.exports == []

    def test_export_captures_metrics(self, capturing_exporter, agent_metrics):
        capturing_exporter.export(agent_metrics)
        assert len(capturing_exporter.exports) == 1
        assert capturing_exporter.exports[0] is agent_metrics

    def test_export_accumulates_multiple_runs(self, capturing_exporter, agent_metrics):
        second = AgentRunMetrics(agent_name="agent-2")
        capturing_exporter.export(agent_metrics)
        capturing_exporter.export(second)
        assert len(capturing_exporter.exports) == 2
        assert capturing_exporter.exports[1].agent_name == "agent-2"
