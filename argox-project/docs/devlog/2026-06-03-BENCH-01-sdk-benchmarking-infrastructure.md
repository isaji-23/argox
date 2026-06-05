# [BENCH-01] SDK benchmarking infrastructure

- **Date:** 2026-06-03
- **PR:** n/a (working tree, `dev`)
- **Status:** in-review

## What changed

- **`argox-core/src/argox/core/state.py`** — `AgentRunMetrics` gains a new field
  `phase_timings: dict[str, float]` (default empty dict) that stores per-phase
  wall-clock cost in milliseconds. `to_dict()` serialises it as `"phase_timings_ms"`.
- **`argox-core/src/argox/core/manager.py`** — `ArgoxManager.run()` now wraps
  each lifecycle phase with `time.perf_counter()` probes and writes the elapsed
  milliseconds into `metrics.phase_timings`. Keys recorded:

  | Key | Phase |
  |---|---|
  | `processors_input` | `_run_processors("input")` |
  | `policy_input` | `_policy.check_input()` |
  | `tool_filter` | per-tool `is_tool_allowed()` loop |
  | `agent_exec` | `runner(instrumented, processed_prompt)` |
  | `processors_output` | `_run_processors("output")` |
  | `policy_output` | `_policy.check_output()` |
  | `export` | full exporter loop in `finally` |

  Conditional phases (`policy_input`, `tool_filter`, `policy_output`) are only
  written when the branch actually executes (i.e. `self._policy is not None`).

- **`argox-core/pyproject.toml`** — `dev` extras add `pytest-benchmark>=4.0`
  and `pytest-recording>=0.13`.
- **`argox-project/pyproject.toml`** — `[tool.pytest.ini_options]` gains
  `benchmark` and `live` markers.
- **`argox-project/benchmarks/`** (new directory, untracked) — five benchmark
  modules:
  - `bench_overhead.py` — Strategy A: full `ArgoxManager.run()` with a mock
    runner; asserts SDK overhead < 5% when `agent_exec` is 100ms.
  - `bench_components.py` — isolated `PiiRedactionProcessor` microbenchmarks
    across short/medium/long/clean text and `process_tool_args`.
  - `bench_e2e_replay.py` — Strategy C: VCR cassette replay (cassettes to be
    recorded separately).
  - `bench_e2e_live.py` — Strategy B: real API gate (`ARGOX_LIVE_BENCH=1`);
    stub implementations left as `pytest.skip` pending runner wiring.
  - `bench_concurrent.py` — Strategy D: `asyncio.gather` at N=10/50/100
    concurrent runs.

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

- VCR cassettes in `benchmarks/cassettes/` are empty — record with
  `ARGOX_RECORD_CASSETTES=1 pytest benchmarks/bench_e2e_replay.py --vcr-record=new_episodes`.
- `bench_e2e_live.py` stubs need real `openai` runner wiring before they are
  meaningful.
- Consider adding a `make bench-save` baseline snapshot to CI once cassettes
  are recorded, so regressions surface automatically.
