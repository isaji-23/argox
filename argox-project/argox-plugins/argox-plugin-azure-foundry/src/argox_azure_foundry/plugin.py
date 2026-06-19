"""ArgoxAzureFoundryPlugin — integrates Azure AI Foundry Agent Service with Argox.

Phase 0 — Investigation Results:
1. Execution Model: Agent -> Thread -> Message -> Run. 
   Runs are executed via client.agents.create_and_process_run (sync-like) or 
   client.agents.create_run + polling. Supports streaming with AsyncAgentEventHandler.
2. Extension points for tool calls: No native "hooks" on the Agent object itself. 
   Tool execution is intercepted by wrapping the functions passed to FunctionTool 
   before the run.
3. Tool filtering: create_run/create_and_process_run accepts a 'tools' parameter 
   that overrides Agent tools. ArgoxManager applies policies by rewriting target.tools.
4. Token extraction: ThreadRun.usage has {total_tokens, prompt_tokens, completion_tokens}.
   It is a model object; we use getattr for safety.
5. Output final: Obtained via client.agents.list_messages(thread_id). 
   Normalized by taking the last assistant message.
6. Async client: Available as azure.ai.projects.aio.AIProjectClient.
"""

from __future__ import annotations

import asyncio
import copy
import functools
import logging
import time
from typing import Any, Callable

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord
from argox.interfaces.plugin import ArgoxPlugin, ToolArgsRunner

logger = logging.getLogger(__name__)


class ArgoxAzureFoundryPlugin(ArgoxPlugin):
    """ArgoxPlugin implementation for Azure AI Foundry (azure-ai-projects)."""

    @property
    def name(self) -> str:
        return "azure-foundry"

    def instrument(
        self,
        target: Any,
        metrics: AgentRunMetrics,
        tool_args_runner: ToolArgsRunner | None = None,
    ) -> Any:
        """Instrument the Azure Agent by wrapping its tools.

        Azure Agent Service doesn't have a simple hooks system like openai-agents.
        Instead, we wrap the function tools provided to the agent to record 
        start/end times and results, and to run the tool-args processors.
        """
        if not hasattr(target, "tools") or not target.tools:
            return target

        # We need to import FunctionTool inside to avoid hard dependency in core
        try:
            from azure.ai.projects.models import AsyncFunctionTool, FunctionTool
        except ImportError:
            # If the user is using the SDK, it should be available.
            # If not, we can't instrument tools.
            return target

        new_tools = []
        for tool in target.tools:
            if isinstance(tool, (FunctionTool, AsyncFunctionTool)):
                new_tools.append(self._wrap_function_tool(tool, metrics, tool_args_runner))
            else:
                new_tools.append(tool)
        
        target.tools = new_tools
        return target

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        """Extract token usage from the Run object.

        In Azure AI Foundry, the 'raw_result' is typically a ThreadRun object
        returned by create_and_process_run or retrieved via get_run.
        """
        usage = getattr(raw_result, "usage", None)
        if not usage:
            return

        # Azure SDK models use snake_case for usage attributes like prompt_tokens.
        # Based on docs/architecture.md and Phase 0, we use getattr.
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

        metrics.api_calls.append(
            ApiCallRecord(
                call_number=len(metrics.api_calls) + 1,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
        )

    def extract_output(self, raw_result: Any) -> str:
        """Extract final output from the Run or Messages.

        Note: In some Foundry patterns, the 'raw_result' might be the Run object
        itself. To get the output text, one often needs to query the messages
        of the thread. However, if the runner returns the final message content
        or a result object containing it, we extract it here.
        
        If raw_result is a string, return it.
        If it has a 'text' attribute (custom results), return it.
        """
        if isinstance(raw_result, str):
            return raw_result
        
        # Check for common result patterns
        if hasattr(raw_result, "content"):
            return str(raw_result.content)
        
        logger.warning("Could not extract output: raw_result does not have 'content' attribute.")
        return ""

    def _wrap_function_tool(
        self, 
        tool: Any, 
        metrics: AgentRunMetrics, 
        runner: ToolArgsRunner | None
    ) -> Any:
        """Wrap an azure.ai.projects.models.FunctionTool to intercept calls."""
        try:
            from azure.ai.projects.models import AsyncFunctionTool
            is_async = isinstance(tool, AsyncFunctionTool)
        except ImportError:
            is_async = False

        original_functions = getattr(tool, "_functions", {})
        if not original_functions:
            return tool

        wrapped_tool = copy.copy(tool)
        wrapped_functions = {}
        for name, func in original_functions.items():
            if is_async:
                wrapped_functions[name] = self._make_async_wrapper(name, func, metrics, runner)
            else:
                wrapped_functions[name] = self._make_sync_wrapper(name, func, metrics, runner)

        wrapped_tool._functions = wrapped_functions
        return wrapped_tool

    def _make_sync_wrapper(
        self, 
        name: str, 
        func: Callable, 
        metrics: AgentRunMetrics, 
        runner: ToolArgsRunner | None
    ) -> Callable:
        """Create a sync wrapper for a sync tool function."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            record = ToolCallRecord(name=name, start=time.time())
            metrics.tools_called.append(record)
            
            try:
                if runner:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    
                    if loop and loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            kwargs = pool.submit(asyncio.run, runner(name, kwargs)).result()
                    else:
                        kwargs = asyncio.run(runner(name, kwargs))
                
                result = func(*args, **kwargs)
                
                record.end = time.time()
                record.result = str(result)
                return result
            except Exception as e:
                record.end = time.time()
                record.result = f"Error: {str(e)}"
                raise
        
        return wrapper

    def _make_async_wrapper(
        self, 
        name: str, 
        func: Callable, 
        metrics: AgentRunMetrics, 
        runner: ToolArgsRunner | None
    ) -> Callable:
        """Create an async wrapper for an async tool function."""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            record = ToolCallRecord(name=name, start=time.time())
            metrics.tools_called.append(record)
            
            try:
                if runner:
                    kwargs = await runner(name, kwargs)
                
                result = await func(*args, **kwargs)
                
                record.end = time.time()
                record.result = str(result)
                return result
            except Exception as e:
                record.end = time.time()
                record.result = f"Error: {str(e)}"
                raise
        
        return wrapper
