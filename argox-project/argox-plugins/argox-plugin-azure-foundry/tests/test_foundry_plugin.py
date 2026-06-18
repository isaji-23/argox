import pytest
import time
import sys
from unittest.mock import MagicMock, AsyncMock

# Mocking Azure SDK because it might not be installed
class MockFunctionTool:
    def __init__(self, functions=None):
        self.definitions = []
        self._functions = {}
        if functions:
            for f in functions:
                self._functions[f.__name__] = f

# Pre-mock the module so monkeypatch can find it
mock_models = MagicMock()
mock_models.FunctionTool = MockFunctionTool
sys.modules["azure.ai"] = MagicMock()
sys.modules["azure.ai.projects"] = MagicMock()
sys.modules["azure.ai.projects.models"] = mock_models

from argox_azure_foundry.plugin import ArgoxAzureFoundryPlugin
from argox.core.state import AgentRunMetrics, ToolCallRecord

@pytest.fixture
def plugin():
    return ArgoxAzureFoundryPlugin()

@pytest.fixture
def metrics():
    return AgentRunMetrics(agent_name="test-agent")

def test_plugin_name(plugin):
    assert plugin.name == "azure-foundry"

@pytest.mark.asyncio
async def test_instrument_wraps_tools(plugin, metrics, monkeypatch):
    async def sample_tool(location: str):
        return f"Weather in {location} is fine"
    
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    # Tool args runner
    async def tool_args_runner(name, args):
        args["location"] = "London"
        return args
    
    plugin.instrument(mock_agent, metrics, tool_args_runner)
    
    assert len(mock_agent.tools) == 1
    wrapped_tool = mock_agent.tools[0]
    assert isinstance(wrapped_tool, MockFunctionTool)
    
    # Verify the function is wrapped
    wrapped_func = wrapped_tool._functions["sample_tool"]
    
    result = await wrapped_func(location="Paris")
    
    assert result == "Weather in London is fine"
    assert len(metrics.tools_called) == 1
    assert metrics.tools_called[0].name == "sample_tool"
    assert metrics.tools_called[0].result == "Weather in London is fine"

def test_extract_tokens(plugin, metrics):
    mock_run = MagicMock()
    mock_run.usage = MagicMock()
    mock_run.usage.prompt_tokens = 10
    mock_run.usage.completion_tokens = 5
    mock_run.usage.total_tokens = 15
    
    plugin.extract_tokens(mock_run, metrics)
    
    assert len(metrics.api_calls) == 1
    assert metrics.api_calls[0].input_tokens == 10
    assert metrics.api_calls[0].output_tokens == 5
    assert metrics.api_calls[0].total_tokens == 15

def test_extract_output(plugin):
    # Case 1: String
    assert plugin.extract_output("hello") == "hello"
    
    # Case 2: Object with content
    mock_res = MagicMock()
    mock_res.content = "world"
    assert plugin.extract_output(mock_res) == "world"
    
    # Case 3: Empty
    assert plugin.extract_output(None) == ""
