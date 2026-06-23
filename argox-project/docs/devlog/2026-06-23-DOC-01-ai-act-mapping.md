# [DOC-01] Write docs/compliance/ai-act-mapping.md

- **Date:** 2026-06-23
- **PR:** #98  ·  **Branch:** docs/DOC-01-ai-act-mapping
- **Status:** in-review

## What changed

- Created `docs/compliance/ai-act-mapping.md` mapping Argox features to the EU AI Act.
- Created `argox-project/docs/compliance/ai-act-mapping.md` under the authoritative living docs directory.
- Mapped six key articles of the EU AI Act (Regulation 2024/1689) to specific SDK and Collector components:
  - **Art. 9 (Risk Management System):** Mapped to `ArgoxManager`, `LocalPolicyClient`, and `RemotePolicyClient` fail-closed design.
  - **Art. 12 (Record-Keeping):** Mapped to the `AuditLog` WORM SHA-256 hash chain and DuckDB/SQLite reconciliation sweep (`reconcile_run_audit`).
  - **Art. 13 (Transparency to Users):** Mapped to Route B unified run telemetry (`HttpRunExporter`), OpenTelemetry semantic conventions, and the Web Dashboard.
  - **Art. 14 (Human Oversight):** Mapped to blocking/alerting policy actions and the Monaco live policy editor with dry-run validation.
  - **Art. 50 (Transparency Obligations):** Mapped to `ArgoxProcessor` in-flight disclosure injectors and output-trigger checks.
  - **Art. 72 (Incident Reporting):** Mapped to `AuditLog` event-kind chaining and `argox.policy.decisions` metrics for alerting.

## Why

- To provide the regulatory compliance mapping referenced in the architecture overview.
- Acts as a core compliance artifact required for the Master's Thesis (TFM) defense.
- Provides developers and operators with explicit setup and configuration guidelines for out-of-the-box compliance.
