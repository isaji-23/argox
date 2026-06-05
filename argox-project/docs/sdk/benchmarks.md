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
  --benchmark-columns=mean,median,stddev,min,max,rounds
```

Skipped automatically when `ARGOX_LIVE_BENCH` is unset.

> Keep `median` and `min` in the columns: LLM outliers inflate the mean, so the
> median is the robust central value and the min is the cleanest overhead signal.

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

| Test | Mean | StdDev | Median | Overhead vs baseline (median) |
|---|---|---|---|---|
| `test_sdk_overhead_with_policy` | 93.4 µs | 12.5 µs | 89.4 µs | +3% |
| `test_sdk_overhead_baseline` | 102.5 µs | 40.6 µs | 86.6 µs | — (reference) |
| `test_sdk_overhead_with_processors` | 127.9 µs | 38.7 µs | 113.2 µs | +31% |
| `test_sdk_overhead_phase_breakdown` | 101,110 µs | 261 µs | 101,037 µs | <1% vs LLM* |

> Percentages are vs the `baseline` median. They are µs-level deltas — the PII
> processor (+31%, ~+27µs) is the only measurable cost; the policy stub is in
> the noise. `phase_breakdown`'s figure is a different ratio: SDK overhead as a
> share of a 100ms mock LLM (`asyncio.sleep(0.1)`), intentionally < 1%.

**Why the processor's "+31%" is not a concern:**

1. **It is +31% of microseconds.** ~+27µs over an 87µs scaffold. The percentage
   looks large only because the baseline is tiny; the honest metric at this
   scale is the absolute delta (~27µs), not the ratio.
2. **It disappears in a real run.** Against a real ~1.4s LLM call, ~27µs is
   ~0.002%. The live E2E group confirms it: the SDK path is indistinguishable
   from LLM noise (min-to-min ≈ 1ms).
3. **The cost is real work, not waste.** Per output, the processor runs 8
   compiled-regex scans (EMAIL, PHONE, IPV4, IPV6, IBAN, CREDIT_CARD, ES_DNI,
   ES_NIE), post-match validators (Luhn, DNI/NIE control letter, IBAN/IPv4
   shape), overlap resolution, plus one extra `await`, one span event, and one
   OTel metric record. Bounded O(len(text)).
4. **It is fixed cost, not input-scaling.** The processors group shows the PII
   processor at ~55µs median on clean input vs ~56µs on ~10k chars — flat. The
   `asyncio` hop and event-loop scheduling dominate, not the regex, so the
   delta stays in the tens of µs even on large outputs.

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

### Live E2E group (2026-06-05)

**Run conditions:** Azure AI Foundry `gpt-4o-mini` deployment (OpenAI-compatible
surface), 2026-06-05, 12th Gen i7-1280P, Python 3.13.13. Each test runs via
`benchmark.pedantic` with 5 timed rounds + 1 warmup × 1 iteration → 6 billable
calls per test, **12 calls total**. Output capped at 200 tokens; prompt ~25
tokens; `openai-agents` tracing disabled. `bare` is a raw `chat.completions`
call; `sdk_wrapped` runs the same model through the `openai-agents` `Runner`
under `ArgoxManager` (openai plugin only, no processors or policy).

**Cost:** the benchmark JSON records timings only, not token usage. From the caps
(≤240 input / ≤2400 output tokens over 12 calls), the run cost an estimated
**≤ $0.0015** on gpt-4o-mini — sub-cent.

| Test | Mean | Median | StdDev | Min | Max |
|---|---|---|---|---|---|
| `test_live_bare_openai` | 1423 ms | 1398 ms | 100 ms | **1318 ms** | 1568 ms |
| `test_live_sdk_wrapped` | 1550 ms | 1430 ms | 348 ms | **1319 ms** | 2167 ms |

**Relative overhead (`sdk_wrapped` vs `bare`), per statistic:**

| Statistic | bare | sdk_wrapped | Overhead |
|---|---|---|---|
| Mean | 1423 ms | 1550 ms | +8.9% |
| Median | 1398 ms | 1430 ms | +2.2% |
| Min | 1318 ms | 1319 ms | **+0.08%** |
| Max | 1568 ms | 2167 ms | +38% |

> The overhead % collapses mean → median → min as noise is stripped out. The min
> (+0.08%, ~1 ms) is the true overhead floor; the +8.9% mean and +38% max are
> inflated by a single slow LLM response, not by the SDK.

**How to read this — the SDK overhead is below the noise floor here.**

- The LLM dominates wall time (~1.4 s) with 100–350 ms of round-to-round
  variance. Argox overhead measured in isolation is ~100 µs (mock bench), so at
  N=5 it is unresolvable against the LLM's own jitter.
- **Do not read the mean delta (127 ms) as SDK overhead.** It is LLM/network
  variance. The `sdk_wrapped` StdDev (348 ms, 3.5× `bare`) comes from a single
  2167 ms slow response, which also inflates its mean.
- The only clean signal at this sample size is **min-to-min: 1319 − 1318 ≈ 1 ms**,
  consistent with the docstring's `~1ms` claim and with the mock overhead bench.
- **Caveat:** `bare` is one HTTP call; `sdk_wrapped` is the full `openai-agents`
  agent loop (tool resolution, response parsing) *plus* Argox. The delta is
  "agent stack + Argox" vs "raw call", not pure Argox cost.
- **To resolve Argox overhead live:** use N≥30 to average out LLM variance, add
  a third baseline (agents `Runner` *without* Argox) to isolate the SDK layer,
  and compare on **min or a high percentile**, never the mean.

**Takeaway:** consistent with the mock benchmarks — Argox overhead is negligible
(µs-to-low-ms) and disappears into LLM latency in any real deployment.

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
