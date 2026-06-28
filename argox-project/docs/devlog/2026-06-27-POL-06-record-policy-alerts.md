# [POL-06] Record policy alerts in run metrics

- **Date:** 2026-06-27
- **PR:** (pending)  ·  **Branch:** dev
- **Status:** in-review

## What changed
- `ArgoxManager.run` (`argox-core/src/argox/core/manager.py`) now handles the
  `alert` action at all three policy stages. Previously only `block`
  (`PolicyResult.passed is False`) had an effect; alert results
  (`passed is True` with a `rule_id`) were silently discarded.
- Input policy (`check_input`) and output policy (`check_output`): when the
  result passes but carries a `rule_id`, the reason is appended to
  `metrics.policy_violations` and a `record_policy_decision(decision="alert",
  rule_id=...)` is emitted; the run continues (no `PermissionError`).
- Tool filter (`is_tool_allowed`): an alerted tool stays in
  `metrics.tools_available` (not stripped) and is flagged the same way —
  violation recorded, `decision="alert"` metric emitted.
- `PolicyResult.ok()` (empty `rule_id`) still takes the `decision="ok"` path, so
  clean runs keep `policy_violations == []`.
- Tests: new `_AlertInputPolicy` / `_AlertOutputPolicy` / `_AlertToolPolicy`
  stubs and three `TestPolicy` cases asserting that alerts record a violation,
  keep `*_policy_passed is True`, leave `success is True`, and (for tools) keep
  the tool available (`argox-project/tests/test_manager.py`).

## Why
- `PolicyCache.evaluate` already returned `PolicyResult.alert(...)` for `alert`
  rules (`policies/cache.py`), and the policy parser/schema accept the `alert`
  action, but the manager only branched on `not result.passed`. The net effect
  was that **alert rules did nothing**: no violation recorded, no decision
  metric, nothing surfaced to exporters, the dashboard, or the demo UI.
- Recording alerts in `policy_violations` (rather than a new field) keeps
  `AgentRunMetrics.to_dict` and the `/v1/runs` payload stable, so the dashboard
  Run Record and the local demo front show alerts with no schema change.

## Notes / follow-ups
- `policy_violations` now holds both block reasons (run failed) and alert
  reasons (run succeeded). Consumers distinguish the two via the
  `input_policy_passed` / `output_policy_passed` flags and `success`.
- A dedicated `policy_alerts` field could later separate the two if a consumer
  needs alerts without inspecting the pass flags; deferred as unnecessary now.
