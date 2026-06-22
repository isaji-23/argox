"""
Phase 0 Answers:
1. Target Agent: The plugin covers LCEL `Runnable`s and `AgentExecutor`s.
2. Extension Point: We use `AsyncCallbackHandler` to gather observational metrics (`on_tool_start`, `on_llm_end`).
3. Injection Method: We return `target.with_config({"callbacks": [handler]})`. We don't mutate the agent internals for callbacks, as LCEL is immutable/declarative.
4. Tool Filtering: We mutate `target.tools` if the attribute exists (e.g., `AgentExecutor`), which `ArgoxManager` correctly snapshots and restores.
5. Tool Arguments Interception (PLUGIN-02): Callbacks are purely observational. To mutate arguments before execution, we dynamically wrap `_run` and `_arun` methods of each `BaseTool` in `target.tools`.
6. Token Extraction: Extracted in `on_llm_end` callback using `response.llm_output["token_usage"]`.
7. Final Output: Extracted via `extract_output` checking for dicts with `"output"` or objects with `"content"`.
8. Sync vs Async: Primary path is async (`AsyncCallbackHandler`).
"""

import functools
import logging
from typing import Any

from argox.core.state import AgentRunMetrics
from argox.interfaces.plugin import ArgoxPlugin, ToolArgsRunner

logger = logging.getLogger(__name__)

class ArgoxLangChainPlugin(ArgoxPlugin):
    """ArgoxPlugin implementation for LangChain."""

    @property
    def name(self) -> str:
        return "langchain"

    def instrument(
        self, target: Any, metrics: AgentRunMetrics, tool_args_runner: ToolArgsRunner | None = None
    ) -> Any:
        """
        Instrument a LangChain AgentExecutor or LCEL Runnable.
        Returns a new RunnableBinding with callbacks attached.
        """
        try:
            from langchain_core.runnables import Runnable
        except ImportError:
            return target

        if not isinstance(target, Runnable):
            logger.warning("Target is not a LangChain Runnable. Instrumentation skipped.")
            return target

        # If the target exposes 'tools', we can wrap them to intercept arguments
        # before the tool logic runs (necessary for PII redaction and policy enforcement).
        original_tools = getattr(target, "tools", None)
        if original_tools is not None and isinstance(original_tools, list):
            wrapped_tools = []
            for tool in original_tools:
                wrapped_tools.append(self._wrap_tool(tool, tool_args_runner))
            # Mutate target tools. (This mutates AgentExecutor.tools)
            target.tools = wrapped_tools

        from argox_langchain.callback_handler import ArgoxLangChainCallbackHandler
        handler = ArgoxLangChainCallbackHandler(metrics)

        # Return a new Runnable with the callback attached
        return target.with_config({"callbacks": [handler]})

    def _wrap_tool(self, tool: Any, runner: ToolArgsRunner | None) -> Any:
        """Wrap a LangChain BaseTool to run arg interceptor before execution."""
        from langchain_core.tools import BaseTool
        
        if not isinstance(tool, BaseTool):
            return tool

        original_run = tool._run
        original_arun = getattr(tool, "_arun", None)

        @functools.wraps(original_run)
        def wrapped_run(*args, **kwargs):
            if runner:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                
                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        kwargs = pool.submit(asyncio.run, runner(tool.name, kwargs)).result()
                else:
                    kwargs = asyncio.run(runner(tool.name, kwargs))
            
            return original_run(*args, **kwargs)

        # Direct assignment to __dict__ avoids pydantic validation issues
        tool._run = wrapped_run

        if original_arun:
            @functools.wraps(original_arun)
            async def wrapped_arun(*args, **kwargs):
                if runner:
                    kwargs = await runner(tool.name, kwargs)
                return await original_arun(*args, **kwargs)
            tool._arun = wrapped_arun

        return tool

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        """Tokens are extracted via AsyncCallbackHandler in on_llm_end. No-op here."""
        pass

    def extract_output(self, raw_result: Any) -> str:
        """Extract output from standard LangChain shapes."""
        if raw_result is None:
            return ""
        
        # AgentExecutor typically returns dict with "output"
        if isinstance(raw_result, dict):
            if "output" in raw_result:
                return str(raw_result["output"])
            # Fallback
            return str(raw_result)

        # LCEL AIMessage typically has "content"
        if hasattr(raw_result, "content"):
            return str(raw_result.content)
            
        return str(raw_result)
