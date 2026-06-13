# Architecture Decision Records

Locked-in architectural decisions for the Argox SDK. Each ADR explains the
context, the decision, and the triggers that would justify revisiting it.
Add a new ADR with [`_template.md`](_template.md) whenever a change embodies a
decision future contributors should not silently re-open.

| ID | Title | Status |
|---|---|---|
| ADR-0001 | [Plugin interface evolution](plugin-interface-evolution.md) | accepted |
| ADR-0002 | [Collector ingest acknowledgement semantics](ADR-0002-collector-ingest-acknowledgement.md) | accepted |
| ADR-0003 | [Policy storage — content-addressed blobs committed via manifest CAS](ADR-0003-policy-storage-content-addressed-cas.md) | accepted |
| ADR-0004 | [Audit log — WORM hash chain over the blob StorageBackend](ADR-0004-audit-log-worm-hash-chain.md) | accepted |
| ADR-0005 | [Collector auth — hashed API keys for machines, OIDC JWTs for humans](ADR-0005-collector-auth-api-keys-and-oidc.md) | accepted |
