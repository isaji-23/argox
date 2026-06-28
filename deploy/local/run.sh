#!/usr/bin/env bash
#
# Multi-agent demo for the Argox stack, in two modes:
#
#   ./run.sh local    (default)  Bring up the whole stack on this machine
#                                (Collector + real Dashboard + Azurite blob
#                                emulator) and run the agents against it. No
#                                Azure account needed — a self-contained demo
#                                / fallback.
#
#   ./run.sh remote              Run ONLY the agents here, against your already
#                                DEPLOYED Dashboard + Collector. Nothing local
#                                is started.
#
# Both modes then start the multi-agent demo backend (server.py) + front. Open
# the printed demo URL: pick an agent, send a prompt, and watch the run land in
# the dashboard (local or deployed).
#
# Usage (from deploy/local/):
#   ./run.sh                # local
#   ./run.sh remote
#
# Requires an LLM backend (set in .env — see .env.example) and the SDK installed
# in the active Python environment:
#   pip install -e "../../argox-project/argox-core[otlp]" \
#               -e ../../argox-project/argox-plugins/argox-plugin-openai
#   pip install -r requirements.txt
#
# local mode also requires Docker. remote mode requires either ARGOX_DASHBOARD_URL
# set in .env, or the `az` CLI logged in (to resolve the dashboard FQDN).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
DOCKER_DIR="$SCRIPT_DIR/../docker"

MODE="${1:-${DEMO_MODE:-local}}"
[[ "$MODE" == "local" || "$MODE" == "remote" ]] || {
  echo "ERROR: unknown mode '$MODE' (use 'local' or 'remote')." >&2; exit 1; }

ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

PY="${PYTHON:-python3}"
DEMO_HOST="${DEMO_HOST:-127.0.0.1}"
DEMO_PORT="${DEMO_PORT:-8090}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

command -v "$PY" >/dev/null || die "python3 not found."

# --- 1. resolve the dashboard base URL (and bring up the stack if local) ----
if [[ "$MODE" == "local" ]]; then
  command -v docker >/dev/null || die "docker not found (needed for local mode)."
  DASHBOARD_PORT="${DASHBOARD_PORT:-8080}"
  BASE="http://localhost:${DASHBOARD_PORT}"
  ADMIN_KEY="${ARGOX_BOOTSTRAP_ADMIN_KEY:-argox-local-admin}"

  log "Starting Docker stack (Collector + Dashboard + Azurite)"
  export ARGOX_BOOTSTRAP_ADMIN_KEY="$ADMIN_KEY"
  export ARGOX_STORAGE_AZURE_CONNECTION_STRING="${ARGOX_STORAGE_AZURE_CONNECTION_STRING:-DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;}"
  export DASHBOARD_PORT
  docker compose -f "$DOCKER_DIR/compose.yaml" --profile local up -d --build

  log "Waiting for the dashboard at $BASE"
  for _ in $(seq 1 60); do
    curl -fsS "$BASE/" >/dev/null 2>&1 && break
    sleep 2
  done
  curl -fsS "$BASE/" >/dev/null 2>&1 || die "dashboard not reachable at $BASE"
  echo "  up: $BASE"
else
  # remote: resolve from ARGOX_DASHBOARD_URL, else from Azure Container Apps.
  ADMIN_KEY="${ARGOX_BOOTSTRAP_ADMIN_KEY:-}"
  BASE="${ARGOX_DASHBOARD_URL:-}"
  if [[ -z "$BASE" ]]; then
    command -v az >/dev/null || die "remote mode: set ARGOX_DASHBOARD_URL in .env, or install the az CLI."
    az account show >/dev/null 2>&1 || die "remote mode: not logged in. Run 'az login' (or set ARGOX_DASHBOARD_URL)."
    RG="${RG:-TFM-Aliando}"
    log "Resolving deployed Dashboard URL (resource group: $RG)"
    FQDN="$(az containerapp show -n dashboard -g "$RG" \
      --query properties.configuration.ingress.fqdn -o tsv)"
    [[ -n "$FQDN" ]] || die "could not resolve dashboard FQDN. Is it deployed in '$RG'?"
    BASE="https://$FQDN"
  fi
  curl -fsS "$BASE/" >/dev/null 2>&1 || die "deployed dashboard not reachable at $BASE"
  echo "  using: $BASE"
fi

# --- 2. demo API key --------------------------------------------------------
# Reuse ARGOX_COLLECTOR_API_KEY if provided; otherwise mint one with the admin
# key. policy-write is only needed when this script seeds the demo policy.
API_KEY="${ARGOX_COLLECTOR_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  [[ -n "$ADMIN_KEY" ]] || die "no ARGOX_COLLECTOR_API_KEY and no ARGOX_BOOTSTRAP_ADMIN_KEY to mint one."
  log "Minting demo API key (read, ingest, policy-read, policy-write)"
  API_KEY="$(curl -fsS -X POST "$BASE/api/v1/keys" \
    -H "Authorization: Bearer $ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"name":"agent-demo","scopes":["read","ingest","policy-read","policy-write"]}' \
    | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["key"])')"
  [[ -n "$API_KEY" ]] || die "key mint failed (is the admin key correct?)."
  echo "  minted (raw key shown once, not stored)"
fi

# --- 3. seed the demo policy ------------------------------------------------
# local: seed by default. remote: only when SEED_POLICY=true, to avoid mutating
# a deployed fleet's policies unless explicitly asked.
SEED_POLICY="${SEED_POLICY:-$([[ "$MODE" == "local" ]] && echo true || echo false)}"
if [[ "$SEED_POLICY" == "true" ]]; then
  log "Seeding demo policy"
  "$PY" "$SCRIPT_DIR/seed_policy.py" "$BASE" "$API_KEY"
else
  log "Skipping policy seed (remote mode; set SEED_POLICY=true to seed)"
fi

# --- 4. start the demo backend + front --------------------------------------
log "Starting the multi-agent demo backend ($MODE mode)"
export ARGOX_DASHBOARD_URL="$BASE"
export ARGOX_COLLECTOR_API_KEY="$API_KEY"
export DEMO_HOST DEMO_PORT
echo
echo "  Mode:        $MODE"
echo "  Demo front:  http://${DEMO_HOST}:${DEMO_PORT}"
echo "  Dashboard:   $BASE"
if [[ "$MODE" == "local" ]]; then
  echo
  echo "  Stop the local stack later with:"
  echo "    docker compose -f $DOCKER_DIR/compose.yaml --profile local down"
fi
echo
exec "$PY" "$SCRIPT_DIR/server.py"
