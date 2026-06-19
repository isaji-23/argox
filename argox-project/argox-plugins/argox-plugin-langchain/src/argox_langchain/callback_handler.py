import time
from typing import Any, Dict, List
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord

class ArgoxLangChainCallbackHandler(AsyncCallbackHandler):
    """Async callback handler to record metrics into Argox."""

    def __init__(self, metrics: AgentRunMetrics):
        super().__init__()
        self.metrics = metrics
        self._tool_starts: Dict[UUID, float] = {}
        self._llm_starts: Dict[UUID, float] = {}

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._llm_starts[run_id] = time.time()

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        start_time = self._llm_starts.pop(run_id, time.time())
        end_time = time.time()
        
        # Extract token usage
        # This usually sits in response.llm_output["token_usage"]
        llm_output = response.llm_output or {}
        token_usage = llm_output.get("token_usage", {})
        
        prompt_tokens = token_usage.get("prompt_tokens", 0)
        completion_tokens = token_usage.get("completion_tokens", 0)
        total_tokens = token_usage.get("total_tokens", prompt_tokens + completion_tokens)
        
        record = ApiCallRecord(
            call_number=len(self.metrics.api_calls) + 1,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        self.metrics.api_calls.append(record)

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._tool_starts[run_id] = time.time()

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        start_time = self._tool_starts.pop(run_id, time.time())
        name = kwargs.get("name", "unknown_tool")
        record = ToolCallRecord(
            name=name,
            start=start_time,
            end=time.time(),
            result=str(output)
        )
        self.metrics.tools_called.append(record)

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        start_time = self._tool_starts.pop(run_id, time.time())
        name = kwargs.get("name", "unknown_tool")
        record = ToolCallRecord(
            name=name,
            start=start_time,
            end=time.time(),
            result=f"Error: {str(error)}"
        )
        self.metrics.tools_called.append(record)
