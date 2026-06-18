# [PLUGIN-04] Implement argox-plugin-azure-foundry

- **Date:** 2026-06-18
- **PR:** #139  ·  **Branch:** feat/PLUGIN-04-foundry-agent-plugin
- **Status:** in-review

## What changed
- Created `argox-plugin-azure-foundry` package in `argox-plugins/`.
- Implemented `ArgoxAzureFoundryPlugin` with support for:
  - Tool interception via wrapping `azure.ai.projects.models.FunctionTool` functions.
  - Token extraction from `ThreadRun` usage metadata.
  - Compatibility with `ArgoxManager` tool-args processors.
- Added unit tests with mocked Azure AI Foundry SDK.
- Updated SDK overview documentation.

## Why
Azure AI Foundry Agent Service (formerly part of Azure OpenAI Assistants) is a key enterprise framework. Providing a native plugin allows Argox to govern and monitor agents built on Microsoft's AI stack with zero changes to the agent's core logic.

## Notes / follow-ups
- The current implementation accesses the internal `_functions` attribute of `FunctionTool` to wrap callables. This is the only way to intercept tools in the current SDK version (v1.0.0b).
- Native hooks (`AsyncAgentEventHandler`) are only available for streaming. Non-streaming runs require the wrapping approach implemented here.
