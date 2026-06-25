# Argox Plugin Development Guide

This guide provides a comprehensive blueprint for developers who want to write custom framework integrations (plugins) for the Argox SDK. It covers the `ArgoxPlugin` contract, run lifecycle hooks, pre-execution tool-argument interception for PII redaction, OpenTelemetry (OTel) telemetry conventions, auto-discovery packaging, and testing best practices.

---

## 1. Introduction to Plugins in Argox

In the Argox ecosystem, the SDK is designed to be entirely framework-agnostic. The core orchestrator, `ArgoxManager`, does not know how to interact directly with specific agent frameworks (such as the OpenAI Agents SDK, LangChain, or Azure AI Foundry). Instead, it delegates all framework-specific operations to a **Plugin**.

A plugin implements the `ArgoxPlugin` interface and is responsible for:
1. **Instrumenting the agent** before execution to capture run metadata, hooks, and tool-call events.
2. **Intercepting tool executions** to apply in-flight argument transformations (such as PII redaction) and emit OTel child spans.
3. **Extracting token consumption** from the raw response returned by the framework.
4. **Normalizing the final output** into a plain string.

A plugin does **not** manage policies, instantiate global metrics, or manage the root OTel span. Those concerns are handled exclusively by the `ArgoxManager`.

---

## 2. The `ArgoxPlugin` Interface

Every Argox plugin must subclass the abstract base class `ArgoxPlugin` (defined in `argox.interfaces.plugin.py`).

```python
from abc import ABC, abstractmethod
from typing import Any
from argox.core.state import AgentRunMetrics
from argox.interfaces.plugin import ToolArgsRunner

class ArgoxPlugin(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique plugin identifier. Must be lowercase and contain no spaces.
        Examples: "openai", "langchain", "azure_foundry".
        """
        pass

    @abstractmethod
    def instrument(
        self,
        target: Any,
        metrics: AgentRunMetrics,
        tool_args_runner: ToolArgsRunner | None = None,
    ) -> Any:
        """
        Injects monitoring and hooks into the agent or runner object.
        """
        pass

    @abstractmethod
    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        """
        Extracts token usage from the raw result and records it in metrics.
        """
        pass

    @abstractmethod
    def extract_output(self, raw_result: Any) -> str:
        """
        Extracts the final response text from the raw framework result.
        """
        pass
```

---

## 3. Detailed Implementation Details

### A. The `name` Property
The `name` property uniquely identifies your plugin. This name is used by the `@argox.monitor(plugin="...")` decorator to resolve the plugin at runtime. It must match the name registered in the package's entry points.

### B. The `instrument` Method
This method is called **before** the agent starts execution. Its goal is to wrap or hook into the `target` (which represents the framework-specific agent, chain, or runner) and bind the execution flow to the provided `metrics` object.

#### Concurrency and Cloning
According to **ADR-0010**, `ArgoxManager` passes a **per-run shallow copy** of the agent (`copy.copy(agent)`) to the `instrument` method, rather than the caller's shared instance. This prevents cross-request metrics contamination and race conditions when a single agent instance is driven concurrently.
* Your plugin should perform **rebinds** (e.g., replacing a list or dict of tools/hooks on the target) rather than mutating shared nested objects in-place.
* Always return the instrumented target (which can be the mutated copy or a wrapped wrapper object).

#### Pre-Execution Tool-Argument Interception
One of Argox's core guarantees is the ability to redact PII *before* it reaches tool execution. If a user has registered processors (like a PII redactor), the Manager provides a `tool_args_runner` callable of type `ToolArgsRunner` (which is an `async` callable with signature `(tool_name: str, args: dict[str, Any]) -> Awaitable[dict[str, Any]]`).

Inside your tool-execution shim, you **must**:
1. Check if `tool_args_runner` is provided.
2. If provided, await `tool_args_runner(tool_name, raw_args)`.
3. Forward the returned (mutated/redacted) arguments to the actual tool body.

```python
# Example inside a tool wrapper
if tool_args_runner is not None:
    redacted_args = await tool_args_runner(tool.name, raw_arguments)
else:
    redacted_args = raw_arguments

# Execute the native tool with redacted_args
result = await tool.execute(**redacted_args)
```

### C. The `extract_tokens` Method
This method is executed **after** the agent has finished running. It takes the `raw_result` (the object returned by the framework's runner) and parses it to extract token metrics. The plugin must append these records to `metrics.api_calls` as `ApiCallRecord` objects.

```python
from argox.core.state import ApiCallRecord

def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
    # Framework-specific extraction logic
    input_tokens = raw_result.usage.prompt_tokens
    output_tokens = raw_result.usage.completion_tokens
    
    metrics.api_calls.append(
        ApiCallRecord(
            call_number=len(metrics.api_calls) + 1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
    )
```

### D. The `extract_output` Method
Normalizes the framework's raw response object into a plain python `str`. This is critical because every framework wraps its response differently (e.g., `RunResult`, `AIMessage`, or custom dicts).

---

## 4. Telemetry and OpenTelemetry Spans

Argox relies heavily on OpenTelemetry (OTel) for tracing. As established in **ADR-0009**:
* The `ArgoxManager` manages the root span `argox.agent.run`.
* The plugin is responsible for emitting a **child span** for every tool execution.
* The plugin should also enrich the root span with the model name.

### GenAI Semantic Conventions
When emitting spans, you must comply with the OpenTelemetry Semantic Conventions for GenAI:
1. **Model Name**: In `instrument`, or as soon as the model is known, set the attribute `gen_ai.request.model` on the active root span if available from the agent's configuration (e.g., `agent.model`).
2. **Tool Child Spans**:
   - Span Name: Must be exactly `execute_tool {tool_name}`.
   - Span Attributes:
     - `gen_ai.operation.name` set to `"execute_tool"`.
     - `gen_ai.tool.name` set to the tool's name.
   - **Critical PII Protection**: Never place raw tool arguments or results on the span attributes. If the tool execution raises an exception, mark the span status as `ERROR` and set the `error.type` attribute to the exception class name only. **Do not** write the exception message or stack trace to the span, as they routinely echo raw arguments (which may contain PII). Open the span with `record_exception=False` and `set_status_on_exception=False`.

### Tool Span Context Parenting
Because the tool execution is typically awaited inside the same asynchronous task as the agent execution, simply starting the child span with `tracer.start_as_current_span(...)` will parent it to the root span automatically.

Here is the correct implementation pattern for a tool wrapper:

```python
import traceback
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer("argox")

async def wrapped_tool_executor(tool, tool_args_runner, *args, **kwargs):
    # Prepare arguments
    raw_args = kwargs # or parse positional arguments into a dict
    if tool_args_runner is not None:
        args_to_use = await tool_args_runner(tool.name, raw_args)
    else:
        args_to_use = raw_args

    # Start the child span conforming to ADR-0009
    span_name = f"execute_tool {tool.name}"
    with tracer.start_as_current_span(
        span_name,
        record_exception=False,        # Crucial: Do not record raw exception messages (PII leak risk)
        set_status_on_exception=False, # Crucial: Manage status manually
    ) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool.name)
        
        try:
            result = await tool.execute(**args_to_use)
            return result
        except Exception as e:
            # Set status to ERROR and only record the class name in error.type
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("error.type", e.__class__.__name__)
            raise e
```

---

## 5. Auto-Discovery and Packaging

Argox supports auto-discovery of plugins (implemented via **DX-02**). This allows users to simply install your package (e.g., `pip install argox-plugin-custom`) and refer to it by name without needing manual import or registration boilerplate.

### Entry Point Registration
To enable auto-discovery, you must register your plugin class under the `argox.plugins` entry-point group.

#### Using `pyproject.toml` (Modern PEP 621)
```toml
[project.entry-points."argox.plugins"]
custom_framework = "argox_custom.plugin:CustomFrameworkPlugin"
```

#### Using `setup.py` (Legacy)
```python
setup(
    ...
    entry_points={
        "argox.plugins": [
            "custom_framework = argox_custom.plugin:CustomFrameworkPlugin",
        ],
    },
)
```

When `ArgoxManager` initializes, it queries `importlib.metadata.entry_points(group="argox.plugins")` and registers your plugin under the name `custom_framework`.

---

## 6. Testing Your Plugin

Testing is critical to ensure that your plugin behaves correctly, handles errors gracefully, and conforms to the OTel and argument mutation contracts.

### Key Testing Guidelines
1. **Mock External Providers**: Do not make real network calls to LLMs or external services during tests. Mock the framework's runner/client responses.
2. **Verify Tool Argument Interception**: Ensure that when a `tool_args_runner` is provided, it is invoked, and the mutated arguments are what actually get passed to the underlying tool.
3. **Verify OTel Spans**: Use OpenTelemetry's `InMemorySpanExporter` to inspect the emitted spans. Verify that:
   - Tool execution emits a child span named `execute_tool {name}`.
   - The child span has the correct `gen_ai.operation.name` and `gen_ai.tool.name` attributes.
   - In case of failure, the span is marked `ERROR` and `error.type` contains the exception class name, with **no** raw exception messages or stack traces recorded.

---

## 7. Reference Implementation

Below is a complete, self-contained reference implementation of a mock agent framework, an `ArgoxPlugin` integrating it, and a comprehensive test suite.

### A. The Mock Framework (`mock_framework.py`)
This represents the third-party agent framework you are integrating.

```python
# mock_framework.py
from typing import Any, Callable, List

class MockTool:
    def __init__(self, name: str, func: Callable):
        self.name = name
        self.func = func

    async def execute(self, **kwargs) -> Any:
        return await self.func(**kwargs)

class MockAgent:
    def __init__(self, name: str, model: str, tools: List[MockTool]):
        self.name = name
        self.model = model
        self.tools = tools

class MockRunResult:
    def __init__(self, output: str, prompt_tokens: int, completion_tokens: int):
        self.output = output
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
```

### B. The Argox Plugin (`plugin.py`)
This is the actual Argox plugin implementation.

```python
# plugin.py
import copy
from typing import Any
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from argox.interfaces.plugin import ArgoxPlugin, ToolArgsRunner
from argox.core.state import AgentRunMetrics, ApiCallRecord

# Import the mock framework components
from .mock_framework import MockAgent, MockTool

tracer = trace.get_tracer("argox")

class MockFrameworkPlugin(ArgoxPlugin):

    @property
    def name(self) -> str:
        return "mock_framework"

    def instrument(
        self,
        target: Any,
        metrics: AgentRunMetrics,
        tool_args_runner: ToolArgsRunner | None = None,
    ) -> Any:
        # Verify target type
        if not isinstance(target, MockAgent):
            raise TypeError("Target must be an instance of MockAgent")

        # Set the model name on the active root span if present
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.set_attribute("gen_ai.request.model", target.model)

        # As per ADR-0010, target is already a shallow copy. 
        # Rebind the tools list with wrapped versions to prevent mutating shared state.
        instrumented_tools = []
        for tool in target.tools:
            instrumented_tools.append(
                self._wrap_tool(tool, metrics, tool_args_runner)
            )
        
        target.tools = instrumented_tools
        return target

    def _wrap_tool(
        self,
        tool: MockTool,
        metrics: AgentRunMetrics,
        tool_args_runner: ToolArgsRunner | None,
    ) -> MockTool:
        original_func = tool.func

        async def wrapped_func(**kwargs):
            # 1. Record that the tool was called in metrics
            metrics.tools_called.append(tool.name)

            # 2. Handle pre-execution argument mutation if a runner is provided
            args_to_use = kwargs
            if tool_args_runner is not None:
                args_to_use = await tool_args_runner(tool.name, kwargs)

            # 3. Execute under an OTel child span conforming to ADR-0009
            span_name = f"execute_tool {tool.name}"
            with tracer.start_as_current_span(
                span_name,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                span.set_attribute("gen_ai.operation.name", "execute_tool")
                span.set_attribute("gen_ai.tool.name", tool.name)

                try:
                    res = await original_func(**args_to_use)
                    return res
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR))
                    span.set_attribute("error.type", e.__class__.__name__)
                    raise e

        # Return a new MockTool instance with the wrapped function
        return MockTool(name=tool.name, func=wrapped_func)

    def extract_tokens(self, raw_result: Any, metrics: AgentRunMetrics) -> None:
        # Extract from MockRunResult
        input_tokens = raw_result.prompt_tokens
        output_tokens = raw_result.completion_tokens
        
        metrics.api_calls.append(
            ApiCallRecord(
                call_number=len(metrics.api_calls) + 1,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
        )

    def extract_output(self, raw_result: Any) -> str:
        return raw_result.output
```

### C. The Plugin Test Suite (`test_plugin.py`)
This test suite validates the plugin behavior, OTel span attributes, and argument mutation.

```python
# test_plugin.py
import pytest
from unittest.mock import AsyncMock

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from argox.core.state import AgentRunMetrics
from .mock_framework import MockAgent, MockTool, MockRunResult
from .plugin import MockFrameworkPlugin

@pytest.fixture
def otel_exporter():
    """Sets up an in-memory OTel span exporter for verifying telemetry."""
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    
    # Temporarily set global tracer provider for the test
    old_provider = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)
    yield exporter
    trace.set_tracer_provider(old_provider)

@pytest.mark.asyncio
async def test_plugin_instrument_and_tool_execution(otel_exporter):
    # 1. Setup mock tool and agent
    async def sample_tool_func(x: int) -> str:
        return f"result: {x}"

    tool = MockTool(name="math_tool", func=sample_tool_func)
    agent = MockAgent(name="test_agent", model="gpt-4o", tools=[tool])
    metrics = AgentRunMetrics(run_id="test-run")

    # Mock tool_args_runner to increment the input argument
    async def mock_tool_args_runner(tool_name: str, args: dict) -> dict:
        mutated = args.copy()
        mutated["x"] = args["x"] + 10
        return mutated

    # 2. Instrument the agent
    plugin = MockFrameworkPlugin()
    
    # Start a dummy parent span to represent the manager's root span
    tracer = trace.get_tracer("argox")
    with tracer.start_as_current_span("argox.agent.run") as root_span:
        instrumented_agent = plugin.instrument(
            target=agent,
            metrics=metrics,
            tool_args_runner=mock_tool_args_runner
        )
        
        # Verify model name is set on the root span
        assert root_span.attributes.get("gen_ai.request.model") == "gpt-4o"

        # 3. Execute the instrumented tool
        inst_tool = instrumented_agent.tools[0]
        tool_result = await inst_tool.execute(x=5)

    # 4. Assertions
    # Verify the argument mutation (5 + 10 = 15)
    assert tool_result == "result: 15"
    # Verify tool call was recorded in metrics
    assert "math_tool" in metrics.tools_called

    # Verify OpenTelemetry child span
    spans = otel_exporter.get_finished_spans()
    # Expecting 2 spans: the child tool span and the parent root span
    assert len(spans) == 2
    
    tool_span = spans[0]
    assert tool_span.name == "execute_tool math_tool"
    assert tool_span.attributes.get("gen_ai.operation.name") == "execute_tool"
    assert tool_span.attributes.get("gen_ai.tool.name") == "math_tool"
    assert tool_span.status.is_ok

@pytest.mark.asyncio
async def test_tool_failure_span_conventions(otel_exporter):
    # 1. Setup a tool that fails
    async def failing_tool_func():
        raise ValueError("Database connection failed")

    tool = MockTool(name="db_tool", func=failing_tool_func)
    agent = MockAgent(name="test_agent", model="gpt-4o", tools=[tool])
    metrics = AgentRunMetrics(run_id="test-run")

    # 2. Instrument
    plugin = MockFrameworkPlugin()
    instrumented_agent = plugin.instrument(agent, metrics)

    # 3. Execute and expect exception
    inst_tool = instrumented_agent.tools[0]
    with pytest.raises(ValueError):
        await inst_tool.execute()

    # 4. Assertions on the error span (ADR-0009)
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    tool_span = spans[0]
    
    assert tool_span.name == "execute_tool db_tool"
    # Status must be ERROR
    assert tool_span.status.status_code == trace.StatusCode.ERROR
    # error.type must be the class name only
    assert tool_span.attributes.get("error.type") == "ValueError"
    # Ensure no raw exception message or stack trace is recorded on the span
    assert "exception" not in tool_span.attributes
    assert len(tool_span.events) == 0  # no exception event recorded

def test_token_and_output_extraction():
    plugin = MockFrameworkPlugin()
    metrics = AgentRunMetrics(run_id="test-run")
    raw_result = MockRunResult(output="Hello world", prompt_tokens=10, completion_tokens=15)

    # Test output extraction
    output = plugin.extract_output(raw_result)
    assert output == "Hello world"

    # Test token extraction
    plugin.extract_tokens(raw_result, metrics)
    assert len(metrics.api_calls) == 1
    record = metrics.api_calls[0]
    assert record.input_tokens == 10
    assert record.output_tokens == 15
    assert record.total_tokens == 25
```
