import pytest
import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

from langchain_core.runnables import RunnableLambda
from langchain_core.tools import BaseTool
from langchain_core.outputs import LLMResult

from argox_langchain.plugin import ArgoxLangChainPlugin
from argox_langchain.callback_handler import ArgoxLangChainCallbackHandler
from argox.core.state import AgentRunMetrics

class DummyTool(BaseTool):
    name: str = "dummy_tool"
    description: str = "A dummy tool"

    def _run(self, *args, **kwargs):
        return f"Dummy result for {kwargs.get('query')}"
        
    async def _arun(self, *args, **kwargs):
        return f"Async dummy result for {kwargs.get('query')}"

@pytest.fixture
def plugin():
    return ArgoxLangChainPlugin()

@pytest.fixture
def metrics():
    return AgentRunMetrics(agent_name="test-agent")

def test_plugin_name(plugin):
    assert plugin.name == "langchain"

def test_instrument_returns_runnable(plugin, metrics):
    dummy = RunnableLambda(lambda x: {"output": "hello"})
    result = plugin.instrument(dummy, metrics)
    
    assert hasattr(result, "invoke")
    # Verify it returns something that is wrapped with our callback
    # Result is a RunnableBinding
    assert hasattr(result, "config")
    assert "callbacks" in result.config

@pytest.mark.asyncio
async def test_tool_wrapping_intercepts_args(plugin, metrics):
    class DummyAgent(RunnableLambda):
        def __init__(self, func):
            super().__init__(func)
            self.tools = [DummyTool()]
            
    dummy = DummyAgent(lambda x: "hello")
    
    async def tool_args_runner(name, args):
        args["query"] = "intercepted"
        return args
        
    result = plugin.instrument(dummy, metrics, tool_args_runner)
    
    tool = result.tools[0]
    
    # Sync call
    res_sync = tool._run(query="original")
    assert res_sync == "Dummy result for intercepted"
    
    # Async call
    res_async = await tool._arun(query="original")
    assert res_async == "Async dummy result for intercepted"

@pytest.mark.asyncio
async def test_callback_handler_records_tokens(metrics):
    handler = ArgoxLangChainCallbackHandler(metrics)
    run_id = uuid4()
    
    await handler.on_llm_start({}, [], run_id=run_id)
    
    llm_result = LLMResult(
        generations=[], 
        llm_output={
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model_name": "test-model"
        }
    )
    
    await handler.on_llm_end(llm_result, run_id=run_id, invocation_params={"_type": "openai"})
    
    assert len(metrics.api_calls) == 1
    call = metrics.api_calls[0]
    assert call.call_number == 1
    assert call.input_tokens == 10
    assert call.output_tokens == 5
    assert call.total_tokens == 15

@pytest.mark.asyncio
async def test_callback_handler_records_tools(metrics):
    handler = ArgoxLangChainCallbackHandler(metrics)
    run_id = uuid4()
    
    await handler.on_tool_start({}, "input", run_id=run_id)
    await handler.on_tool_end("tool output", run_id=run_id, name="test_tool")
    
    assert len(metrics.tools_called) == 1
    tool = metrics.tools_called[0]
    assert tool.name == "test_tool"
    assert tool.result == "tool output"

def test_extract_output(plugin):
    assert plugin.extract_output({"output": "hello"}) == "hello"
    
    class AIMessage:
        content = "hello AI"
    assert plugin.extract_output(AIMessage()) == "hello AI"
    
    assert plugin.extract_output("direct string") == "direct string"
