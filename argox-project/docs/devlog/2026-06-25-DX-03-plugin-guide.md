# [DX-03] Write PLUGIN_GUIDE.md for community plugin authors

- **Date:** 2026-06-25
- **PR:** #181  ·  **Branch:** docs/DX-03-plugin-guide
- **Status:** in-review

## What changed
- `argox-project/docs/sdk/plugin-guide.md`:
  Created a comprehensive developer guide for writing custom agent framework plugins for the Argox SDK.
  - Defined the role of plugins and their position in the Argox ecosystem.
  - Detailed each method and property of the `ArgoxPlugin` contract: `name`, `instrument`, `extract_tokens`, and `extract_output`.
  - Described the pre-execution tool argument interception pattern using `tool_args_runner`, ensuring compatibility with Argox's PII redaction and transformation processors.
  - Documented OpenTelemetry (OTel) integration requirements, specifically child span creation for tool execution (`execute_tool {name}`) conforming to GenAI semantic conventions, context parenting, and PII protection (preventing leakage of arguments/exceptions via spans).
  - Outlined packaging and auto-discovery registration using Python entry points in `pyproject.toml`.
  - Provided testing guidelines, including mocks, `pytest` fixtures, OTel span verification, and assertion checks.
  - Included a complete, self-contained reference implementation with a mock framework, a plugin, and its corresponding test suite.
- `argox-project/docs/devlog/_index.md`:
  Added a row for the `DX-03` ticket in the chronological devlog index.

## Why
Argox is designed to be a framework-agnostic SDK for AI agent governance and observability, but developers and community authors lacked clear documentation on how to build and integrate custom framework plugins (e.g., for frameworks beyond the built-in OpenAI and Azure Foundry plugins). Providing a detailed, technical guide with a complete reference implementation and test suite lowers the friction for community adoption and guarantees architectural consistency across plugins (such as correct OTel semantic conventions, pre-execution PII redaction, and thread-safe shallow copying).
