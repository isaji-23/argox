#!/usr/bin/env bash
#
# End-to-end demo against the DEPLOYED Argox stack:
#   1. resolve the public Dashboard URL (the Collector's only public surface),
#   2. mint a demo API key (ingest + read) with the break-glass ADMIN_KEY,
#   3. run a tiny @argox.monitor-instrumented agent (demo_agent.py) that ships
#      its run span to the Collector over OTLP,
#   4. poll until the trace is indexed, then print the Collector's metrics.
#
# Usage (from deploy/azure/):
#   ./demo.sh
#
# Requires an LLM backend for the agent — set ONE in .env or the environment:
#   OPENAI_API_KEY [OPENAI_MODEL]   |   AZURE_OPENAI_API_KEY + ENDPOINT + DEPLOYMENT
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

RG="${RG:-TFM-Aliando}"
ADMIN_KEY="${ADMIN_KEY:-}"
PY="${PYTHON:-python3}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

command -v az >/dev/null || die "az CLI not found."
az account show >/dev/null 2>&1 || die "not logged in. Run 'az login'."
[[ -n "$ADMIN_KEY" ]] || die "ADMIN_KEY empty. Deploy first (./deploy.sh writes it to .env)."

# --- 1. public Dashboard URL ----------------------------------------------
log "Resolving Dashboard URL"
FQDN="$(az containerapp show -n dashboard -g "$RG" \
  --query properties.configuration.ingress.fqdn -o tsv)"
[[ -n "$FQDN" ]] || die "could not resolve dashboard FQDN. Is it deployed?"
BASE="https://$FQDN"
echo "  $BASE"

# --- 2. demo API key (ingest + read) --------------------------------------
# Reuse ARGOX_COLLECTOR_API_KEY if already provided; otherwise mint one.
API_KEY="${ARGOX_COLLECTOR_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  log "Minting demo API key (scopes: read, ingest)"
  API_KEY="$(curl -fsS -X POST "$BASE/api/v1/keys" \
    -H "Authorization: Bearer $ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"name":"demo","scopes":["read","ingest"]}' \
    | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["key"])')"
  [[ -n "$API_KEY" ]] || die "key mint failed (check ADMIN_KEY)."
  echo "  minted (raw key shown once, not stored)"
fi

# --- 3. run the monitored agent -------------------------------------------
log "Running monitored agent (demo_agent.py)"
export ARGOX_COLLECTOR_ENDPOINT="$BASE/v1/traces"
export ARGOX_COLLECTOR_API_KEY="$API_KEY"
"$PY" "$SCRIPT_DIR/demo_agent.py"

# --- 4. read the metrics back from the Collector ---------------------------
auth=(-H "Authorization: Bearer $API_KEY")

log "Waiting for the trace to be indexed"
total=0
for _ in $(seq 1 20); do
  total="$(curl -fsS "${auth[@]}" "$BASE/api/v1/traces?limit=1" \
    | "$PY" -c 'import sys,json; print(json.load(sys.stdin).get("total",0))' 2>/dev/null || echo 0)"
  [[ "$total" -gt 0 ]] && break
  sleep 2
done
[[ "$total" -gt 0 ]] || echo "  (no trace indexed yet; metrics below may be empty)"

show() {  # pretty-print a JSON endpoint
  local label="$1" path="$2"
  echo
  echo "--- $label  ($path) ---"
  curl -fsS "${auth[@]}" "$BASE$path" | "$PY" -m json.tool 2>/dev/null \
    || echo "  request failed"
}

log "Collector metrics (trailing 24h)"
show "Latest traces" "/api/v1/traces?limit=5"
show "Cost"          "/api/v1/metrics/cost"
show "Latency"       "/api/v1/metrics/latency"
show "Success rate"  "/api/v1/metrics/success"

echo
echo "Open the Dashboard to see the trace waterfall: $BASE"
