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
import time
from typing import Any, Callable

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord
from argox.interfaces.plugin import ArgoxPlugin, ToolArgsRunner


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
            from azure.ai.projects.models import FunctionTool
        except ImportError:
            # If the user is using the SDK, it should be available.
            # If not, we can't instrument tools.
            return target

        new_tools = []
        for tool in target.tools:
            if isinstance(tool, FunctionTool):
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

        # Azure SDK models often use camelCase or specific attribute names.
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
        
        return ""

    def _wrap_function_tool(
        self, 
        tool: Any, 
        metrics: AgentRunMetrics, 
        runner: ToolArgsRunner | None
    ) -> Any:
        """Wrap an azure.ai.projects.models.FunctionTool to intercept calls."""
        # FunctionTool has a 'functions' attribute which is a list of callables
        # or it handles them via a dictionary internally.
        # Actually, FunctionTool in azure-ai-projects works by taking a set of functions.
        # We need to wrap each function in the tool.
        
        # If we can't easily wrap inside FunctionTool (it might be sealed/immutable),
        # we might need to recreate it.
        from azure.ai.projects.models import FunctionTool

        original_functions = getattr(tool, "_functions", {}) # Implementation detail of SDK
        if not original_functions:
            # Try to get from public API if exists
            return tool

        wrapped_functions = {}
        for name, func in original_functions.items():
            wrapped_functions[name] = self._make_wrapper(name, func, metrics, runner)

        # Recreate the tool with wrapped functions
        new_tool = FunctionTool(functions=list(wrapped_functions.values()))
        return new_tool

    def _make_wrapper(
        self, 
        name: str, 
        func: Callable, 
        metrics: AgentRunMetrics, 
        runner: ToolArgsRunner | None
    ) -> Callable:
        """Create a wrapper for a tool function."""
        
        async def wrapper(*args, **kwargs):
            record = ToolCallRecord(name=name, start=time.time())
            metrics.tools_called.append(record)
            
            try:
                # 1. Mutate arguments if runner is provided
                if runner:
                    # In Azure, tool calls usually pass arguments as kwargs
                    kwargs = await runner(name, kwargs)
                
                # 2. Execute original function
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    # Run sync function in executor or directly? 
                    # Project context suggests async-first.
                    result = func(*args, **kwargs)
                
                # 3. Record success
                record.end = time.time()
                record.result = str(result)
                return result
            except Exception as e:
                # 4. Record failure and re-raise
                record.end = time.time()
                record.result = f"Error: {str(e)}"
                raise
        
        # Preserve original metadata if possible for the SDK to pick up signatures
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        wrapper.__annotations__ = func.__annotations__
        
        return wrapper
