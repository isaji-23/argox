# [DX-05] Write PROCESSOR_GUIDE.md for in-flight data transformation authors

- **Date:** 2026-06-25
- **PR:** #183  ·  **Branch:** docs/DX-05-processor-guide
- **Status:** in-review

## What changed
- `argox-project/docs/sdk/processor-guide.md`:
  Created a comprehensive developer guide for writing custom in-flight data transformation processors for the Argox SDK.
  - Defined the role of `ArgoxProcessor` and contrasted it against OpenTelemetry's `SpanProcessor`.
  - Detailed the three asynchronous transformation points: `process_input`, `process_tool_args`, and `process_output`.
  - Documented lifecycle execution order, the role of `RunContext`, and pipeline mechanics within `ArgoxManager.run`.
  - Explained **fail-open vs. strict semantics** in detail, highlighting how the SDK handles exceptions (logging OTel events and continuing vs. marking spans as `ERROR` and propagating exceptions to abort execution).
  - Highlighted the **tool arguments deep-copying pattern** where the Manager copies arguments beforehand to prevent partial transformation leakage.
  - Provided best practices for performance (local operations, network timeouts) and the strict requirement to never suppress `asyncio.CancelledError`.
  - Described automatically emitted OTel span events (`argox.processor.applied` and `argox.processor.error`) and their associated attributes.
  - Provided testing guidelines and a complete, self-contained reference implementation including a regex-based `RedactorProcessor` (for credit cards and API keys) and a matching `pytest` unit test suite.
- `argox-project/docs/devlog/_index.md`:
  Added a row for the `DX-05` ticket in the chronological devlog index.

## Why
Argox features a real-time data transformation pipeline designed to protect data sovereignty (e.g. redacting PII before it reaches LLMs or tools). However, developers lacked clear guidelines on how to build custom processors, understand pipeline execution order, handle errors gracefully (fail-open), or avoid latency on the hot path. Providing this guide lowers the barrier to entry for creating security and compliance plugins, while reinforcing key engineering patterns like deep copying tool arguments and propagating cancellations.
