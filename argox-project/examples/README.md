# Argox Examples

End-to-end demos that exercise the Argox SDK against a real LLM backend.
They are meant for teammates who want to see the SDK working with as little
ceremony as possible: clone the repo, install the local packages, drop in a
`.env`, run the script.

The demos live in this directory and are runnable as standalone Python
scripts from `argox-project/`.

| Script | What it shows |
|--------|---------------|
| [`demo_azure_openai.py`](demo_azure_openai.py) | Policy-based tool blocking, in-flight argument and output redaction (`ArgoxProcessor`), and metrics export (custom exporter + OTel `ConsoleMetricExporter`). Uses the public `@argox.monitor` decorator with the OpenAI Agents SDK plugin against an Azure OpenAI deployment. |

---

## 1. Prerequisites

- **Python 3.9+**
- **pip 22+** (older versions do not handle local editable installs well)
- An **Azure OpenAI** resource with a chat deployment (e.g. `gpt-4o-mini`) and
  its API key, endpoint and deployment name. The demos drive a real LLM, so
  charges from your Azure account apply.

> The current demo targets Azure OpenAI specifically. Pointing it at vanilla
> OpenAI would only require swapping the `AsyncOpenAI` client construction in
> `demo_azure_openai.py` — the SDK side is identical.

---

## 2. Create a virtual environment

From the repository root:

```bash
cd argox-project
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows PowerShell
```

---

## 3. Install the Argox packages (editable)

The repo is a multi-package workspace. The demo needs `argox-core` (the SDK
itself) and `argox-plugin-openai` (the bridge to the OpenAI Agents SDK).
Install both in editable mode so local changes are picked up without
reinstalling:

```bash
pip install -e ./argox-core
pip install -e ./argox-plugins/argox-plugin-openai
```

`argox-plugin-openai` declares `argox-core` and `openai-agents` as
dependencies, so installing it pulls in the OpenAI Agents SDK and the
`openai` client transitively.

### Optional extras

- **OTLP span export** — to push spans to an OpenTelemetry collector
  (Argox Collector, Jaeger, etc.) install the OTLP extra of `argox-core`:

  ```bash
  pip install -e "./argox-core[otlp]"
  ```

- **Azure Blob audit exporter** — install the Azure exporter package:

  ```bash
  pip install -e ./argox-exporters/argox-exporter-azure
  ```

---

## 4. Install the example-only dependencies

A small `requirements.txt` next to this README pins the extra libraries the
demo scripts use directly that the SDK itself does not depend on (currently
just `python-dotenv` for `.env` loading):

```bash
pip install -r examples/requirements.txt
```

---

## 5. Configure the `.env`

Copy the template and fill in the values from the Azure portal:

```bash
cp examples/.env.example examples/.env
```

The demo loads `.env` from the working directory it is invoked from. The
recommended layout is to keep the file at **`argox-project/.env`** and run
the script from `argox-project/`:

```bash
cp examples/.env.example .env
$EDITOR .env
```

Required keys:

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_API_KEY` | Resource key from the Azure portal. |
| `AZURE_OPENAI_ENDPOINT` | Full endpoint URL, e.g. `https://my-resource.openai.azure.com/`. |
| `AZURE_OPENAI_DEPLOYMENT` | Name of the chat deployment you created in the resource. |

> Do not commit the populated `.env`. Only `.env.example` belongs in the repo.

---

## 6. Run the demo

From `argox-project/` with the virtual environment active:

```bash
python examples/demo_azure_openai.py
```

Expected output, in order:

1. A `ConsoleSpanExporter` JSON line per agent run span.
2. `[processor] redacted email …` lines as the `PiiRedactingProcessor`
   scrubs the email address from `log_user_activity`'s arguments
   before the tool body runs.
3. `[tool:log_user_activity] received: email='[REDACTED]' …` proving the
   tool only ever saw the redacted value.
4. `[tool:get_weather] received: …` for the weather call.
5. A `[metrics] …` block printed by the custom `_PrintMetricsExporter`
   (tokens, duration, tools called, tools blocked).
6. The agent's final natural-language answer.
7. One `ConsoleMetricExporter` JSON dump flushed at process exit.

The policy in the demo blocks `get_current_datetime`, so it should appear
under `tools_blocked` and never under `tools_called`.

---

## 7. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `KeyError: 'AZURE_OPENAI_API_KEY'` | `.env` not found in the working directory you ran from, or the variable name is misspelled. Run the script from `argox-project/`. |
| `ModuleNotFoundError: argox` / `argox_openai` | The editable installs in step 3 were skipped or installed into a different virtualenv. Re-activate the venv and re-run them. |
| `401` / `403` from Azure | Wrong key, endpoint, or the deployment name does not exist in that resource. |
| The model name is rejected by the Agents SDK | `AZURE_OPENAI_DEPLOYMENT` must match the deployment name in Azure, not the underlying model id. |
| No metric dump at the end | The `ConsoleMetricExporter` is flushed via `MeterProvider.force_flush()` in the `finally` block. If the process is killed with `SIGKILL` the periodic reader will not flush. |

---

## 8. Adding a new demo

When contributing a new example:

1. Place the script in this directory and give it a self-describing name
   (`demo_<provider>_<feature>.py`).
2. Keep its dependencies in the example-only `requirements.txt`. Any
   dependency that is part of the public SDK contract belongs in the
   relevant package's `pyproject.toml`, not here.
3. Add a row to the table at the top of this README describing what the
   demo demonstrates.
4. Document any new environment variables in `.env.example`.
