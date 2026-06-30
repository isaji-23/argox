#!/usr/bin/env bash
#
# End-to-end terminal demo: drive the Argox SDK against a live Azure OpenAI
# deployment, ship the resulting spans to a locally-running Argox Collector
# over OTLP/HTTP, then query the Collector back to prove the data landed,
# was enriched (cost) and indexed.
#
# Flow:
#   1. mint an API key (ingest + read) straight into the index DB
#   2. boot the Collector (FastAPI/uvicorn) with auth on
#   3. run demo_azure_openai.py with OTLP export pointed at the Collector
#   4. curl the query + metrics endpoints with the read key
#
# Prereqs (see examples/README.md):
#   - argox-core[otlp], argox-plugin-openai and the collector installed in the
#     active venv:  pip install -e "./argox-core[otlp]" \
#                              -e ./argox-plugins/argox-plugin-openai \
#                              -e ./argox-collector
#   - examples/.env populated with AZURE_OPENAI_* (real deployment; this calls
#     a live LLM and incurs charges).
#
# Run from argox-project/:
#   bash examples/demo_e2e.sh
#
set -euo pipefail

PORT="${COLLECTOR_PORT:-8000}"
BASE="http://localhost:${PORT}"
ENDPOINT="${BASE}/v1/traces"
# Isolate the demo's state so repeated runs start clean and nothing here
# touches a real deployment's index/blobs.
DEMO_DIR="$(mktemp -d -t argox-e2e-XXXXXX)"
export ARGOX_INDEX_DUCKDB_PATH="${DEMO_DIR}/index.duckdb"
export ARGOX_STORAGE_BACKEND="local"
export ARGOX_STORAGE_LOCAL_ROOT="${DEMO_DIR}/blobs"
export ARGOX_AUTH_ENABLED="true"
# serve has no --host/--port flags; it reads these from settings (env).
export ARGOX_HOST="127.0.0.1"
export ARGOX_PORT="${PORT}"

COLLECTOR_PID=""
cleanup() {
  [ -n "${COLLECTOR_PID}" ] && kill "${COLLECTOR_PID}" 2>/dev/null || true
  rm -rf "${DEMO_DIR}"
}
trap cleanup EXIT

echo "=== 1. Mint an API key (ingest + read) ==="
# keys create writes directly to ARGOX_INDEX_DUCKDB_PATH, so the very first
# key can be minted offline before the (admin-only) HTTP CRUD is reachable.
CREATE_OUT="$(argox-collector keys create \
  --name demo-e2e --scope ingest --scope read --created-by demo-e2e)"
echo "${CREATE_OUT}"
API_KEY="$(echo "${CREATE_OUT}" | grep -oE 'argox_[A-Za-z0-9_-]+' | head -n1)"
if [ -z "${API_KEY}" ]; then
  echo "error: could not parse minted API key" >&2
  exit 1
fi

echo
echo "=== 2. Boot the Collector on ${BASE} ==="
argox-collector serve >/tmp/argox-collector.log 2>&1 &
COLLECTOR_PID=$!

# Wait for readiness (public probe, no auth required).
for _ in $(seq 1 30); do
  if curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -fsS "${BASE}/healthz" >/dev/null || { echo "Collector failed to start; see /tmp/argox-collector.log" >&2; exit 1; }
echo "Collector healthy."

echo
echo "=== 3. Run the SDK demo, exporting spans to the Collector ==="
ARGOX_COLLECTOR_ENDPOINT="${ENDPOINT}" \
ARGOX_COLLECTOR_API_KEY="${API_KEY}" \
  python examples/demo_azure_openai.py

# The SDK force-flushes on exit, but ingest -> enrich -> index runs in the
# Collector's background threadpool; give it a moment to settle before querying.
sleep 2

AUTH=(-H "Authorization: Bearer ${API_KEY}")
echo
echo "=== 4. Query the Collector back (proof the data landed) ==="
echo "--- GET /api/v1/traces ---"
curl -fsS "${AUTH[@]}" "${BASE}/api/v1/traces?limit=5" | python -m json.tool
echo "--- GET /api/v1/metrics/cost ---"
curl -fsS "${AUTH[@]}" "${BASE}/api/v1/metrics/cost" | python -m json.tool
echo "--- GET /api/v1/metrics/latency ---"
curl -fsS "${AUTH[@]}" "${BASE}/api/v1/metrics/latency" | python -m json.tool
echo "--- GET /api/v1/metrics/success ---"
curl -fsS "${AUTH[@]}" "${BASE}/api/v1/metrics/success" | python -m json.tool

echo
echo "=== Done. SDK -> OTLP -> Collector -> enrich -> index -> query verified. ==="
