# Argox SDK — Benchmarks

How to measure SDK overhead and run the benchmark suite. All commands run from
`argox-project/`.

## Overview

Two distinct measurements:

| Goal | Strategy | Gate |
|---|---|---|
| Pure SDK overhead (no LLM) | Mock runner returning a fixed payload | Always runnable |
| Component cost in isolation | Single processor/interface method | Always runnable |
| Realistic E2E (deterministic) | VCR cassette replay | Cassettes must be recorded first |
| Realistic E2E (real API) | Live API calls | `ARGOX_LIVE_BENCH=1` + API key |
| Concurrent load / throughput | `asyncio.gather(N)` with mock runner | Always runnable |

---

## Phase timings

`ArgoxManager.run()` wraps every lifecycle phase with `time.perf_counter()`
probes. Results land in `AgentRunMetrics.phase_timings` (milliseconds) and are
serialised as `phase_timings_ms` by `to_dict()`.

| Key | Phase measured |
|---|---|
| `processors_input` | `_run_processors("input")` |
| `policy_input` | `_policy.check_input()` |
| `tool_filter` | per-tool `is_tool_allowed()` loop |
| `agent_exec` | `runner(instrumented, prompt)` — pure LLM time |
| `processors_output` | `_run_processors("output")` |
| `policy_output` | `_policy.check_output()` |
| `export` | full `ExporterBase.export()` loop |

Keys for conditional phases (`policy_input`, `tool_filter`, `policy_output`) are
only present when the branch runs (i.e. a `PolicyClient` is registered).

**SDK overhead formula:**

```python
overhead_pct = (total_ms - phase_timings["agent_exec"]) / total_ms * 100
```

---

## Running the benchmarks

### Strategy A — SDK overhead (mock runner)

Replaces the LLM call with a stub that returns instantly. Total wall time minus
`agent_exec` = pure SDK cost.

```bash
pytest benchmarks/bench_overhead.py -v \
  --benchmark-columns=mean,stddev,median,rounds
```

Variants:
- `test_sdk_overhead_baseline` — no processors, no policy
- `test_sdk_overhead_with_processors` — PII redaction processor added
- `test_sdk_overhead_with_policy` — allow-all policy client added
- `test_sdk_overhead_phase_breakdown` — 100ms mock LLM; asserts overhead < 5%

### Strategy A (isolated) — component microbenchmarks

Each benchmark calls a single processor method directly, bypassing the manager.

```bash
pytest benchmarks/bench_components.py -v \
  --benchmark-columns=mean,stddev,median,rounds
```

Variants:
- `test_pii_processor_short_input` — `<100` chars, one phone number
- `test_pii_processor_medium_input` — `~500` chars, mixed PII
- `test_pii_processor_long_input` — `~10k` chars
- `test_pii_processor_clean_input` — no PII; measures regex-scan baseline
- `test_pii_processor_tool_args` — nested dict with PII values

### Strategy D — concurrent load

`asyncio.gather(N)` with mock runner. Surfaces event-loop blocking in processors
and OTel global-state contention under load.

```bash
pytest benchmarks/bench_concurrent.py -v \
  --benchmark-columns=mean,stddev,median,rounds
```

Variants: N = 10, 50, 100 concurrent runs; N = 50 with PII processor.

### Run all non-network benchmarks at once

```bash
pytest benchmarks/bench_overhead.py \
       benchmarks/bench_components.py \
       benchmarks/bench_concurrent.py \
  -v --benchmark-columns=mean,stddev,median
```

---

### Strategy C — VCR replay E2E

Records real API responses once; replays deterministically. Removes API variance
while preserving realistic payload shapes.

**Record cassettes (one-time, needs API key):**

```bash
pytest benchmarks/bench_e2e_replay.py --vcr-record=new_episodes -v
```

Cassettes are saved to `benchmarks/cassettes/` and committed. After that:

```bash
pytest benchmarks/bench_e2e_replay.py -v \
  --benchmark-columns=mean,stddev,median
```

### Strategy B — live API E2E

Real API calls. LLM response variance (1–10s) dominates SDK cost (`~1ms`);
use `rounds>=5` for any meaningful mean.

```bash
ARGOX_LIVE_BENCH=1 pytest benchmarks/bench_e2e_live.py -v \
  --benchmark-columns=mean,stddev,min,max,rounds
```

Skipped automatically when `ARGOX_LIVE_BENCH` is unset.

---

## Saving and comparing baselines

```bash
# Save current run as baseline JSON under .benchmarks/
pytest benchmarks/bench_overhead.py benchmarks/bench_components.py \
  --benchmark-autosave

# Compare next run against saved baseline (0001 = first saved run)
pytest benchmarks/bench_overhead.py benchmarks/bench_components.py \
  --benchmark-compare=0001
```

A regression is flagged when mean exceeds baseline by more than 20%.

---

## Baseline results (2026-06-03)

Measured on Python 3.13, Linux, `time.perf_counter`, `pytest-benchmark 5.2.3`.

### Overhead group

| Test | Mean | StdDev | Median |
|---|---|---|---|
| `test_sdk_overhead_with_policy` | 93.4 µs | 12.5 µs | 89.4 µs |
| `test_sdk_overhead_baseline` | 102.5 µs | 40.6 µs | 86.6 µs |
| `test_sdk_overhead_with_processors` | 127.9 µs | 38.7 µs | 113.2 µs |
| `test_sdk_overhead_phase_breakdown` | 101,110 µs | 261 µs | 101,037 µs |

> `phase_breakdown` uses `asyncio.sleep(0.1)` to simulate 100ms LLM latency —
> that 100ms is intentional. SDK overhead in that test is < 1%.

### Processors group

| Test | Mean | StdDev | Median |
|---|---|---|---|
| `test_pii_processor_clean_input` | 57.0 µs | 8.4 µs | 55.0 µs |
| `test_pii_processor_short_input` | 58.5 µs | 14.4 µs | 55.8 µs |
| `test_pii_processor_medium_input` | 59.9 µs | 12.2 µs | 55.0 µs |
| `test_pii_processor_long_input` | 64.2 µs | 22.5 µs | 56.3 µs |
| `test_pii_processor_tool_args` | 105.5 µs | 33.3 µs | 91.8 µs |

> PII regex cost is nearly flat across text sizes — the `asyncio` call overhead
> and event-loop scheduling dominate over the regex scan itself.

---

## Success thresholds

| Benchmark | Target | Status |
|---|---|---|
| SDK overhead (no processors, no policy) | < 5ms mean | PASS — ~93µs |
| SDK overhead % (100ms mock LLM) | < 5% | PASS — < 1% |
| PII processor short text (< 100 chars) | < 1ms | PASS — ~58µs |
| PII processor long text (~10k chars) | < 50ms | PASS — ~64µs |
| E2E replay (no tools) | baseline TBD | cassettes pending |
| E2E replay (with tool calls) | baseline TBD | cassettes pending |
