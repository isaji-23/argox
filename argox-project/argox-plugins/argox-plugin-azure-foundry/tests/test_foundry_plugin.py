import pytest
import time
import sys
import copy
import asyncio
from unittest.mock import MagicMock

# Mocking Azure SDK because it might not be installed
class MockFunctionTool:
    def __init__(self, name="mock_tool", functions=None):
        self.name = name
        self.definitions = [{"name": name, "parameters": {}}]
        self._functions = {}
        if functions:
            for f in functions:
                self._functions[f.__name__] = f

class MockAsyncFunctionTool(MockFunctionTool):
    pass

@pytest.fixture(autouse=True)
def mock_azure_sdk(monkeypatch):
    mock_models = MagicMock()
    mock_models.FunctionTool = MockFunctionTool
    mock_models.AsyncFunctionTool = MockAsyncFunctionTool
    monkeypatch.setitem(sys.modules, "azure", MagicMock())
    monkeypatch.setitem(sys.modules, "azure.ai", MagicMock())
    monkeypatch.setitem(sys.modules, "azure.ai.projects", MagicMock())
    monkeypatch.setitem(sys.modules, "azure.ai.projects.models", mock_models)

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

@pytest.fixture(scope="module")
def _module_exporter() -> InMemorySpanExporter:
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter

@pytest.fixture
def span_exporter(_module_exporter):
    _module_exporter.clear()
    yield _module_exporter
    _module_exporter.clear()

from argox_azure_foundry.plugin import ArgoxAzureFoundryPlugin
from argox.core.state import AgentRunMetrics

@pytest.fixture
def plugin():
    return ArgoxAzureFoundryPlugin()

@pytest.fixture
def metrics():
    return AgentRunMetrics(agent_name="test-agent")

def test_plugin_name(plugin):
    assert plugin.name == "azure-foundry"

@pytest.mark.asyncio
async def test_instrument_wraps_async_tools(plugin, metrics):
    async def sample_tool(location: str):
        return f"Weather in {location} is fine"
    
    mock_agent = MagicMock()
    mock_tool = MockAsyncFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    # Tool args runner
    async def tool_args_runner(name, args):
        args["location"] = "London"
        return args
    
    plugin.instrument(mock_agent, metrics, tool_args_runner)
    
    assert len(mock_agent.tools) == 1
    wrapped_tool = mock_agent.tools[0]
    assert isinstance(wrapped_tool, MockAsyncFunctionTool)
    
    # Verify the function is wrapped
    wrapped_func = wrapped_tool._functions["sample_tool"]
    
    result = await wrapped_func(location="Paris")
    
    assert result == "Weather in London is fine"
    assert len(metrics.tools_called) == 1
    assert metrics.tools_called[0].name == "sample_tool"
    assert metrics.tools_called[0].result == "Weather in London is fine"

def test_instrument_wraps_sync_tools(plugin, metrics):
    def sample_tool(location: str):
        return f"Weather in {location} is fine"
    
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
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
    
    result = wrapped_func(location="Paris")
    
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

def test_extract_output_with_blocks(plugin):
    # Case 4: Content blocks
    mock_res = MagicMock()
    mock_block = MagicMock()
    mock_block.text = MagicMock()
    mock_block.text.value = "block_content"
    mock_res.content = [mock_block]
    
    assert plugin.extract_output(mock_res) == "block_content"

def test_instrument_positional_arguments(plugin, metrics):
    def sample_tool(location: str, temperature: float = 20.0):
        return f"Weather in {location} is {temperature}C"
    
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    async def tool_args_runner(name, args):
        assert "location" in args
        assert "temperature" in args
        args["location"] = "Madrid"
        args["temperature"] = 35.0
        return args
        
    plugin.instrument(mock_agent, metrics, tool_args_runner)
    wrapped_func = mock_agent.tools[0]._functions["sample_tool"]
    
    # Pass location positionally, temperature as keyword
    result = wrapped_func("Paris", temperature=15.0)
    assert result == "Weather in Madrid is 35.0C"

def test_instrument_sync_tool_async_function(plugin, metrics):
    async def sample_tool(location: str):
        return f"Async result for {location}"
    
    mock_agent = MagicMock()
    # It is a FunctionTool (sync wrapper) but holds an async function
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    plugin.instrument(mock_agent, metrics)
    wrapped_func = mock_agent.tools[0]._functions["sample_tool"]
    
    # Call it synchronously (our sync wrapper should detect it is async and run it)
    result = wrapped_func("Berlin")
    assert result == "Async result for Berlin"

def test_instrument_emits_child_span(plugin, metrics, span_exporter):
    def sample_tool(location: str):
        return "ok"
        
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    plugin.instrument(mock_agent, metrics)
    wrapped_func = mock_agent.tools[0]._functions["sample_tool"]
    
    wrapped_func("Rome")
    
    spans = span_exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name.startswith("execute_tool ")]
    assert len(tool_spans) == 1
    assert tool_spans[0].name == "execute_tool sample_tool"
    assert tool_spans[0].attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool_spans[0].attributes["gen_ai.tool.name"] == "sample_tool"

def test_instrument_exception_logging(plugin, metrics, span_exporter):
    def sample_tool(location: str):
        raise ValueError("failing tool")
        
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    plugin.instrument(mock_agent, metrics)
    wrapped_func = mock_agent.tools[0]._functions["sample_tool"]
    
    with pytest.raises(ValueError, match="failing tool"):
        wrapped_func("Rome")
        
    spans = span_exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name.startswith("execute_tool ")]
    assert len(tool_spans) == 1
    # Check that OTel span has status ERROR and only error.type attribute
    assert tool_spans[0].status.status_code.name == "ERROR"
    assert tool_spans[0].attributes["error.type"] == "ValueError"
    
    # Check that exception message is NOT in span attributes
    for key, value in tool_spans[0].attributes.items():
        assert "failing tool" not in str(value)
        
    # Check that metrics has correct error message type only
    assert len(metrics.tools_called) == 1
    assert metrics.tools_called[0].result == "Error: ValueError"

def test_instrument_sets_model_attribute(plugin, metrics, span_exporter):
    mock_agent = MagicMock()
    mock_agent.model = "gpt-4o-test"
    mock_agent.tools = []
    
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("parent_span"):
        plugin.instrument(mock_agent, metrics)
        
    spans = span_exporter.get_finished_spans()
    parent_span = next(s for s in spans if s.name == "parent_span")
    assert parent_span.attributes["gen_ai.request.model"] == "gpt-4o-test"

def test_instrument_deepcopies_definitions(plugin, metrics):
    def sample_tool(location: str):
        return "ok"
        
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    plugin.instrument(mock_agent, metrics)
    
    wrapped_tool = mock_agent.tools[0]
    # Check that definitions are deep-copied and not sharing same reference
    assert wrapped_tool.definitions is not mock_tool.definitions
    assert wrapped_tool.definitions == mock_tool.definitions


@pytest.mark.asyncio
async def test_instrument_sync_tool_with_active_loop(plugin, metrics):
    def sample_tool(location: str):
        return f"Result for {location}"
        
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    # Tool args runner
    async def tool_args_runner(name, args):
        args["location"] = "Madrid"
        return args
        
    # Instrument while the event loop is active
    plugin.instrument(mock_agent, metrics, tool_args_runner)
    wrapped_func = mock_agent.tools[0]._functions["sample_tool"]
    
    # Case 1: Call sync wrapped tool from inside the running loop thread
    # This should trigger the executor path (_run_async runs inside ThreadPoolExecutor)
    result_sync = wrapped_func("Paris")
    assert result_sync == "Result for Madrid"
    
    # Case 2: Call sync wrapped tool from a background thread
    # This should trigger the run_coroutine_threadsafe path
    result_thread = await asyncio.to_thread(wrapped_func, "Paris")
    assert result_thread == "Result for Madrid"


def test_instrument_var_keyword_arguments(plugin, metrics):
    def sample_tool(location: str, **kwargs):
        return f"Weather in {location} is {kwargs.get('temp', 20)}C"
        
    mock_agent = MagicMock()
    mock_tool = MockFunctionTool(name="sample_tool", functions=[sample_tool])
    mock_agent.tools = [mock_tool]
    
    async def tool_args_runner(name, args):
        assert "location" in args
        assert "temp" in args
        args["location"] = "Madrid"
        args["temp"] = 35.0
        return args
        
    plugin.instrument(mock_agent, metrics, tool_args_runner)
    wrapped_func = mock_agent.tools[0]._functions["sample_tool"]
    
    # Pass location and temp (extra keyword argument matching **kwargs)
    result = wrapped_func("Paris", temp=15.0)
    assert result == "Weather in Madrid is 35.0C"
