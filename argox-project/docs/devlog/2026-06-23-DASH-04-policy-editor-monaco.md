# [DASH-04] Policy editor with Monaco (live YAML editing)

- **Date:** 2026-06-23
- **PR:** #91  ·  **Branch:** feat/DASH-04-policy-editor-monaco
- **Status:** in-review

## What changed
- Added `POST /api/v1/policies/validate` validation endpoint in the Collector, which parses YAML content and runs Pydantic model validation on the policy document structure, returning the validation status and parsed rules.
- Extended the `GET /api/v1/policies/{policy_id}` and `GET /api/v1/policies/{policy_id}/v{version}` endpoints to return raw YAML payloads when requested with an Accept header of `application/x-yaml` or `text/yaml`.
- Created the `PoliciesScreen` React component in the dashboard embedding Monaco Editor for live policy YAML editing and Monaco Diff Editor for comparing policy versions side-by-side.
- Added a "Validate Schema" dry-run button that checks policy YAML against the server validation endpoint without persistence.
- Added a "Save Version" action that validates the YAML on the server first, and on success saves a new version of the policy via `PUT /api/v1/policies/{id}`.
- Re-generated the OpenAPI specification contract and frontend TypeScript client definitions.

## Why
- Governance administrators need to be able to safely inspect, edit, and publish policy rules directly in the web dashboard. Monaco Editor provides syntax highlighting and validation feedback, ensuring that only syntactically and logically correct policies can be saved. Returning raw YAML from the endpoints keeps the source of truth cleanly in git/storage without needing a JS YAML parsing/formatting layer on the client.
