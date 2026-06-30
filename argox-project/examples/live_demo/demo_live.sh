#!/usr/bin/env bash
#
# Live dashboard demo: boot the Argox Collector, serve a tiny static front that
# polls the Query API, and stream synthetic traces into it so you can watch the
# SDK -> Collector -> dashboard flow in real time.
#
# Flow:
#   1. boot the Collector (FastAPI/uvicorn) with auth OFF and CORS open to the
#      front's origin, so the browser can poll the API keyless.
#   2. serve examples/live_demo/index.html on http://localhost:8001.
#   3. run trace_generator.py (synthetic, no Azure) — or, with --azure, the
#      real Azure OpenAI demo (examples/demo_azure_openai.py), or, with
#      --azure-bridge, the azure_bridge.py HTTP server that fires one real
#      Azure run per click of the dashboard's "Ask Azure" button.
#
# Prereqs (see examples/live_demo/README.md):
#   pip install -e "./argox-core[otlp]" -e ./argox-collector
#   # --azure additionally needs argox-plugin-openai and examples/.env populated.
#
# Run from argox-project/:
#   bash examples/live_demo/demo_live.sh                # synthetic, loopback only
#   bash examples/live_demo/demo_live.sh --azure        # real Azure OpenAI run
#   bash examples/live_demo/demo_live.sh --azure-bridge # fire runs from the button
#   bash examples/live_demo/demo_live.sh --bind-all     # expose to the Tailscale net
#
# --bind-all binds the Collector and the front to 0.0.0.0 and advertises the
# host as ${TS_HOST} (default 100.96.191.95, mirlo's Tailscale IP) so a browser
# elsewhere on the tailnet can reach them. The Collector runs with auth OFF, so
# this exposes a keyless API to the whole tailnet — fine for a private demo, not
# for anything public.
#
set -euo pipefail

MODE="synthetic"
BIND_ALL=0
for arg in "$@"; do
  case "${arg}" in
    --azure) MODE="azure" ;;
    --azure-bridge) MODE="azure-bridge" ;;
    --bind-all) BIND_ALL=1 ;;
    *) echo "unknown argument: ${arg}" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

COLLECTOR_PORT="${COLLECTOR_PORT:-8000}"
FRONT_PORT="${FRONT_PORT:-8001}"
BRIDGE_PORT="${BRIDGE_PORT:-8002}"
# Tailscale address the browser will use; override with TS_HOST=...
# Defaults to mirlo's Tailscale IP (more robust than MagicDNS, which may not
# resolve on every client).
TS_HOST="${TS_HOST:-100.96.191.95}"

# BASE is what THIS host curls to probe readiness; always loopback.
BASE="http://localhost:${COLLECTOR_PORT}"

if [ "${BIND_ALL}" -eq 1 ]; then
  BIND_HOST="0.0.0.0"
  PUBLIC_HOST="${TS_HOST}"
else
  BIND_HOST="127.0.0.1"
  PUBLIC_HOST="localhost"
fi

# URLs the browser uses (the page polls the Collector via the ?api= param).
FRONT_URL="http://${PUBLIC_HOST}:${FRONT_PORT}"
PUBLIC_API="http://${PUBLIC_HOST}:${COLLECTOR_PORT}"
PUBLIC_BRIDGE="http://${PUBLIC_HOST}:${BRIDGE_PORT}"
OPEN_URL="${FRONT_URL}/?api=${PUBLIC_API}"
if [ "${MODE}" = "azure-bridge" ]; then
  OPEN_URL="${OPEN_URL}&azure=${PUBLIC_BRIDGE}"
fi

# Isolated, throwaway state so repeated runs start clean.
DEMO_DIR="$(mktemp -d -t argox-live-XXXXXX)"
export ARGOX_INDEX_DUCKDB_PATH="${DEMO_DIR}/index.duckdb"
export ARGOX_STORAGE_BACKEND="local"
export ARGOX_STORAGE_LOCAL_ROOT="${DEMO_DIR}/blobs"
# Auth off => the browser can call the Query API without a Bearer token.
export ARGOX_AUTH_ENABLED="false"
# CORS must list the front's exact origin or the browser blocks the fetch.
export ARGOX_CORS_ORIGINS="${FRONT_URL}"
export ARGOX_HOST="${BIND_HOST}"
export ARGOX_PORT="${COLLECTOR_PORT}"

COLLECTOR_PID=""
FRONT_PID=""
BRIDGE_PID=""
cleanup() {
  [ -n "${BRIDGE_PID}" ] && kill "${BRIDGE_PID}" 2>/dev/null || true
  [ -n "${FRONT_PID}" ] && kill "${FRONT_PID}" 2>/dev/null || true
  [ -n "${COLLECTOR_PID}" ] && kill "${COLLECTOR_PID}" 2>/dev/null || true
  rm -rf "${DEMO_DIR}"
}
trap cleanup EXIT

# Fail fast on a port clash: if something already answers on the collector
# port, our `serve` would bind-fail while the health probe still passes against
# the stale process, silently pointing the front at the wrong Collector.
if curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then
  echo "error: something is already listening on ${BASE}." >&2
  echo "       Stop it, or rerun with a free port: COLLECTOR_PORT=8123 bash $0" >&2
  exit 1
fi

echo "=== 1. Boot the Collector on ${BASE} (auth off, CORS -> ${FRONT_URL}) ==="
argox-collector serve >/tmp/argox-live-collector.log 2>&1 &
COLLECTOR_PID=$!

for _ in $(seq 1 30); do
  if curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -fsS "${BASE}/healthz" >/dev/null || {
  echo "Collector failed to start; see /tmp/argox-live-collector.log" >&2
  exit 1
}
echo "Collector healthy."

echo
echo "=== 2. Serve the front on ${FRONT_URL} ==="
python -m http.server "${FRONT_PORT}" --bind "${BIND_HOST}" --directory "${HERE}" \
  >/tmp/argox-live-front.log 2>&1 &
FRONT_PID=$!
sleep 1
echo "Front served. Open ${OPEN_URL} in your browser."

echo
if [ "${MODE}" = "azure-bridge" ]; then
  echo "=== 3. Run the Azure bridge — fire runs from the dashboard button (Ctrl-C to stop) ==="
  echo ">>> Open ${OPEN_URL} and press 'Ask Azure' to trigger a real run. <<<"
  echo
  python "${HERE}/azure_bridge.py" \
    --collector "${BASE}" --port "${BRIDGE_PORT}" --bind "${BIND_HOST}"
elif [ "${MODE}" = "azure" ]; then
  echo "=== 3. Run the real Azure OpenAI demo (Ctrl-C to stop) ==="
  ARGOX_COLLECTOR_ENDPOINT="${BASE}/v1/traces" \
    python "${HERE}/../demo_azure_openai.py"
else
  echo "=== 3. Stream synthetic traces (Ctrl-C to stop) ==="
  echo ">>> Open ${OPEN_URL} now to watch traces arrive live. <<<"
  echo
  python "${HERE}/trace_generator.py" --endpoint "${BASE}"
fi
