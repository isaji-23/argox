"""Public ``@argox.monitor`` decorator.

Wraps a user callable in an :class:`~argox.core.manager.ArgoxManager` lifecycle
so a single decoration replaces the boilerplate of building, configuring, and
driving the Manager by hand.

Typical usage::

    agent = Agent(name="weather", instructions=..., tools=[...])

    @argox.monitor(plugin="openai", policy=my_policy)
    def run_agent(prompt: str) -> str:
        return Runner.run_sync(agent, prompt)

    print(run_agent("What's the weather in Madrid?"))

The decorator supports both sync and async target functions and locates the
agent instance from the function's closure or module globals when it is not
passed explicitly via the ``agent`` keyword.

When the wrapped function declares an ``agent`` parameter the decorator
injects the agent returned by ``plugin.instrument(...)`` into that slot, so
plugins that wrap the agent (rather than mutating it in place) keep their
instrumentation active during execution. When the function only takes the
prompt and the plugin returns a wrapper distinct from the original agent, a
``RuntimeWarning`` is emitted to flag that instrumentation will be lost.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import warnings
from typing import Any, Callable, Iterable, List, Optional, Tuple, Union

from argox.core.manager import ArgoxManager
from argox.interfaces.exporter import ExporterBase
from argox.interfaces.plugin import ArgoxPlugin
from argox.interfaces.policy import PolicyClient
from argox.interfaces.processor import ArgoxProcessor

ProcessorSpec = Union[ArgoxProcessor, Tuple[ArgoxProcessor, bool]]


def _load_plugin(name: str) -> ArgoxPlugin:
    """Instantiate a plugin registered under entry-point group ``argox.plugins``.

    Args:
        name: Plugin entry-point name (e.g., ``"openai"``).

    Returns:
        A fresh plugin instance.

    Raises:
        LookupError: If no entry point matches ``name``.
    """
    from importlib.metadata import entry_points

    try:
        eps = entry_points(group="argox.plugins")
    except TypeError:  # pragma: no cover - Python <3.10 fallback
        eps = entry_points().get("argox.plugins", [])
    for ep in eps:
        if ep.name == name:
            plugin_cls = ep.load()
            return plugin_cls()
    raise LookupError(
        f"No Argox plugin registered for '{name}'. "
        "Install a package exposing it under entry-point group 'argox.plugins'."
    )


def _looks_like_agent(value: Any) -> bool:
    """Return True for objects that quack like a framework agent."""
    if isinstance(value, type):
        return False
    return hasattr(value, "name") and hasattr(value, "tools")


def _find_agent_in_closure(fn: Callable[..., Any]) -> Optional[Any]:
    """Scan ``fn``'s closure cells for an object that looks like an agent."""
    closure = getattr(fn, "__closure__", None)
    if not closure:
        return None
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if _looks_like_agent(value):
            return value
    return None


def _find_agent_in_globals(fn: Callable[..., Any]) -> Optional[Any]:
    """Scan ``fn.__globals__`` for an object that looks like an agent."""
    globs = getattr(fn, "__globals__", None)
    if not globs:
        return None
    for value in globs.values():
        if _looks_like_agent(value):
            return value
    return None


def monitor(
    *,
    plugin: Union[str, ArgoxPlugin],
    agent: Any = None,
    policy: Optional[PolicyClient] = None,
    processors: Optional[Iterable[ProcessorSpec]] = None,
    exporters: Optional[Iterable[ExporterBase]] = None,
    metadata: Optional[dict] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Build a decorator that routes the target callable through an ArgoxManager.

    Args:
        plugin: Either a plugin entry-point name (``"openai"``) resolved via
            ``importlib.metadata`` or an already-instantiated ``ArgoxPlugin``.
        agent: Optional explicit agent instance. When omitted the decorator
            inspects the target function's closure and module globals.
        policy: Optional ``PolicyClient``. When ``None`` no policy checks run.
        processors: Iterable of processors to register. Each item may be a
            bare ``ArgoxProcessor`` (fail-open) or a ``(processor, strict)``
            tuple matching ``ArgoxManager.register_processor``.
        exporters: Iterable of ``ExporterBase`` instances to register.
        metadata: Extra metadata propagated to ``RunContext`` on every call.

    Returns:
        A decorator. Applying it twice to two different functions causes both
        to share the same ``ArgoxManager`` instance.

    Raises:
        LookupError: If the plugin string cannot be resolved.
    """
    plugin_instance: ArgoxPlugin = (
        _load_plugin(plugin) if isinstance(plugin, str) else plugin
    )

    mgr = ArgoxManager(policy=policy)
    mgr.register_plugin(plugin_instance)
    for spec in processors or ():
        if isinstance(spec, tuple):
            processor, strict = spec
            mgr.register_processor(processor, strict=strict)
        else:
            mgr.register_processor(spec)
    for exporter in exporters or ():
        mgr.register_exporter(exporter)

    plugin_name = plugin_instance.name
    explicit_agent = agent

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        is_coro = asyncio.iscoroutinefunction(fn)
        sig_params = inspect.signature(fn).parameters
        inject_agent = "agent" in sig_params

        def _resolve_agent() -> Any:
            if explicit_agent is not None:
                return explicit_agent
            found = _find_agent_in_closure(fn) or _find_agent_in_globals(fn)
            if found is None:
                raise LookupError(
                    "@argox.monitor could not locate an agent. Pass "
                    "`agent=` explicitly or reference it from the function "
                    "closure or module globals."
                )
            return found

        def _resolve_prompt(call_args: tuple, call_kwargs: dict) -> str:
            if call_args:
                return call_args[0]
            if "prompt" in call_kwargs:
                return call_kwargs["prompt"]
            raise TypeError(
                "@argox.monitor expects the prompt as the first positional "
                "argument or as the `prompt` keyword."
            )

        async def _invoke(call_args: tuple, call_kwargs: dict) -> str:
            agent_obj = _resolve_agent()
            prompt = _resolve_prompt(call_args, call_kwargs)

            async def runner(instrumented_agent: Any, processed_prompt: str) -> Any:
                bound_args: List[Any]
                bound_kwargs = dict(call_kwargs)
                if inject_agent:
                    # Pass agent and prompt as keywords to avoid a positional
                    # collision with the agent slot in the target signature.
                    # The user-supplied prompt positional (call_args[0]) is
                    # replaced by ``processed_prompt`` and any remaining
                    # positionals are forwarded unchanged.
                    bound_args = list(call_args[1:])
                    bound_kwargs["prompt"] = processed_prompt
                    bound_kwargs["agent"] = instrumented_agent
                else:
                    bound_args = list(call_args)
                    if bound_args:
                        bound_args[0] = processed_prompt
                    else:
                        bound_kwargs["prompt"] = processed_prompt
                    if instrumented_agent is not agent_obj:
                        warnings.warn(
                            "Plugin returned an instrumented wrapper distinct "
                            "from the original agent but the decorated "
                            "function does not accept an `agent` parameter. "
                            "The wrapper will be discarded and instrumentation "
                            "lost. Declare an `agent` parameter so the "
                            "decorator can inject it.",
                            RuntimeWarning,
                            stacklevel=2,
                        )
                if is_coro:
                    return await fn(*bound_args, **bound_kwargs)
                return await asyncio.to_thread(fn, *bound_args, **bound_kwargs)

            return await mgr.run(
                agent_obj,
                prompt,
                plugin_name,
                runner,
                metadata=metadata,
            )

        if is_coro:

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> str:
                return await _invoke(args, kwargs)

            async_wrapper.argox_manager = mgr  # type: ignore[attr-defined]
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> str:
            return asyncio.run(_invoke(args, kwargs))

        sync_wrapper.argox_manager = mgr  # type: ignore[attr-defined]
        return sync_wrapper

    return decorator
