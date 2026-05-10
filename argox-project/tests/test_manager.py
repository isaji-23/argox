"""Tests for ArgoxManager: registration, lifecycle, policy enforcement, and export."""

from __future__ import annotations

from typing import Any

import pytest

from argox.core.context import RunContext
from argox.core.manager import ArgoxManager
from argox.core.state import AgentRunMetrics, ApiCallRecord
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient, PolicyResult
from argox.interfaces.processor import ArgoxProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str = "hello", input_tokens: int = 5, output_tokens: int = 10):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens


class _FakeAgent:
    name = "test-agent"
    tools: list = []


class _FakePlugin(ArgoxPlugin):
    @property
    def name(self) -> str:
        return "fake"

    def instrument(self, target: Any, metrics: AgentRunMetrics) -> Any:
        return target

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        if isinstance(raw_result, _FakeResponse):
            metrics.api_calls.append(
                ApiCallRecord(
                    call_number=1,
                    input_tokens=raw_result.input_tokens,
                    output_tokens=raw_result.output_tokens,
                    total_tokens=raw_result.total_tokens,
                )
            )

    def extract_output(self, raw_result: Any) -> str:
        return raw_result.text if isinstance(raw_result, _FakeResponse) else str(raw_result)


class _CapturingExporter(ExporterBase):
    def __init__(self) -> None:
        self.exports: list[AgentRunMetrics] = []

    def export(self, metrics: AgentRunMetrics) -> None:
        self.exports.append(metrics)


class _PrefixProcessor(ArgoxProcessor):
    """Prepends a fixed string to input and appends one to output."""

    async def process_input(self, text: str, ctx: RunContext) -> str:
        return f"[IN]{text}"

    async def process_tool_args(self, tool_name: str, args: dict, ctx: RunContext) -> dict:
        return args

    async def process_output(self, text: str, ctx: RunContext) -> str:
        return f"{text}[OUT]"


class _BlockInputPolicy(PolicyClient):
    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.block(reason="input blocked", rule_id="R1")

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.ok()


class _BlockOutputPolicy(PolicyClient):
    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.block(reason="output blocked", rule_id="R2")


class _BlockToolPolicy(PolicyClient):
    def __init__(self, blocked_tool: str) -> None:
        self._blocked = blocked_tool

    async def check_input(self, text: str) -> PolicyResult:
        return PolicyResult.ok()

    async def is_tool_allowed(self, tool_name: str) -> PolicyResult:
        if tool_name == self._blocked:
            return PolicyResult.block(reason="tool blocked", rule_id="R3")
        return PolicyResult.ok()

    async def check_output(self, text: str) -> PolicyResult:
        return PolicyResult.ok()


async def _fake_runner(agent: Any, prompt: str) -> _FakeResponse:
    return _FakeResponse(text=f"response to: {prompt}")


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_plugin(self):
        mgr = ArgoxManager()
        plugin = _FakePlugin()
        mgr.register_plugin(plugin)
        assert "fake" in mgr._plugins

    def test_register_exporter(self):
        mgr = ArgoxManager()
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        assert exp in mgr._exporters

    def test_register_processor(self):
        mgr = ArgoxManager()
        proc = _PrefixProcessor()
        mgr.register_processor(proc)
        assert proc in mgr._processors

    def test_unknown_plugin_raises(self):
        mgr = ArgoxManager()
        with pytest.raises(KeyError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                mgr.run(_FakeAgent(), "prompt", "missing", _fake_runner)
            )


# ---------------------------------------------------------------------------
# Happy-path run
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_returns_output(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        result = await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        assert "response to: hello" in result

    @pytest.mark.asyncio
    async def test_metrics_exported(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        assert len(exp.exports) == 1
        assert exp.exports[0].success is True

    @pytest.mark.asyncio
    async def test_token_metrics_populated(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        metrics = exp.exports[0]
        assert metrics.total_input_tokens == 5
        assert metrics.total_output_tokens == 10

    @pytest.mark.asyncio
    async def test_agent_name_captured(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        await mgr.run(_FakeAgent(), "hi", "fake", _fake_runner)
        assert exp.exports[0].agent_name == "test-agent"

    @pytest.mark.asyncio
    async def test_final_output_stored(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        result = await mgr.run(_FakeAgent(), "q", "fake", _fake_runner)
        assert exp.exports[0].final_output == result


# ---------------------------------------------------------------------------
# Processor pipeline
# ---------------------------------------------------------------------------


class TestProcessors:
    @pytest.mark.asyncio
    async def test_input_transformed(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())

        captured_prompt: list[str] = []

        async def spy_runner(agent: Any, prompt: str) -> _FakeResponse:
            captured_prompt.append(prompt)
            return _FakeResponse()

        mgr.register_processor(_PrefixProcessor())
        await mgr.run(_FakeAgent(), "hello", "fake", spy_runner)
        assert captured_prompt[0] == "[IN]hello"

    @pytest.mark.asyncio
    async def test_output_transformed(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_PrefixProcessor())
        result = await mgr.run(_FakeAgent(), "q", "fake", _fake_runner)
        assert result.endswith("[OUT]")

    @pytest.mark.asyncio
    async def test_multiple_processors_chain(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_processor(_PrefixProcessor())
        mgr.register_processor(_PrefixProcessor())

        captured: list[str] = []

        async def spy_runner(agent: Any, prompt: str) -> _FakeResponse:
            captured.append(prompt)
            return _FakeResponse()

        await mgr.run(_FakeAgent(), "x", "fake", spy_runner)
        assert captured[0] == "[IN][IN]x"


# ---------------------------------------------------------------------------
# Policy enforcement
# ---------------------------------------------------------------------------


class TestPolicy:
    @pytest.mark.asyncio
    async def test_input_blocked_raises(self):
        mgr = ArgoxManager(policy=_BlockInputPolicy())
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        with pytest.raises(PermissionError, match="POLICY:R1"):
            await mgr.run(_FakeAgent(), "bad input", "fake", _fake_runner)

    @pytest.mark.asyncio
    async def test_input_blocked_records_violation(self):
        mgr = ArgoxManager(policy=_BlockInputPolicy())
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        with pytest.raises(PermissionError):
            await mgr.run(_FakeAgent(), "bad input", "fake", _fake_runner)
        assert exp.exports[0].input_policy_passed is False
        assert "input blocked" in exp.exports[0].policy_violations

    @pytest.mark.asyncio
    async def test_output_blocked_raises(self):
        mgr = ArgoxManager(policy=_BlockOutputPolicy())
        mgr.register_plugin(_FakePlugin())
        with pytest.raises(PermissionError, match="POLICY:R2"):
            await mgr.run(_FakeAgent(), "prompt", "fake", _fake_runner)

    @pytest.mark.asyncio
    async def test_output_blocked_metrics_not_success(self):
        mgr = ArgoxManager(policy=_BlockOutputPolicy())
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        with pytest.raises(PermissionError):
            await mgr.run(_FakeAgent(), "prompt", "fake", _fake_runner)
        assert exp.exports[0].output_policy_passed is False
        assert exp.exports[0].success is False

    @pytest.mark.asyncio
    async def test_tool_filtering(self):
        mgr = ArgoxManager(policy=_BlockToolPolicy("dangerous"))
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        await mgr.run(
            _FakeAgent(), "prompt", "fake", _fake_runner,
            tools=["safe", "dangerous"],
        )
        metrics = exp.exports[0]
        assert "safe" in metrics.tools_available
        assert "dangerous" not in metrics.tools_available
        assert any(t["name"] == "dangerous" for t in metrics.tools_blocked)

    @pytest.mark.asyncio
    async def test_no_policy_all_tools_available(self):
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        await mgr.run(
            _FakeAgent(), "prompt", "fake", _fake_runner,
            tools=["tool_a", "tool_b"],
        )
        metrics = exp.exports[0]
        assert set(metrics.tools_available) == {"tool_a", "tool_b"}
        assert metrics.tools_blocked == []

    @pytest.mark.asyncio
    async def test_blocked_tools_removed_from_agent_before_runner(self):
        """Blocked tools must be stripped from agent.tools before runner is called."""

        class _AgentWithTools(_FakeAgent):
            tools = ["safe", "dangerous"]

        agent = _AgentWithTools()
        tools_seen: list[list] = []

        async def spy_runner(ag: Any, prompt: str) -> _FakeResponse:
            tools_seen.append(list(ag.tools))
            return _FakeResponse()

        mgr = ArgoxManager(policy=_BlockToolPolicy("dangerous"))
        mgr.register_plugin(_FakePlugin())
        await mgr.run(agent, "prompt", "fake", spy_runner, tools=["safe", "dangerous"])
        assert tools_seen[0] == ["safe"]

    @pytest.mark.asyncio
    async def test_agent_tools_restored_after_run(self):
        """agent.tools must be back to its original state after run() returns."""

        class _AgentWithTools(_FakeAgent):
            tools = ["safe", "dangerous"]

        agent = _AgentWithTools()
        mgr = ArgoxManager(policy=_BlockToolPolicy("dangerous"))
        mgr.register_plugin(_FakePlugin())
        await mgr.run(agent, "prompt", "fake", _fake_runner, tools=["safe", "dangerous"])
        assert agent.tools == ["safe", "dangerous"]

    @pytest.mark.asyncio
    async def test_agent_tools_restored_even_on_policy_error(self):
        """agent.tools must be restored even when run() raises."""

        class _AgentWithTools(_FakeAgent):
            tools = ["safe", "dangerous"]

        agent = _AgentWithTools()
        mgr = ArgoxManager(policy=_BlockInputPolicy())
        mgr.register_plugin(_FakePlugin())
        with pytest.raises(PermissionError):
            await mgr.run(agent, "bad", "fake", _fake_runner, tools=["safe", "dangerous"])
        assert agent.tools == ["safe", "dangerous"]

    @pytest.mark.asyncio
    async def test_empty_tools_list_not_overridden_by_agent_tools(self):
        """tools=[] must mean no tools, not fall back to agent.tools."""

        class _AgentWithTools(_FakeAgent):
            tools = ["injected_tool"]

        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        await mgr.run(_AgentWithTools(), "prompt", "fake", _fake_runner, tools=[])
        assert exp.exports[0].tools_available == []

    @pytest.mark.asyncio
    async def test_failing_exporter_does_not_mask_run_result(self):
        """A raising exporter must not propagate and must not suppress the return value."""

        class _BrokenExporter(ExporterBase):
            def export(self, metrics: AgentRunMetrics) -> None:
                raise RuntimeError("disk full")

        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_exporter(_BrokenExporter())
        result = await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        assert "response to: hello" in result

    @pytest.mark.asyncio
    async def test_failing_exporter_error_collected_in_metrics(self):
        """Exporter errors must be recorded in metrics.exporter_errors."""

        class _BrokenExporter(ExporterBase):
            def export(self, metrics: AgentRunMetrics) -> None:
                raise RuntimeError("disk full")

        capturing = _CapturingExporter()
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_exporter(_BrokenExporter())
        mgr.register_exporter(capturing)
        await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        assert len(capturing.exports[0].exporter_errors) == 1
        assert "disk full" in capturing.exports[0].exporter_errors[0]

    @pytest.mark.asyncio
    async def test_subsequent_exporters_run_after_failure(self):
        """A raising exporter must not prevent later exporters from running."""

        class _BrokenExporter(ExporterBase):
            def export(self, metrics: AgentRunMetrics) -> None:
                raise RuntimeError("network error")

        capturing = _CapturingExporter()
        mgr = ArgoxManager()
        mgr.register_plugin(_FakePlugin())
        mgr.register_exporter(_BrokenExporter())
        mgr.register_exporter(capturing)
        await mgr.run(_FakeAgent(), "hello", "fake", _fake_runner)
        assert len(capturing.exports) == 1

    @pytest.mark.asyncio
    async def test_exporter_called_even_on_input_block(self):
        mgr = ArgoxManager(policy=_BlockInputPolicy())
        mgr.register_plugin(_FakePlugin())
        exp = _CapturingExporter()
        mgr.register_exporter(exp)
        with pytest.raises(PermissionError):
            await mgr.run(_FakeAgent(), "bad", "fake", _fake_runner)
        assert len(exp.exports) == 1
