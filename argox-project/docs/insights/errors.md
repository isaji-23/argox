# Errors & Fixes Log

Debugging knowledge captured as it happens. Append newest-first. The goal is
that a problem solved once is never re-debugged from scratch — record the
symptom (verbatim error string when possible), the root cause, the fix, and the
guard that prevents regression. Populated by `/argox-doc` when a session hits
and resolves a non-trivial error.

<!-- Add new entries directly below this line, newest first. -->

## 2026-06-05 — Overhead benchmark `with_processors` showed 7x StdDev variance  [BENCH-01]
- **Symptom:** `test_sdk_overhead_with_processors` reported `StdDev 70.3us (7.33)` with `Mean 122.8us` far above `Median 99.4us`, while sibling tests sat near 1.0-1.3x. Strong right-skewed distribution.
- **Root cause:** Not the regex. The benchmark input is constant (`process_input` is a no-op since `redact_input=False`; only `process_output` runs over a fixed 29-char string), so per-round work is deterministic. The PII pipeline allocates many transient objects per call (entity `set`, 8 `finditer` iterators, `EntityMatch` tuples, `_resolve_overlaps` dict/sorted/list, `_apply` pieces list). CPython's generational GC fires on allocation thresholds, so the probability a GC sweep lands inside a measured round scales with allocations. `baseline` allocates almost nothing, so its distribution stays tight; `with_processors` catches frequent GC pauses → fat right tail. pytest-benchmark does **not** disable GC by default (`disable_gc=False`), so the pauses entered the measurement.
- **Fix:** Add `disable_gc=True` to the `@pytest.mark.benchmark` markers in `argox-project/benchmarks/bench_overhead.py`. StdDev collapsed 70.3us (7.33x) → 17.7us (1.31x) and Mean converged to Median (skew gone), confirming GC as the source.
- **Guard:** `disable_gc=True` on all four overhead benchmarks. `warmup=True` was trialed and **rejected** — it inflates round count and wall-time (~3.5s → ~13s), widening the sampling window and catching more host-scheduler noise, raising StdDev instead of lowering it. For these microbenchmarks track **median** (robust); residual Mean/StdDev reflects host load and varies per session, not the SDK.

## Format

```markdown
## YYYY-MM-DD — <symptom one-liner>  [TICKET-NN]
- **Symptom:** <error string / observed behavior>
- **Root cause:** <why>
- **Fix:** <what resolved it; file:line>
- **Guard:** <test added / check to prevent regression>
```
