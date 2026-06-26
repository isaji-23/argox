# Argox EU AI Act Compliance Mapping (Regulation 2024/1689)

This document provides a comprehensive technical mapping of the Argox SDK and Collector features to the compliance requirements of the **EU Artificial Intelligence Act (Regulation 2024/1689)**. It serves as authoritative compliance evidence for high-risk AI system deployments and is a core deliverable for the Master's Thesis (TFM) defense.

> [!NOTE]
> Argox is a technical observability and governance framework. It provides the infrastructure to enforce, record, and verify compliance controls, but does not constitute legal advice. Deployers must consult qualified legal counsel to validate their specific regulatory postures.

---

## 1. Compliance Architecture Overview

Argox is architected specifically to address the stringent governance requirements imposed on high-risk AI systems. By intercepting agent execution at the edge (SDK) and consolidating telemetry and policy decisions in a secure central control plane (Collector), Argox establishes a robust compliance boundary.

```mermaid
graph TD
    subgraph Client Application (SDK Edge)
        A[Agent Execution] -->|@argox.monitor| B[ArgoxManager]
        B -->|1. Intercept Input| C[Local/Remote Policy Client]
        B -->|2. In-Flight Transform| D[ArgoxProcessor Pipeline]
        B -->|3. Intercept Output| C
        B -->|4. Export Runs/Spans| E[HttpRunExporter / OTel]
    end
    subgraph Governance Plane (Collector Central)
        E -->|Ingest /v1/runs| F[Collector API]
        F -->|Store Run Record| G[StorageBackend / WORM Blob]
        F -->|Audit Append| H[Unified Audit Log Chain]
        C -->|Poll Policy| I[Policy Distribution / CAS]
    end
    style H fill:#f9f,stroke:#333,stroke-width:2px
    style G fill:#bbf,stroke:#333,stroke-width:1px
```

---

## 2. Article-by-Article Compliance Mapping

The following tables map each relevant AI Act article to the concrete technical controls, configurations, and code paths within the Argox project.

### Article 9: Risk Management System
* **Requirement:** High-risk AI systems must implement a continuous, systematic risk management system to identify, estimate, and mitigate risks associated with the AI system throughout its lifecycle.

| Dimension | Technical Implementation & Compliance Controls |
|---|---|
| **Regulatory Text Summary** | Establish and maintain a risk management system consisting of identification, analysis, estimation, and adoption of mitigation measures for risks. |
| **Argox Feature & Mechanism** | Real-time policy evaluation and active in-flight data sanitization. The `ArgoxManager` intercepts inputs, outputs, and tool calls, evaluating them against rules before allowing execution. The `ArgoxProcessor` pipeline transforms data in-flight (e.g., redacting PII or validating formats) to actively mitigate risk before LLM submission. |
| **Fail-Safe Design** | **Fail-Closed Semantics:** Exceptions or errors during policy evaluation are treated as policy violations, returning a blocking result (`PolicyResult.block()`) to prevent unsafe fallbacks. |
| **Out-of-the-Box Config** | • **Policy Rules:** Configured via a local YAML file (e.g. `policy.yaml`) or fetched remotely.<br>• **Strict Execution:** Register processors with strict enforcement: `ArgoxProcessor(strict=True)`. |
| **Concrete Code Paths** | • [`LocalPolicyClient`](../../argox-core/src/argox/policies/local_client.py): Local policy check orchestration.<br>• [`RemotePolicyClient`](../../argox-core/src/argox/policies/remote_client.py): Production-ready remote policy fetcher and in-memory evaluator.<br>• [`ArgoxManager`](../../argox-core/src/argox/core/manager.py): Intercepts agent lifecycle phases and runs policy/processor checks. |
| **Known Gaps & Roadmap** | • Integration of external automated risk classification APIs on prompt inputs.<br>• Support for dynamic risk score computation based on conversational context. |

---

### Article 12: Record-Keeping (Logging)
* **Requirement:** High-risk AI systems must technically enable the automatic recording of events ('logs') over their lifetime to ensure traceability, monitor functioning, and detect risks. Logs must be protected against modification or deletion.

| Dimension | Technical Implementation & Compliance Controls |
|---|---|
| **Regulatory Text Summary** | Enable automatic recording of events (traceability, incident detection, monitoring) throughout the system's lifetime. Ensure logs are protected from unauthorized modification or deletion. |
| **Argox Feature & Mechanism** | **Tamper-Evident WORM (Write-Once, Read-Many) Audit Log:** All governance events, run records, and span batches are consolidated into a single unified audit chain. Each record carries a monotonic sequence number `seq`, UTC timestamp, `actor`, `action`, `target`, and `payload_digest`. Integrity is secured via a cryptographic SHA-256 hash chain: `sha256(prev_hash \|\| canonical_json(record))`. The storage layer exposes no delete or overwrite API. |
| **Resilience & Self-Healing** | **Reconciliation Sweep:** Ingested runs are marked with a tri-state `audited` column. If a write succeeds but audit chaining fails (due to transient errors), a startup reconciliation task (`reconcile_run_audit`) reads unchained runs and appends them, guaranteeing eventually-consistent audit logs without blocking the runtime hot path. |
| **Out-of-the-Box Config** | • `max_segment_records` (default: 1000) for splitting segments in the `StorageBackend`. |
| **Concrete Code Paths** | • [`AuditLog`](../../argox-collector/src/argox_collector/audit/log.py): Cryptographic hash chain, append-only logic, and segment management.<br>• [`verify()`](../../argox-collector/src/argox_collector/audit/log.py#L255-L303): Walk verifier that detects gaps, sequence breaks, or content tampering.<br>• [`reconcile_run_audit` in DuckDB](../../argox-collector/src/argox_collector/index/duckdb.py): Database reconciliation sweep for the tri-state `audited` column. |
| **Known Gaps & Roadmap** | • **External Notarization:** Integrate RFC 3161 cryptographic timestamping authorities to notarize the chain's head hash.<br>• **Consensus-based Logging:** Real-time multi-signature signing of segments. |

---

### Article 13: Transparency and Provision of Information to Users
* **Requirement:** High-risk AI systems must be designed to ensure sufficiently transparent operation, enabling deployers to interpret the system's output and use it appropriately.

| Dimension | Technical Implementation & Compliance Controls |
|---|---|
| **Regulatory Text Summary** | High-risk AI systems must be transparent to enable deployers to interpret outputs, monitor operation, and understand how decisions are reached. |
| **Argox Feature & Mechanism** | **Route B Unified Telemetry:** Collects and persists deep conversational context that standard tracing spans omit. Persists the full prompt, final output, exact tool arguments, token counts, and complete policy evaluation reasons. This telemetry is visualized in the Web Dashboard via detailed run screens and Jaeger-style waterfall charts, enabling complete interpretability. |
| **Semantic Conventions** | Extends OpenTelemetry conventions with custom Argox attributes to log policy decisions, applied processors, and redactions directly in standard tracing streams. |
| **Out-of-the-Box Config** | • Configure the SDK with the `HttpRunExporter` targeting the Collector's `/v1/runs` endpoint.<br>• Annotate agent functions with the `@argox.monitor` decorator to enable automatic tracing. |
| **Concrete Code Paths** | • [`HttpRunExporter`](../../argox-core/src/argox/exporters/http_run.py): Transmits detailed agent run records.<br>• [`attributes.py`](../../argox-core/src/argox/semconv/attributes.py): Custom semantic conventions (e.g., `argox.policy.decision`, `argox.run.cost`).<br>• [`TraceDetailScreen.tsx`](../../argox-dashboard/src/components/screens/TraceDetailScreen.tsx) and [`WaterfallChart.tsx`](../../argox-dashboard/src/components/ui/WaterfallChart.tsx): Dashboard components rendering execution steps and policy outcomes. |
| **Known Gaps & Roadmap** | • Natural language generation of policy block explanations for non-technical operators.<br>• One-click PDF compliance report exports directly from the dashboard. |

---

### Article 14: Human Oversight
* **Requirement:** High-risk AI systems must be designed and developed in such a way that they can be effectively overseen by natural persons, including capability to intervene, override, or shut down the system.

| Dimension | Technical Implementation & Compliance Controls |
|---|---|
| **Regulatory Text Summary** | Enable natural persons to oversee the AI system, prevent or minimize risks, and intervene or override decisions. |
| **Argox Feature & Mechanism** | **Interactive Policy Control & Intervention:** Humans define policies with explicit `block` or `alert` actions. A `block` action immediately halts execution at the SDK edge, raising a `PolicyBlockError` in the host application to prevent unauthorized tool execution. The Web Dashboard features a Monaco-based live policy editor allowing real-time policy modification, complete with schema validation and dry-run testing against the Collector. |
| **Oversight UI** | The dashboard provides live telemetry feeds, showing active policy violations, allowing operators to immediately spot anomalies. |
| **Out-of-the-Box Config** | • Policy rules configured with `action: block` to enforce hard stops.<br>• Use the dashboard Monaco policy editor with automatic dry-run validation enabled. |
| **Concrete Code Paths** | • [`PolicyCache.evaluate`](../../argox-core/src/argox/policies/cache.py): Evaluates predicates and returns `PolicyResult.block(...)` or `PolicyResult.alert(...)`.<br>• `PoliciesScreen` (Dashboard): Monaco-based policy editor with dry-run validation. |
| **Known Gaps & Roadmap** | • **Human-in-the-Loop (HITL) Gates:** Implement an active pause-and-resume mechanism where a high-risk tool call is suspended until an operator approves it via the dashboard. |

---

### Article 50: Transparency Obligations for Certain AI Systems
* **Requirement:** Providers must ensure that AI systems intended to interact with natural persons are designed so that users are informed they are interacting with an AI system, unless obvious.

| Dimension | Technical Implementation & Compliance Controls |
|---|---|
| **Regulatory Text Summary** | Inform natural persons that they are interacting with an AI system, unless this is obvious from the circumstances. |
| **Argox Feature & Mechanism** | **Edge Disclosure Injection and Output Verification:** Argox supports two layers of disclosure controls:<br>1. **Active Injection:** An `ArgoxProcessor` running in the `output` phase can automatically append standard AI disclosure notices (e.g., *"This response was generated by an AI assistant."*) to the agent's output before it reaches the user.<br>2. **Passive Verification:** An `on_output` policy rule can check responses via regex or semantic evaluation to block any outputs that fail to include the required AI interaction disclosure. |
| **Out-of-the-Box Config** | • Configure an `on_output` policy rule with a regex check for disclosure keywords.<br>• Register a custom `DisclosureProcessor` in the `ArgoxManager` output pipeline. |
| **Concrete Code Paths** | • [`ArgoxProcessor`](../../argox-core/src/argox/interfaces/processor.py): Base class for in-flight content processors.<br>• [`LocalPolicyClient.check_output`](../../argox-core/src/argox/policies/local_client.py#L109-L134): Triggers output policy validation. |
| **Known Gaps & Roadmap** | • Out-of-the-box, pre-built `InteractionDisclosureProcessor` with multi-language template support. |

---

### Article 72: Reporting of Serious Incidents
* **Requirement:** Providers of high-risk AI systems must report any serious incident or malfunctioning of the AI system which constitutes a breach of obligations protecting fundamental rights to the market surveillance authority.

| Dimension | Technical Implementation & Compliance Controls |
|---|---|
| **Regulatory Text Summary** | Report any serious incident or malfunctioning that breaches fundamental rights obligations to the appropriate market surveillance authorities. |
| **Argox Feature & Mechanism** | **Governance Event Auditing and Alerting Integrations:** Critical policy violations (such as P0 safety rules or unauthorized database access attempts) are captured as distinct governance events (`kind="event"`) and written to the tamper-evident WORM audit log. Centralized OpenTelemetry metrics (`argox.policy.decisions`) can be exported to standard IT alerting infrastructures (e.g., Prometheus, Grafana, PagerDuty) to trigger incident reporting workflows immediately upon a breach. |
| **Auditing API** | The Collector Query API allows auditors to search, filter, and extract incident logs and associated conversational context to construct incident reports. |
| **Out-of-the-Box Config** | • Standard OTel exporter configuration to stream `argox.policy.decisions` metrics.<br>• Alerting thresholds configured on policy block counts. |
| **Concrete Code Paths** | • [`AuditLog.append(kind="event")`](../../argox-collector/src/argox_collector/audit/log.py#L171-L224): Appends incident entries into the WORM chain.<br>• [`attributes.py:METRIC_ARGOX_POLICY_DECISIONS`](../../argox-core/src/argox/semconv/attributes.py#L88): Policy decision metric definition.<br>• [`Query API Router`](../../argox-collector/src/argox_collector/routers/query.py): Query endpoint to retrieve incident records. |
| **Known Gaps & Roadmap** | • **Incident Report Generator:** A dashboard feature to auto-generate standardized incident reports matching EU Member State reporting templates.<br>• Webhook integrations to push incident details directly to compliance officers. |

---

## 3. Cryptographic Verification Example

The internal integrity of the record-keeping log (Article 12) can be mathematically verified by any third-party auditor. Below is the conceptual verification algorithm executed by the Collector's `/api/v1/audit/verify` endpoint:

```python
# Conceptual verification loop matching AuditLog.verify()
prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"  # GENESIS_HASH
expected_seq = 1

for entry in audit_log.iter_entries():
    record = entry.record
    
    # 1. Assert sequence continuity
    assert record.seq == expected_seq, f"Sequence gap: expected {expected_seq}, got {record.seq}"
    
    # 2. Assert hash chain link
    assert record.prev_hash == prev_hash, f"Hash chain broken at seq {record.seq}"
    
    # 3. Assert record content integrity
    recomputed_hash = record.compute_hash()
    assert recomputed_hash == entry.hash, f"Content tampered at seq {record.seq}"
    
    prev_hash = entry.hash
    expected_seq += 1

print(f"Verification successful. Verified {expected_seq - 1} entries. Hash chain is intact.")
```

Through this cryptographic structure, any unauthorized modification of past records (e.g., altering a prompt to hide a policy breach) or deletion of segments will cause a verification failure at the next audit interval, satisfying the non-repudiation and deletion protection requirements of **Article 12**.
