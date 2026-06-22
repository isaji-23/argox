# Live trace demo

Watch traces flow from the Argox SDK to the Collector and into a tiny dashboard
**in real time**. A generator drives the SDK in a loop; a static HTML page polls
the Collector's Query API every second and flashes each new trace as it lands.

```
trace_generator.py  --(OTLP /v1/traces + /v1/runs)-->  Collector  <--(poll /api/v1/*)--  index.html
```

## Prerequisites

From `argox-project/` with your virtualenv active:

```bash
pip install -e "./argox-core[otlp]" -e ./argox-collector
```

The `--azure` mode additionally needs the OpenAI plugin and credentials:

```bash
pip install -e "./argox-plugins/argox-plugin-openai"
# populate examples/.env with AZURE_OPENAI_* (this calls a live LLM and bills).
```

## Run it

From `argox-project/`:

```bash
bash examples/live_demo/demo_live.sh
```

Then open <http://localhost:8001> in your browser. You'll see the trace count,
cost, latency and success-rate cards update, and new traces appear (with a brief
highlight) every 1–2 seconds. Click a trace row to inspect its span waterfall.

Press `Ctrl-C` to stop; the script kills the Collector and the static server and
deletes its temporary index/blob state.

### Watch from another machine (Tailscale / LAN)

By default everything binds to loopback, so the dashboard is only reachable from
the host running it. To watch it from a browser on another machine in your
Tailscale network, bind to all interfaces and advertise the host's name:

```bash
# bind to 0.0.0.0 and advertise mirlo's Tailscale IP (100.96.191.95)
bash examples/live_demo/demo_live.sh --bind-all
```

Then open the printed URL on the remote machine:

```
http://100.96.191.95:8001/?api=http://100.96.191.95:8000
```

The host you type in the browser must match `TS_HOST` exactly, or CORS blocks
the API calls. Override the advertised address/ports if needed:

```bash
TS_HOST=myhost COLLECTOR_PORT=9000 FRONT_PORT=9001 \
  bash examples/live_demo/demo_live.sh --bind-all
```

> ⚠️ The Collector runs with **auth disabled**, so `--bind-all` exposes a
> keyless API to your whole tailnet. Fine for a private demo; do not use it on a
> public or untrusted network. Without `--bind-all`, use an SSH tunnel instead:
> `ssh -L 8001:localhost:8001 -L 8000:localhost:8000 user@mirlo`.

### Real Azure OpenAI run

```bash
bash examples/live_demo/demo_live.sh --azure
```

This swaps the synthetic generator for `examples/demo_azure_openai.py`, sending
real LLM spans to the same Collector and dashboard.

### Fire Azure runs from the dashboard button

The `--azure` mode above runs the baseline-vs-monitored comparison script once
and exits. To instead trigger a **single real Azure run on demand** from the
dashboard, use the bridge:

```bash
bash examples/live_demo/demo_live.sh --azure-bridge
```

This boots the Collector and the front (no synthetic generator) and starts
`azure_bridge.py`, a tiny HTTP server on `http://localhost:8002`. Open the
printed URL, type a prompt in the **Ask Azure** box, and press the button — the
bridge runs the monitored agent once and ships its span to the Collector, so the
new trace flashes into the list and the cost / success cards update.

Cost and success follow the real SDK path, not faked numbers:

- **Cost** is computed by the **Collector**, not the bridge. The span carries
  the model (`gen_ai.request.model`) and the SDK records token usage, so the
  Collector's cost enricher (COL-07) prices the run at ingest. The model **must
  match a key in the Collector's `pricing.yaml`** (e.g. `gpt-4o`). Azure
  deployment names often differ from the model id — set `AZURE_OPENAI_MODEL` to
  the priced model id when they do, otherwise the cost card stays empty and the
  Collector logs `cost_unknown_model`.
- **Success** comes from the `argox.run.success` span attribute the bridge sets
  once the run returns. The bridge also posts the run summary to `POST /v1/runs`
  so the trace detail's per-span outcome (ok / blocked) is populated.

Run the bridge standalone (Collector already up) if you prefer:

```bash
python examples/live_demo/azure_bridge.py --collector http://localhost:8000
```

The dashboard targets the bridge via the `?azure=` URL param (default
`http://localhost:8002`); `--azure-bridge` appends it for you. The bridge needs
the same `AZURE_OPENAI_*` credentials in `examples/.env` and the OpenAI plugin
installed.

#### Tools and the policy block

The bridge agent exposes three tools:

| Tool | Policy | Result in the waterfall |
|---|---|---|
| `get_weather` | allowed | normal span `tool.get_weather` |
| `log_user_activity` | allowed | normal span; the PII e-mail is scrubbed by the redaction processor |
| `get_current_datetime` | **blocked** by rule `DEMO-TOOL-01` in `examples/policies/demo_policy.yaml` | red span `tool.get_current_datetime` tagged `policy_decision=block` |

When a tool is blocked, the SDK strips it before the run (so the model never
calls it) and records the decision; the bridge then emits a short child span for
it carrying `argox.policy.decision=block` and `argox.policy.rule_id`, which the
Collector promotes into the queryable `policy_decision` column. The dashboard
paints any span with `policy_decision=block` red, so the block is visible right
in the trace's waterfall — expand the row to see the rule id.

**Example prompt that exercises all three tools in one run** (it is also the
default if you leave the box empty):

```
Log that user@example.com just checked the forecast, tell me the weather in Madrid, and what is the current date and time?
```

That single run produces a waterfall with `tool.get_weather` and
`tool.log_user_activity` as normal spans and `tool.get_current_datetime` as a
red, policy-blocked span.

## How it works

- The Collector runs with **auth disabled** (`ARGOX_AUTH_ENABLED=false`) and
  **CORS open** to the front's origin (`ARGOX_CORS_ORIGINS=http://localhost:8001`)
  so the browser can poll the Query API directly without a Bearer token.
- `trace_generator.py` runs `ArgoxManager` with a fake plugin/runner (no real
  provider), force-flushing the OTLP span exporter after every run so traces
  show up immediately. It also posts a run summary to `POST /v1/runs` so the
  success-rate and per-span outcome are populated, and joins them to the trace
  via `trace_id`.
- A fraction of runs (default 20%, `--block-rate`) are blocked by a demo policy
  so the success rate stays visibly below 100%.

### Useful flags

```bash
# faster stream, stop after 50 runs, never block:
python examples/live_demo/trace_generator.py --interval 0.5 --count 50 --block-rate 0
```

## Manual check (no browser)

```bash
curl -s http://localhost:8000/api/v1/traces?limit=5
curl -s http://localhost:8000/api/v1/metrics/success
```
