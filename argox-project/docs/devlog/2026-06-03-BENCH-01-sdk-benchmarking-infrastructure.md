# [BENCH-01] SDK benchmarking infrastructure

- **Date:** 2026-06-03 (live E2E + benchmark tuning landed 2026-06-05; review
  fixes landed 2026-06-07)
- **PR:** #119  ·  **Branch:** feat/BENCH-01-sdk-benchmarking-infra
- **Status:** in-review

## What changed

- **`argox-core/src/argox/core/state.py`** — `AgentRunMetrics` gains a new field
  `phase_timings: dict[str, float]` (default empty dict) that stores per-phase
  wall-clock cost in milliseconds. `to_dict()` serialises it as `"phase_timings_ms"`.
- **`argox-core/src/argox/core/manager.py`** — `ArgoxManager.run()` can wrap
  each lifecycle phase with `time.perf_counter()` probes and write the elapsed
  milliseconds into `metrics.phase_timings`. Probing is **opt-in** via the new
  `ArgoxManager(enable_phase_timings=False)` constructor flag (see review fixes
  below) and is implemented with a `_phase(metrics, name)` context manager. Keys
  recorded:

  | Key | Phase |
  |---|---|
  | `processors_input` | `_run_processors("input")` |
  | `policy_input` | `_policy.check_input()` |
  | `tool_filter` | per-tool `is_tool_allowed()` loop |
  | `agent_exec` | `runner(instrumented, processed_prompt)` |
  | `processors_output` | `_run_processors("output")` |
  | `policy_output` | `_policy.check_output()` |
  | `export` | full exporter loop in `finally` |

  When enabled, all keys are pre-seeded to `0.0` at run start, so every key is
  present even when its branch is skipped (no policy) or the run raises early.

- **`argox-core/pyproject.toml`** — `dev` extras add `pytest-benchmark>=4.0`
  and `pytest-recording>=0.13`.
- **`argox-project/pyproject.toml`** — `[tool.pytest.ini_options]` gains
  `benchmark` and `live` markers.
- **`argox-project/benchmarks/`** (new directory) — five benchmark modules:
  - `bench_overhead.py` — Strategy A: full `ArgoxManager.run()` with a mock
    runner; asserts SDK overhead < 5% when `agent_exec` is 100ms. All four
    overhead benchmarks set `disable_gc=True` (keeps GC pauses out of the
    measurement window — see errors.md).
  - `bench_components.py` — isolated `PiiRedactionProcessor` microbenchmarks
    across short/medium/long/clean text and `process_tool_args`.
  - `bench_payload.py` — Strategy C: realistic-payload lifecycle overhead
    (full lifecycle over ~480-char and ~11k-char mock outputs). Replaced the
    original `bench_e2e_replay.py`, whose `@pytest.mark.vcr` tests used a mock
    runner and empty cassettes and replayed nothing (see review fixes below).
  - `bench_e2e_live.py` — Strategy B: real API gate (`ARGOX_LIVE_BENCH=1`),
    implemented against an Azure AI Foundry deployment via a plain `AsyncOpenAI`
    client (`base_url`) and `set_default_openai_client` — not `AsyncAzureOpenAI`
    (see errors.md). `.env` loads when the gate is set; rounds/iterations are
    pinned with `benchmark.pedantic` so the billable call count is deterministic.
  - `bench_concurrent.py` — Strategy D: `asyncio.gather` at N=10/50/100
    concurrent runs.
- **`argox-project/docs/sdk/benchmarks.md`** (new) — run guide, phase-timing
  reference, baseline results (overhead / processors / live E2E), per-statistic
  overhead percentages, and success thresholds.

## Review fixes (2026-06-07)

PR review caught three issues; all fixed on this branch:

- **Phase timings gated off by default.** Probes were unconditionally on the
  production `run()` path. Added `ArgoxManager(enable_phase_timings=False)`; the
  probes (now a `_phase` context manager) are a no-op — no `perf_counter` call —
  when disabled, so production runs pay nothing. Benchmarks opt in: the
  phase-breakdown test uses a new `manager_timed` fixture.
- **No `KeyError` on the failure path.** `_phase` records in a `finally`, and all
  phase keys are pre-seeded to `0.0` when timing is enabled, so consumers reading
  `phase_timings[...]` never raise even when a phase is skipped or the run errors
  mid-flight.
- **`warmup=True` removed** from `test_sdk_overhead_with_processors` /
  `_with_policy` — it contradicted the documented "warmup rejected" decision and
  was inconsistent across the file.

Benchmark **measurement fix** (review finding #1): every benchmark drove its
coroutine with `asyncio.run(...)`, which builds and tears down a fresh event loop
per round — tens of µs plus heavy allocation that dominated the very SDK overhead
being measured. All benches now share one session-scoped `bench_loop` fixture
(`conftest.py`) and call `bench_loop.run_until_complete(...)`. Overhead medians
dropped from ~90–105 µs to ~38–49 µs (roughly half the old figure was loop
creation); StdDev tightened. The shared loop also fixed a latent live-bench bug
(`AsyncOpenAI` client bound to a closed loop on round 2) — see errors.md.

**Worthless-test rework (review findings #5/#6/#7):** three tests asserted
nothing falsifiable; reworked and backed by new behavioural tests:

- **#5 `phase_breakdown`** asserted `overhead < 5%` of an artificial 100 ms sleep
  — true by construction. Now asserts `agent_exec` actually captured the sleep,
  the **sum of non-`agent_exec` phases stays under an absolute 5 ms bound** (real,
  falsifiable scaffold ceiling), and `agent_exec` is the dominant phase.
- **#6 VCR replay** (`@pytest.mark.vcr` + mock runner + empty cassettes →
  replayed nothing) was removed. Replaced by `bench_payload.py` (Strategy C):
  full lifecycle over ~480-char and ~11k-char outputs, asserting PII is redacted
  end to end, plus a guard that lifecycle cost scales ~linearly, not
  quadratically, with output size. Confirmed cost is O(text length) (~24x payload
  → ~24x time). Dead `vcr_config` fixture and `cassettes/.gitkeep` removed.
- **#7 concurrency** used an instant mock, so `gather` ran sequentially and could
  not test concurrency. The mock now awaits a 5 ms latency so runs truly overlap;
  added `test_concurrent_overlap_no_blocking` asserting N=50 runs finish well
  under the sequential bound. Result: wall time stays flat (~6–7 ms) from N=10 to
  N=100 — the SDK does not serialize runs or block the loop.

New shared fixture `make_llm_response` (`conftest.py`) builds custom-sized mock
payloads for the payload benchmarks.

## Why

No benchmarking infrastructure existed. Without it, SDK overhead was
unmeasured and regressions invisible. `phase_timings` gives a concrete
breakdown of where time goes so bottlenecks can be located without profiling
every run.

The `bench_plan.md` working document defined the four strategies (mock runner,
VCR replay, live API, concurrent load) and the target thresholds:
< 5ms total SDK overhead (no processors/policy), < 5% overhead against a 100ms
mock LLM latency, < 1ms PII processor on short text.

## Notes / follow-ups

- The VCR replay strategy was removed (it replayed nothing). Strategy C is now
  `bench_payload.py` — realistic-payload lifecycle overhead with no network. If
  cassette-based replay is wanted later, it must drive a real client, not a mock.
- Live E2E was re-run on 2026-06-07 at N=30 with a third baseline
  (`test_live_agents_no_argox` — agents `Runner` without Argox; `_ROUNDS=30`).
  Confirmed the SDK overhead is **unresolvable live**: pure Argox came out at
  +39 ms median but **−74 ms on the mean** (impossible as real cost → proves it
  is LLM noise, inflated by a 4235 ms outlier in the agents baseline). Only the
  agents-framework cost resolves (+116 ms median over a raw call). The mock
  benches (~tens of µs) remain the authoritative overhead figure. See
  `docs/sdk/benchmarks.md` (Live E2E group, 2026-06-07).
- Benchmark tuning learned this round: pytest-benchmark leaves GC on by default
  and the `@benchmark` marker rejects `rounds`/`iterations` kwargs — both
  captured in errors.md.
- Consider adding a `make bench-save` baseline snapshot to CI so regressions
  surface automatically (this suite feeds the CI benchmark job tracked in #28 /
  INFRA-03).

### Deferred (minor, not blocking merge)

Low-priority review nits left open intentionally; pick up in a follow-up:

- **Trivial benchmark asserts** (`assert result is not None`, `len == N`) on the
  pure-throughput benchmarks — they smoke-test but validate no behaviour. Fine as
  guards; tighten only if a benchmark starts silently no-op'ing.
- **Live bench imports raise instead of skip.** `test_live_sdk_wrapped` /
  `test_live_agents_no_argox` import `agents` / `argox_openai` at runtime; if
  missing they `ImportError` rather than `pytest.skip`, even though gated by
  `ARGOX_LIVE_BENCH`. Wrap in try/`pytest.skip` for a clean skip on machines
  without the agents stack.
- **Pre-existing lint in `benchmarks/conftest.py`**: unused imports `os` and
  `ArgoxProcessor` (F401) plus import-sort (I001). Predate BENCH-01;
  `ruff check --fix` clears them.
