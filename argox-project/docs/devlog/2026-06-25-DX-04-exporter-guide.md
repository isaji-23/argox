# [DX-04] Write EXPORTER_GUIDE.md for custom exporter authors

- **Date:** 2026-06-25
- **PR:** #182  ·  **Branch:** docs/DX-04-exporter-guide
- **Status:** in-review

## What changed
- `argox-project/docs/sdk/exporter-guide.md`:
  Created a comprehensive developer guide for writing custom exporters for the Argox SDK.
  - Defined the architectural differences between Argox Run Exporters (`ExporterBase`) and OpenTelemetry Span Exporters (`SpanExporter`).
  - Documented the `ExporterBase` contract (`export(metrics: AgentRunMetrics) -> None`), lifecycle, and strict fault-tolerance requirements (ensuring throwing exporters do not crash the agent's main execution flow and append errors to `metrics.exporter_errors`).
  - Documented the OTel `SpanExporter` contract (`export`, `shutdown`, `force_flush`), global telemetry registration via `init_telemetry(exporters=[...])`, and integration best practices (e.g., asynchronous batching, GenAI semantic conventions, and PII awareness).
  - Provided naming and packaging recommendations (`argox-exporter-<destination>`).
  - Offered unit testing guidelines to mock destinations and assert correct serialization, routing, and fault-tolerance behaviors.
  - Included a complete, self-contained reference implementation consisting of a mock HTTP Webhook Run Exporter, a Local JSONL Span Exporter, and their corresponding test suite.
- `argox-project/docs/devlog/_index.md`:
  Added a row for the `DX-04` ticket in the chronological devlog index.

## Why
Argox supports two different telemetry layers: high-level structured summaries (run metrics) and low-level raw traces (spans). However, there was no documentation clarifying the distinction between `ExporterBase` and OTel's `SpanExporter`, nor guidelines on how to build custom exporters for either. Creating this guide provides clear developer guidelines and ensures that third-party exporters follow correct architectural patterns—specifically regarding strict fault-tolerance (preventing exporter failures from breaking agent execution) and OpenTelemetry GenAI semantic conventions.
