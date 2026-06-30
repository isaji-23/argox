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
import atexit
import copy
import concurrent.futures
import functools
import inspect
import logging
import time
from typing import Any, Callable

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from argox.core.state import AgentRunMetrics, ApiCallRecord, ToolCallRecord
from argox.interfaces.plugin import ArgoxPlugin, ToolArgsRunner

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("argox")

# Shared thread pool executor for executing coroutines under running event loops
_SHARED_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10)
atexit.register(lambda: _SHARED_EXECUTOR.shutdown(wait=False))


def _run_async(coro, loop_at_instrument: Any) -> Any:
    """Helper to run a coroutine synchronously without deadlock or loop issues."""
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is not None:
        # We are inside a running loop. Run in a separate thread to avoid deadlock.
        return _SHARED_EXECUTOR.submit(asyncio.run, coro).result()
    else:
        # We are not in a thread with a running loop.
        if loop_at_instrument and loop_at_instrument.is_running():
            return asyncio.run_coroutine_threadsafe(coro, loop_at_instrument).result()
        else:
            return asyncio.run(coro)


def _get_flat_arguments(bound: inspect.BoundArguments) -> dict:
    """Flatten bound arguments by promoting **kwargs to the root level.

    Ensures the runner receives a flat dict of arguments, matching the JSON-like
    format processors expect.
    """
    flat = {}
    for key, value in bound.arguments.items():
        param = bound.signature.parameters.get(key)
        if param and param.kind == inspect.Parameter.VAR_KEYWORD:
            if isinstance(value, dict):
                flat.update(value)
        else:
            flat[key] = value
    return flat


def _update_bound_arguments(sig: inspect.Signature, bound: inspect.BoundArguments, processed_args: dict) -> None:
    """Update bound arguments from the runner's dictionary output.

    Handles function signatures correctly, putting extra parameters into **kwargs
    if present, and preventing silent discarding or signature mismatches.
    """
    var_keyword_name = None
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            var_keyword_name = param.name
            break

    if var_keyword_name is not None:
        bound.arguments[var_keyword_name] = {}

    for key, value in processed_args.items():
        if key in sig.parameters and key != var_keyword_name:
            bound.arguments[key] = value
        elif var_keyword_name is not None:
            bound.arguments[var_keyword_name][key] = value


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
        try:
            loop_at_instrument = asyncio.get_running_loop()
        except RuntimeError:
            loop_at_instrument = None

        model = getattr(target, "model", None)
        if model:
            if not isinstance(model, str):
                model = getattr(model, "model", None)
            if model and isinstance(model, str):
                trace.get_current_span().set_attribute("gen_ai.request.model", model)

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
                new_tools.append(self._wrap_function_tool(tool, metrics, tool_args_runner, loop_at_instrument))
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
        if usage is None:
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
            content = raw_result.content
            if isinstance(content, str):
                return content
            
            # If it's a list (e.g. content blocks in Azure messages)
            if isinstance(content, list):
                parts = []
                for item in content:
                    if hasattr(item, "text"):
                        text_obj = item.text
                        if hasattr(text_obj, "value"):
                            parts.append(str(text_obj.value))
                        else:
                            parts.append(str(text_obj))
                    elif hasattr(item, "value"):
                        parts.append(str(item.value))
                    else:
                        parts.append(str(item))
                return "".join(parts)
            
            return str(content)
        
        logger.warning("Could not extract output: raw_result does not have 'content' attribute.")
        return ""

    def _wrap_function_tool(
        self, 
        tool: Any, 
        metrics: AgentRunMetrics, 
        runner: ToolArgsRunner | None,
        loop_at_instrument: Any
    ) -> Any:
        """Wrap an azure.ai.projects.models.FunctionTool to intercept calls."""
        try:
            from azure.ai.projects.models import AsyncFunctionTool
            is_async = isinstance(tool, AsyncFunctionTool)
        except ImportError:
            is_async = False

        original_functions = getattr(tool, "_functions", None)
        if original_functions is None:
            logger.warning(
                "FunctionTool does not have a private '_functions' attribute. "
                "ArgoxAzureFoundryPlugin cannot wrap its functions. Tool monitoring may not work."
            )
            return tool

        wrapped_tool = copy.copy(tool)
        if hasattr(tool, "definitions") and tool.definitions is not None:
            wrapped_tool.definitions = copy.deepcopy(tool.definitions)

        wrapped_functions = {}
        for name, func in original_functions.items():
            if is_async:
                wrapped_functions[name] = self._make_async_wrapper(name, func, metrics, runner)
            else:
                wrapped_functions[name] = self._make_sync_wrapper(name, func, metrics, runner, loop_at_instrument)

        wrapped_tool._functions = wrapped_functions
        return wrapped_tool

    def _make_sync_wrapper(
        self, 
        name: str, 
        func: Callable, 
        metrics: AgentRunMetrics, 
        runner: ToolArgsRunner | None,
        loop_at_instrument: Any
    ) -> Callable:
        """Create a sync wrapper for a sync tool function."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            record = ToolCallRecord(name=name, start=time.time())
            metrics.tools_called.append(record)
            
            with _tracer.start_as_current_span(
                f"execute_tool {name}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": name,
                },
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()

                    if runner:
                        flat_args = _get_flat_arguments(bound)
                        processed_args = _run_async(runner(name, flat_args), loop_at_instrument)
                        _update_bound_arguments(sig, bound, processed_args)
                    
                    if asyncio.iscoroutinefunction(func):
                        result = _run_async(func(*bound.args, **bound.kwargs), loop_at_instrument)
                    else:
                        result = func(*bound.args, **bound.kwargs)
                    
                    record.end = time.time()
                    record.result = str(result)
                    return result
                except Exception as e:
                    span.set_attribute("error.type", type(e).__qualname__)
                    span.set_status(Status(StatusCode.ERROR))
                    record.end = time.time()
                    record.result = f"Error: {type(e).__name__}"
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
            
            with _tracer.start_as_current_span(
                f"execute_tool {name}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": name,
                },
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()

                    if runner:
                        flat_args = _get_flat_arguments(bound)
                        processed_args = await runner(name, flat_args)
                        _update_bound_arguments(sig, bound, processed_args)
                    
                    result = await func(*bound.args, **bound.kwargs)
                    
                    record.end = time.time()
                    record.result = str(result)
                    return result
                except Exception as e:
                    span.set_attribute("error.type", type(e).__qualname__)
                    span.set_status(Status(StatusCode.ERROR))
                    record.end = time.time()
                    record.result = f"Error: {type(e).__name__}"
                    raise
        
        return wrapper
