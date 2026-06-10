# Errors & Fixes Log

Debugging knowledge captured as it happens. Append newest-first. The goal is
that a problem solved once is never re-debugged from scratch — record the
symptom (verbatim error string when possible), the root cause, the fix, and the
guard that prevents regression. Populated by `/argox-doc` when a session hits
and resolves a non-trivial error.

<!-- Add new entries directly below this line, newest first. -->

## 2026-06-10 — NaN attribute values poison metrics and silently drop spans  [COL-04]
- **Symptom:** Two failure modes found by audit, not in production: (1) an OTLP
  double attribute carrying NaN (or a string `"nan"`) lands in `run_cost`, after
  which `SUM(run_cost)` returns NaN and the `/api/v1/metrics/*` response fails
  to JSON-encode (starlette serialises with `allow_nan=False`) → 500. (2) A NaN
  inside the span `attributes` dict makes `json.dumps` emit a bare `NaN`
  literal, which DuckDB's JSON column parser rejects at insert — the per-row
  fallback then skips the row, so the span vanishes without any client error.
- **Root cause:** `float("nan")` passes `float()` coercion and `json.dumps`
  by default (`allow_nan=True` produces JSON-invalid output); nothing in the
  ingest → index path checked finiteness. Additionally, attribute
  serialisation ran during batch preparation, *before* the
  `executemany`/per-row fallback, so a non-serializable attribute raised
  `TypeError` and lost the entire batch with no row ever written.
- **Fix:** PR #131 — `math.isfinite` guards in `_as_float` (ingest) and
  `_finite_or_none` (index write path); `_encode_attributes` serialises with
  `allow_nan=False` and degrades bad values to strings via `_json_safe`;
  cost/latency aggregates filter `isfinite(...)` to neutralise rows written
  before the fix.
- **Guard:** `tests/test_index.py` (NaN attributes keep the row, non-finite
  doubles stored as NULL, metrics ignore poisoned rows, unserializable
  attributes don't drop the batch) and `tests/test_otlp_ingest.py`
  (non-finite `argox.run.cost` dropped at ingest).

## 2026-06-10 — OTel sidecar exports dropped: Collector rejects gzip bodies  [DEPLOY-01]
- **Symptom:** OTel collector sidecar logs `Exporting failed. Dropping data. ... request to http://collector:8000/v1/traces responded with HTTP Status Code 400` while its own debug exporter shows the spans arriving fine; nothing reaches the Argox Collector.
- **Root cause:** The `otlphttp` exporter compresses request bodies with gzip by default. The Collector's ingest endpoint parses the raw body as protobuf/JSON and does not decompress `Content-Encoding: gzip`, so the payload is malformed from its point of view → 400.
- **Fix:** `compression: none` on the `otlphttp` exporter in `deploy/docker/otel/otel-collector-config.yaml`.
- **Guard:** Comment next to the exporter config. Real fix would be gzip support on the ingest endpoint (many OTLP SDK exporters default to gzip) — open follow-up against COL-03.

## 2026-06-10 — Azurite rejects azure-storage-blob requests: API version not supported  [DEPLOY-01]
- **Symptom:** Collector `/readyz` degraded with `The API version 2026-06-06 is not supported by Azurite. Please upgrade Azurite to latest version and retry. ... ErrorCode:InvalidHeaderValue`.
- **Root cause:** The `azure-storage-blob` version installed in the Collector image requests a service API version newer than the latest Azurite release understands. Azurite validates the `x-ms-version` header strictly by default.
- **Fix:** Run Azurite with `--skipApiVersionCheck` (compose `command`). Documented workaround in the Azurite error message itself.
- **Guard:** Flag is part of `deploy/docker/compose.yaml` with an explanatory comment; will recur for any new Azurite consumer that omits it.

## 2026-06-10 — OTLP/JSON trace IDs: hex (spec) vs base64 (protobuf JSON mapping)  [DEPLOY-01]
- **Symptom:** Posting `deploy/docker/seed/trace.json` to the OTel collector sidecar fails with `readSpan.traceId: parse trace_id:invalid length for ID ... "traceId": "AQIDBAUGBwgJCgsMDQ4PEA=="` — yet the same file is accepted by the Argox Collector.
- **Root cause:** The OTLP/JSON spec deviates from proto3 JSON: `traceId`/`spanId` must be **hex**. The Argox Collector ingests JSON via `google.protobuf.json_format`, which implements plain proto3 JSON (**base64** bytes). The two JSON dialects are mutually incompatible for byte fields.
- **Fix:** Send protobuf (SDK default wire format) when going through the sidecar; the seed file targets the Collector directly. Noted in `deploy/docker/README.md`.
- **Guard:** README note. Follow-up: accept hex IDs in the Collector's JSON ingest (COL-03 parser) for OTLP-spec compliance.

## 2026-06-10 — Metrics window skewed by session time zone in DuckDB  [COL-06]
- **Symptom:** Trailing-window metrics (`/api/v1/metrics/*`) silently included or excluded the wrong spans depending on the host's time zone: a 24h window evaluated on a UTC+2 machine shifted its cutoff by two hours. Found in PR #117's queries (`WHERE start_time >= CURRENT_TIMESTAMP - INTERVAL ...`) while reimplementing for PR #127.
- **Root cause:** Span timestamps are stored as **naive UTC** (`_to_naive_utc` strips tzinfo before insert), but DuckDB's `CURRENT_TIMESTAMP` is a `TIMESTAMPTZ` evaluated in the session time zone. Comparing the two casts implicitly and offsets the window by the local UTC offset.
- **Fix:** Compute the cutoff in Python (`_window_cutoff`): `datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=window_hours)` and bind it as a plain `TIMESTAMP` parameter, so both sides of the comparison are naive UTC.
- **Guard:** `test_index_metrics_cost_respects_window` inserts a span 3 days old and asserts it is excluded at `window_hours=24` but included at `720`. General rule: never mix SQL `now()`/`CURRENT_TIMESTAMP` with the naive-UTC columns of this index.

## 2026-06-09 — PostCSS error when using `tailwindcss` as a legacy plugin  [DASH-01]
- **Symptom:** `Internal server error: [postcss] It looks like you're trying to use tailwindcss directly as a PostCSS plugin...` during `npm run dev`.
- **Root cause:** Tailwind CSS v4 is installed, but the CSS was using legacy `@tailwind base;` etc. directives and the PostCSS config was referencing `@tailwindcss/postcss` while the CSS entry point hadn't been migrated to the v4 `@import "tailwindcss";` pattern.
- **Fix:** Replaced `@tailwind` directives with `@import "tailwindcss";` in `argox-dashboard/src/index.css`.
- **Guard:** Verified that `npx vite build` (which triggers PostCSS) completes successfully and generates valid CSS.

## 2026-06-09 — Durable ingest acknowledged batches it had actually lost  [COL-03]
- **Symptom:** A `POST /v1/traces` with `X-Argox-Durable: true` returned 200 even when the blob write or DuckDB insert failed (disk full, Azure 5xx). The client believed the batch was committed; it was gone. The docstring/ADR promised "200 only once committed".
- **Root cause:** `_persist` wrapped its whole body in `except Exception: logger.exception(...)` and never re-raised. That is correct for the background (fire-and-forget) path — the client was already acknowledged — but the durable path reused the same swallowing function and then returned 200 unconditionally, so a failure could not reach the response.
- **Fix:** Split the two paths. `_persist` now raises; the background task wraps it in `_persist_safe` (log-and-swallow), while the durable path catches the exception and returns **503**. ADR-0002 updated to state durable failures surface as 5xx.
- **Guard:** `test_durable_persist_failure_returns_503` patches `storage.put` to raise and asserts the durable request gets 503 with no row indexed.

## 2026-06-09 — One malformed span dropped an entire ingest batch  [COL-03]
- **Symptom:** A batch insert (`executemany`) of span records failed wholesale when a single span carried an unexpected type — e.g. `run.success` arriving as the string `"true"` against the DuckDB BOOLEAN column — so every good span in the batch was lost and only a log line remained.
- **Root cause:** `executemany` is one statement; a type mismatch on any row aborts the whole call. The raw attribute value was passed straight into the BOOLEAN column with no coercion.
- **Fix:** `_as_bool` coerces `run.success` (string/number → bool, unparseable → None) in `_span_to_record`, and `insert_spans` falls back to per-row inserts when the batch fails, skipping only the offending rows. The existing upsert keeps the per-row retry idempotent.
- **Guard:** `test_duckdb_index_batch_survives_one_bad_row` interleaves a bad row between two good ones and asserts only the good rows land; `test_run_success_string_attribute_is_coerced` covers the coercion.

## 2026-06-07 — `asyncio.run` per round dominated the overhead measurement  [BENCH-01]
- **Symptom:** Overhead benchmarks reported ~90–105 µs median, but that figure was suspiciously high for the work being timed and barely separated `baseline` from the feature variants. The number was measuring scaffolding, not the SDK.
- **Root cause:** Each benchmark callable was `asyncio.run(coro)`. `asyncio.run` builds a brand-new event loop and tears it down on **every** round — tens of microseconds of fixed cost plus heavy transient allocation. That allocation also fed the GC variance fought separately with `disable_gc`. The loop lifecycle, not Argox, dominated the timed region.
- **Fix:** Add a session-scoped `bench_loop` fixture (`benchmarks/conftest.py`) that creates one event loop for the whole session, and drive every benchmark with `bench_loop.run_until_complete(coro)` so the timed region is the coroutine alone. Medians dropped ~90–105 µs → ~38–49 µs; StdDev tightened. The baseline-vs-feature delta — the metric that actually matters — is now clean.
- **Guard:** All benches take the `bench_loop` fixture; the fixture docstring explains why `asyncio.run` must not be used in a timed region.

## 2026-06-07 — Live bench `RuntimeError: Event loop is closed` on round 2  [BENCH-01]
- **Symptom:** With the shared-loop fix in mind, the live benchmarks would have raised `RuntimeError: Event loop is closed` from round 2 onward: the `AsyncOpenAI` client is built once in the test body, but each round ran under a fresh `asyncio.run` loop.
- **Root cause:** `AsyncOpenAI` lazily creates its underlying `httpx.AsyncClient` (and connection pool) bound to whichever event loop is running on first request. `asyncio.run` closes that loop at the end of round 1; round 2 opens a new loop, but the client's pool is still bound to the closed one.
- **Fix:** Drive the live benchmarks on the same shared `bench_loop` via `benchmark.pedantic(lambda: bench_loop.run_until_complete(_call()), ...)`. One persistent loop for the client's lifetime removes the binding mismatch.
- **Guard:** Comment in `bench_e2e_live.py` documents that the client binds its pool to the first loop, so per-round `asyncio.run` must not be reintroduced.

## 2026-06-05 — Live benchmark 404s against Azure AI Foundry deployment  [BENCH-01]
- **Symptom:** Live E2E request failed; the client posted to `/deployments/gpt-4o-mini/chat/completions` (an `AsyncAzureOpenAI` instance), which the deployment does not serve. The model is an Azure AI Foundry deployment exposed over the OpenAI-compatible surface, not classic Azure OpenAI.
- **Root cause:** `AsyncAzureOpenAI` rewrites every request to the Azure-OpenAI URL shape `{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=...`. Foundry's OpenAI-compatible endpoint expects the plain `{base_url}/chat/completions` shape and no `api-version`, so the rewritten path is wrong.
- **Fix:** Use a plain `openai.AsyncOpenAI(api_key=..., base_url=AZURE_OPENAI_ENDPOINT)` (the endpoint is passed verbatim as `base_url`). For the `openai-agents` path, register it via `set_default_openai_client(...)` and reference the deployment by name as the agent `model`. This mirrors the working demo (`examples/demo_azure_openai.py`). See `benchmarks/bench_e2e_live.py::_openai_client`.
- **Guard:** Module docstring documents the Foundry-vs-AzureOpenAI distinction so the client choice is not "corrected" back to `AsyncAzureOpenAI`.

## 2026-06-05 — `@pytest.mark.benchmark` rejects `rounds`/`iterations` kwargs  [BENCH-01]
- **Symptom:** `ValueError: benchmark mark can't have 'rounds' keyword argument.` raised at test setup for the live benchmarks (only surfaced once `ARGOX_LIVE_BENCH=1` let them past the skip).
- **Root cause:** The `@pytest.mark.benchmark(...)` marker only accepts a fixed kwarg set (`max_time, min_rounds, min_time, timer, group, disable_gc, warmup, warmup_iterations, calibration_precision, cprofile`). `rounds`, `warmup_rounds`, and `iterations` are not marker kwargs — they belong to `benchmark.pedantic()`.
- **Fix:** Drop those kwargs from the marker (keep only `group`) and call `benchmark.pedantic(fn, rounds=5, warmup_rounds=1, iterations=1)` instead. `pedantic` also pins the call count deterministically, which is what bounds live-API cost. See `benchmarks/bench_e2e_live.py`.
- **Guard:** Live benchmarks use `pedantic`; comment explains the kwargs cannot live on the marker.

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
