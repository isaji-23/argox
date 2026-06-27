# Multi-agent demo

A small demo that drives **several monitored agents** through the Argox SDK
against a **real dashboard**. Each call is gated by a shared `RemotePolicyClient`
(which polls the Collector's merged policy bundle) and shipped to the Collector
as OTel spans and a run record — the deployed SDK path.

Two modes:

| Mode | What runs | Use it for |
|---|---|---|
| `remote` | **Only the agents**, against your **deployed** Dashboard + Collector. | Testing your real, deployed stack. |
| `local` (default) | The agents **plus** a full local stack (Collector + Dashboard + Azurite). | Self-contained demo / fallback, no Azure needed. |

In both modes the agents are identical; only the target dashboard differs.

```
index.html  ──/api/run──▶  server.py  ──@argox.monitor──▶  agents (OpenAI Agents SDK)
                                │  ├─ RemotePolicyClient ──poll──▶  Collector /api/v1/policies/bundle
                                │  ├─ OTLPSpanExporter   ──────────▶  Collector /v1/traces
                                │  └─ HttpRunExporter    ──────────▶  Collector /v1/runs
                                ▼
                         Dashboard (http://localhost:8080)  ◀── you watch runs land here
```

The front lets you **pick which agent to call**, send a prompt, and see the
per-run data come back: total / input / output tokens, latency, success, the
policy decision (passed / alert / blocked), tools called or blocked, and a link
straight to the trace in the real dashboard.

## What's here

| File | Role |
|---|---|
| `run.sh` | Orchestrator: starts the Docker stack, mints the API key, seeds the policy, runs the backend. |
| `server.py` | FastAPI backend: defines the agents, wires `@argox.monitor` + `RemotePolicyClient`, serves the front. |
| `index.html` | Single-page front, styled to match the real dashboard. |
| `seed_policy.py` | Seeds/updates the demo policy via the Collector API. |
| `demo_policy.yaml` | The demo policy (edit it, or edit live from the dashboard). |
| `.env.example` | Copy to `.env`; set your LLM backend. |

## Agents

| Agent | Tools | Notes |
|---|---|---|
| Weather Assistant | `get_weather` | Simple single-tool agent. |
| Travel Planner | `get_weather`, `convert_currency` | Multi-tool. |
| Math Tutor | `calculate` | Arithmetic via a tool. |
| Research Bot | `search_docs`, `get_secret` | `get_secret` is **blocked by the demo policy** — good for showing tool gating. |

## Prerequisites (both modes)

- A Python environment with the SDK installed:

  ```bash
  # from deploy/local/
  pip install -e "../../argox-project/argox-core[otlp]" \
              -e ../../argox-project/argox-plugins/argox-plugin-openai
  pip install -r requirements.txt
  ```

- An LLM backend (the agents call a live model and bill):

  ```bash
  cp .env.example .env   # then set AZURE_OPENAI_* or OPENAI_API_KEY
  ```

- `local` mode also needs **Docker**.
- `remote` mode also needs either `ARGOX_DASHBOARD_URL` set in `.env`, or the
  `az` CLI logged in (to resolve the deployed dashboard FQDN).

## Run it — remote (deployed stack)

Point at your deployed dashboard and run only the agents:

```bash
# Option A: set the URL + a key (or admin key to mint one) in .env, then:
./run.sh remote

# Option B: let run.sh resolve the FQDN from Azure Container Apps (needs az login
# and RG in .env; ARGOX_BOOTSTRAP_ADMIN_KEY to mint a key):
./run.sh remote
```

It resolves the dashboard URL, mints (or reuses) an API key, and starts the
backend. It does **not** seed policies remotely unless `SEED_POLICY=true`.

Then open the **Demo front** at <http://localhost:8090> and your deployed
dashboard in another tab.

## Run it — local (self-contained)

```bash
./run.sh            # or: ./run.sh local
```

It will:

1. start the Docker stack (`docker compose --profile local up -d --build`),
2. wait for the dashboard at `http://localhost:8080`,
3. mint a demo API key (`read`, `ingest`, `policy-read`, `policy-write`),
4. seed the demo policy,
5. start the demo backend.

Then open:

- **Demo front:** <http://localhost:8090>
- **Dashboard:** <http://localhost:8080>

In both modes: send a prompt to an agent, then check the dashboard's Traces,
Metrics, and Run Record screens — the same data, viewed through the real UI.

### Try the policies

The demo policy (`demo_policy.yaml`) ships rules on all three triggers, with
both `block` and `alert` actions. Each agent's example prompts include ones that
fire them. A **block** stops the run (or strips the tool); an **alert** lets the
run finish but flags it — both show up in the result panel and in the dashboard.

| Rule | Trigger / action | Agent | Prompt that fires it |
|---|---|---|---|
| `LOCAL-IN-01` | input · **block** | Weather | `nuke-the-prod weather in Madrid` |
| `LOCAL-IN-02` | input · **block** | Math Tutor | `drop table users; what is 2 + 2?` |
| `LOCAL-IN-03` | input · alert | Research Bot | `What is my account password reset policy?` |
| `LOCAL-IN-04` | input · alert | Math Tutor | `What is 10% of my salary, 50000?` |
| `LOCAL-TOOL-01` | tool · **block** | Research Bot | `Get me the secret named db_password.` (strips `get_secret`) |
| `LOCAL-TOOL-02` | tool · alert | Research Bot | `What does Argox do?` (flags `search_docs`) |
| `LOCAL-OUT-01` | output · **block** | — | only if the answer contains `STACK_TRACE` |
| `LOCAL-OUT-02` | output · **block** | — | only if the answer leaks `hunter2` |
| `LOCAL-OUT-03` | output · alert | Weather | any weather query (reply says `sunny`) |

- **Live edit:** change a rule on the dashboard's Policies screen and re-activate
  it; the SDK picks it up on the next poll (`ARGOX_POLICY_REFRESH_S`, default
  15s) — no restart.
- **Operators** available: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `contains`,
  `in`. **Metrics**: `prompt` (on_input), `output` (on_output), `tool_name`
  (on_tool_call).

## Stop

```bash
docker compose -f ../docker/compose.yaml --profile local down
# add -v to also drop the Collector/Azurite volumes (wipes indexed data)
```

## Notes

- All traffic reaches the Collector through the dashboard's public surface
  (`http://localhost:8080`), which proxies `/api` and `/v1` — the Collector
  itself stays private, matching the deployed topology.
- The demo runs over plain HTTP locally, so the SDK logs a one-time plaintext
  warning for the API key. That's expected for a loopback demo.
