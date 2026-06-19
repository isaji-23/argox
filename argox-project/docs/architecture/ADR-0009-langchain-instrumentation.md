# ADR 0009: LangChain Instrumentation Approach

- **Status:** accepted
- **Date:** 2026-06-19
- **Deciders:** MarcosCS2004
- **Ticket:** [PLUGIN-03]

## Context

The Argox system requires deep instrumentation of AI frameworks to apply governance and policy filtering. For the LangChain plugin, we face an architectural mismatch: LangChain's execution engine (LCEL Runnables) heavily prioritizes immutability and declarative chain construction, while Argox assumes a mutable target agent that can be modified in-flight (like the OpenAI SDK agent).

Furthermore, LangChain's primary extension mechanism (`AsyncCallbackHandler`) is strictly observational. While it triggers `on_tool_start`, it does not allow the callback to intercept and mutate the arguments *before* the tool logic executes. This breaks Argox's core guarantee of redacting Personally Identifiable Information (PII) before the payload hits the tool.

## Decision

1. **Callback Injection:** Instead of modifying the `target` agent internally, `ArgoxLangChainPlugin.instrument` uses the `target.with_config({"callbacks": [...]})` pattern. This returns a newly wrapped `RunnableBinding`. 
2. **Tool Wrapper for PII:** To fulfill the pre-execution interception requirement, the plugin dynamically wraps the `_run` and `_arun` methods of all tools found inside `target.tools`. When executed, the wrappers suspend execution, run the asynchronous `ArgoxProcessor.process_tool_args` pipeline, and then resume the original tool logic with the sanitized inputs.

## Consequences

**Positive:**
- Complete compliance with GDPR/PII guarantees.
- Fits natively with LCEL without hacks on the core logic.
- Maintains the async-first approach using `AsyncCallbackHandler`.

**Negative:**
- Dynamic tool filtering (adding/removing tools per-invocation) is only supported if the target explicitly exposes a `.tools` attribute (e.g. `AgentExecutor`). Pure LCEL chains where tools are bound opaquely (`llm.bind_tools(tools)`) cannot be safely filtered post-construction. We accept this limitation for the MVP and document it.
