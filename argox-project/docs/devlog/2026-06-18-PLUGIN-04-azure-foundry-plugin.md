# [PLUGIN-04] Implement argox-plugin-azure-foundry

- **Date:** 2026-06-18
- **PR:** #147  ·  **Branch:** feat/PLUGIN-04-argox-plugin-azure-foundry
- **Status:** in-review

## What changed
- Created `argox-plugin-azure-foundry` package in `argox-plugins/`.
- Implemented `ArgoxAzureFoundryPlugin` with support for:
  - Tool interception via wrapping `azure.ai.projects.models.FunctionTool` functions.
  - Token extraction from `ThreadRun` usage metadata.
  - Compatibility with `ArgoxManager` tool-args processors.
- Added unit tests with mocked Azure AI Foundry SDK.
- Updated SDK overview documentation.
- Addressed PR review feedback (2026-06-22):
  - Solved sync event loop deadlock and nested loop issues in sync wrappers.
  - Normalized positional arguments via `inspect.signature` to ensure PII redaction works on all parameter types.
  - Added OTel `execute_tool` child span emission per tool call (conforming to PLUGIN-06).
  - Wired `gen_ai.request.model` extraction into active run spans for accurate pricing tracking (conforming to PLUGIN-05).
  - Masked exception message leaking in spans and metrics to protect PII.
  - Fixed demo script tool wrapping and message content extraction bugs.
- Addressed PR re-review feedback (2026-06-22):
  - Removed mutable state (`self._loop`, `self._executor`) from the plugin instance to prevent race conditions during concurrent runs. Loop references are now captured per-run via closure parameters.
  - Switched to a module-level `_SHARED_EXECUTOR` that is cleanly shutdown on exit using `atexit`.
  - Added tests covering active event loop execution branches (both run_coroutine_threadsafe and background thread pool paths).
  - Flattened bound arguments before passing to the runner and rebuilt them cleanly inside the wrapper supporting function signatures with `**kwargs` catch-all parameters.

## Why
Azure AI Foundry Agent Service (formerly part of Azure OpenAI Assistants) is a key enterprise framework. Providing a native plugin allows Argox to govern and monitor agents built on Microsoft's AI stack with zero changes to the agent's core logic.

## Notes / follow-ups
- The current implementation accesses the internal `_functions` attribute of `FunctionTool` to wrap callables. This is the only way to intercept tools in the current SDK version (v1.0.0b).
- Native hooks (`AsyncAgentEventHandler`) are only available for streaming. Non-streaming runs require the wrapping approach implemented here.
