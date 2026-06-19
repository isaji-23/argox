# ADR-0008: Azure AI Foundry Tool Interception via wrapping

- **Status:** accepted
- **Date:** 2026-06-18
- **Deciders:** MarcosCS2004
- **Ticket:** [PLUGIN-04]

## Context
Azure AI Foundry Agent Service SDK (v1.0.0b) does not provide a native "hooks" or "callback" system for non-streaming agent runs. Unlike the `openai-agents` SDK which allows setting `agent.hooks`, Azure Foundry requires a different approach to intercept and monitor tool calls and to mutate tool arguments (Processors).

## Decision
We will implement tool interception by wrapping the user-provided functions within the `azure.ai.projects.models.FunctionTool` object. 

The `ArgoxAzureFoundryPlugin` will:
1. Iterate over `agent.tools`.
2. Identify `FunctionTool` instances.
3. Access the internal `_functions` dictionary (implementation detail of the current SDK).
4. Replace each callable with an async wrapper that:
   - Records `ToolCallRecord` in `AgentRunMetrics`.
   - Executes the Argox Processor chain (if `tool_args_runner` is provided).
   - Handles both sync and async underlying functions.
5. Reconstruct the `FunctionTool` with the wrapped callables.

## Consequences
- **Pros:**
  - Zero code changes required for the user's tool functions.
  - Supports both observability (metrics) and governance (processors).
  - Framework-agnostic at the `ArgoxManager` level.
- **Cons:**
  - Relies on an internal SDK attribute (`_functions`). If the SDK structure changes, the plugin will need an update.
  - Performance: negligible overhead from the async wrapper.
  - Only supports `FunctionTool`. Hosted tools (Code Interpreter, etc.) remain server-side and are not currently intercepted for argument mutation (consistent with the OpenAI plugin).

## Alternatives Considered
- **Native Events:** `AsyncAgentEventHandler` is only available for streaming (`with_stream`). It doesn't support argument mutation, only observation.
- **Client Wrapping:** Wrapping `AIProjectClient.agents.create_and_process_run` was considered but rejected because Argox's core design instruments the "Agent" object, not the client.
