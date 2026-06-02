# [EXP-08] Rename ConsoleSpanExporter → ConsoleSpanLogger

- **Date:** 2026-05-25
- **PR:** #103  ·  **Branch:** feat/RenameConsoleSpanExporter
- **Status:** merged

## What changed

- `argox/exporters/console.py` removed; class renamed
  `ConsoleSpanExporter` → `ConsoleSpanLogger` and moved to
  `argox/observability/span_loggers.py`.
- `argox.observability` is now the canonical home for OTel-specific span
  processors and exporters (`ConsoleSpanLogger`, `JsonlSpanExporter`,
  `OTLPSpanExporter`); `argox.exporters` is reserved for `ExporterBase`
  implementations and is currently empty.
- `tests/test_console_exporter.py` → `tests/test_span_loggers.py`; test suite
  updated to import from the new path.
- All usages in `examples/` updated to `from argox.observability import ConsoleSpanLogger`.

## Why

`ConsoleSpanExporter` implied the class was the primary export path for
`AgentRunMetrics`, conflating two different contracts (`SpanExporter` vs
`ExporterBase`). The new name and module make the OTel lineage explicit: it is
a debug logger for OTel spans, not a general-purpose Argox exporter.
