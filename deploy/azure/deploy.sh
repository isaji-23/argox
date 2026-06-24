#!/usr/bin/env bash
#
# Deploy the full Argox stack to Azure Container Apps.
#
# Mirrors deploy/azure/azure-deploy-steps.md, but idempotent and driven by .env.
# The resource group is assumed to ALREADY EXIST (TFM-Aliando in Sweden Central)
# and is never created or deleted here.
#
# Usage:
#   cp .env.example .env   # edit ACR / STORAGE to globally-unique names
#   ./deploy.sh
#
set -euo pipefail

# --- locate ourselves and load configuration ------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
else
  echo "WARNING: no .env found; using built-in defaults. Copy .env.example to .env." >&2
fi

# Defaults (overridable via .env or the environment).
RG="${RG:-TFM-Aliando}"
LOC="${LOC:-swedencentral}"
ENV="${ENV:-argox-env}"
ACR="${ACR:-argoxacraliando}"
STORAGE="${STORAGE:-argoxstgaliando}"
TAG="${TAG:-v1}"
ADMIN_KEY="${ADMIN_KEY:-}"

# Repo-relative build contexts. The collector context is the argox-project/
# parent so the image can bundle the sibling argox-core package it imports; its
# Dockerfile is addressed with -f (see build_image / COLLECTOR_DOCKERFILE).
COLLECTOR_CTX="../../argox-project"
COLLECTOR_DOCKERFILE="argox-collector/Dockerfile"
DASHBOARD_CTX="../../argox-dashboard"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# Set KEY=VALUE in an env file, in place, creating it if missing. Uses python so
# the value is written literally (no sed delimiter/metacharacter pitfalls).
persist_env() {
  local key="$1" value="$2" file="$3"
  KEY="$key" VALUE="$value" FILE="$file" python3 - <<'PY'
import os
key, value, path = os.environ["KEY"], os.environ["VALUE"], os.environ["FILE"]
try:
    lines = open(path).read().splitlines()
except FileNotFoundError:
    lines = []
prefix = key + "="
for i, line in enumerate(lines):
    if line.startswith(prefix):
        lines[i] = prefix + value
        break
else:
    lines.append(prefix + value)
open(path, "w").write("\n".join(lines) + "\n")
PY
}

# --- preflight -------------------------------------------------------------
command -v az >/dev/null || { echo "ERROR: az CLI not found." >&2; exit 1; }
az account show >/dev/null 2>&1 || { echo "ERROR: not logged in. Run 'az login'." >&2; exit 1; }
az group show -n "$RG" >/dev/null 2>&1 || { echo "ERROR: resource group '$RG' does not exist." >&2; exit 1; }

log "Ensuring resource providers are registered"
az extension add --name containerapp --upgrade --only-show-errors >/dev/null
# Registration needs subscription-level rights. On restricted accounts the
# providers are usually already registered by the subscription owner, so only
# attempt registration when a provider is not already 'Registered'.
ensure_provider() {
  local ns="$1" state
  state="$(az provider show --namespace "$ns" --query registrationState -o tsv 2>/dev/null || echo Unknown)"
  if [[ "$state" == "Registered" ]]; then
    echo "  $ns: already registered"
  elif az provider register --namespace "$ns" --wait 2>/dev/null; then
    echo "  $ns: registered"
  else
    echo "  WARNING: cannot register $ns (state=$state); no subscription rights." >&2
    echo "           Ask a subscription owner to run: az provider register --namespace $ns" >&2
  fi
}
ensure_provider Microsoft.App
ensure_provider Microsoft.OperationalInsights

# --- admin key: generate once and persist back to .env ---------------------
# The admin key is a break-glass secret: persist it to .env, never echo it to
# stdout (terminal scrollback / CI logs leak it).
if [[ -z "$ADMIN_KEY" ]]; then
  ADMIN_KEY="$(openssl rand -hex 32)"
  if [[ -f "$ENV_FILE" ]]; then
    persist_env ADMIN_KEY "$ADMIN_KEY" "$ENV_FILE"
    echo "Generated ADMIN_KEY and wrote it to $ENV_FILE (not printed here)."
  else
    echo "Generated ADMIN_KEY but no .env to persist into; re-run with a .env." >&2
    echo "Read it once from this shell:  echo \"\$ADMIN_KEY\"" >&2
  fi
fi

# --- container registry + images ------------------------------------------
log "Container registry: $ACR"
if ! az acr show -n "$ACR" -g "$RG" >/dev/null 2>&1; then
  az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled true
fi

log "Building images in ACR (cloud build, no local Docker)"
# Skip a build when the tag already exists, unless FORCE_BUILD=1. ACR builds are
# unconditional otherwise, so a plain re-run rebuilds both images at $TAG.
build_image() {
  local repo="$1" ctx="$2" dockerfile="${3:-}"
  local file_arg=()
  [[ -n "$dockerfile" ]] && file_arg=(-f "$dockerfile")
  if [[ "${FORCE_BUILD:-0}" != "1" ]] && \
     az acr repository show -n "$ACR" --image "$repo:$TAG" >/dev/null 2>&1; then
    echo "  $repo:$TAG already in registry; skipping (FORCE_BUILD=1 to rebuild)"
  else
    az acr build -r "$ACR" -t "$repo:$TAG" "${file_arg[@]}" "$ctx"
  fi
}
build_image argox-collector "$COLLECTOR_CTX" "$COLLECTOR_DOCKERFILE"
build_image argox-dashboard "$DASHBOARD_CTX"

ACR_SERVER="$ACR.azurecr.io"
ACR_USER="$(az acr credential show -n "$ACR" --query username -o tsv)"
ACR_PASS="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"

# --- storage: blob container + Azure Files share ---------------------------
log "Storage account: $STORAGE"
if ! az storage account show -n "$STORAGE" -g "$RG" >/dev/null 2>&1; then
  az storage account create -g "$RG" -n "$STORAGE" -l "$LOC" --sku Standard_LRS --kind StorageV2
fi

STG_KEY="$(az storage account keys list -g "$RG" -n "$STORAGE" --query '[0].value' -o tsv)"
STG_CONN="$(az storage account show-connection-string -g "$RG" -n "$STORAGE" -o tsv)"

log "Blob container 'argox' + file share 'argox-index'"
az storage container create --account-name "$STORAGE" --account-key "$STG_KEY" -n argox --only-show-errors >/dev/null
az storage share-rm create -g "$RG" --storage-account "$STORAGE" -n argox-index --quota 5 --only-show-errors >/dev/null

# --- Container Apps environment + storage registration ---------------------
log "Container Apps environment: $ENV"
if ! az containerapp env show -n "$ENV" -g "$RG" >/dev/null 2>&1; then
  az containerapp env create -g "$RG" -n "$ENV" -l "$LOC"
fi

log "Registering Azure Files share with the environment"
az containerapp env storage set -g "$RG" -n "$ENV" \
  --storage-name argox-index \
  --storage-type AzureFile \
  --azure-file-account-name "$STORAGE" \
  --azure-file-account-key "$STG_KEY" \
  --azure-file-share-name argox-index \
  --access-mode ReadWrite

# --- collector ------------------------------------------------------------
# Two-step (mirrors runbook steps 6 + 7):
#   1. create with plain flags  — the proven path; a hand-built --yaml trips the
#      beta containerapp extension with "could not be converted to Boolean".
#   2. attach the DuckDB volume by patching az's OWN exported YAML, then update.
log "Collector app (internal ingress, single replica)"

# Env vars (secret values referenced via secretref:).
COLLECTOR_ENV=(
  ARGOX_STORAGE_BACKEND=azure
  ARGOX_STORAGE_AZURE_CONNECTION_STRING=secretref:storage-conn
  ARGOX_STORAGE_AZURE_CONTAINER=argox
  ARGOX_INDEX_DUCKDB_PATH=/data/index.duckdb
  ARGOX_AUTH_ENABLED=true
  ARGOX_BOOTSTRAP_ADMIN_KEY=secretref:admin-key
)
if [[ -n "${ARGOX_OIDC_ISSUER:-}" ]]; then
  log "OIDC enabled (Microsoft Entra ID)"
  COLLECTOR_ENV+=(
    "ARGOX_OIDC_ISSUER=${ARGOX_OIDC_ISSUER}"
    "ARGOX_OIDC_AUDIENCE=${ARGOX_OIDC_AUDIENCE:-}"
    "ARGOX_OIDC_JWKS_URI=${ARGOX_OIDC_JWKS_URI:-}"
    "ARGOX_OIDC_ADMIN_ROLE=${ARGOX_OIDC_ADMIN_ROLE:-}"
  )
fi

if ! az containerapp show -n collector -g "$RG" >/dev/null 2>&1; then
  az containerapp create -g "$RG" -n collector \
    --environment "$ENV" \
    --image "$ACR_SERVER/argox-collector:$TAG" \
    --registry-server "$ACR_SERVER" \
    --registry-username "$ACR_USER" \
    --registry-password "$ACR_PASS" \
    --ingress internal --target-port 8000 \
    --min-replicas 1 --max-replicas 1 \
    --cpu 0.5 --memory 1.0Gi \
    --secrets "storage-conn=$STG_CONN" "admin-key=$ADMIN_KEY" \
    --env-vars "${COLLECTOR_ENV[@]}"
else
  az containerapp update -n collector -g "$RG" \
    --image "$ACR_SERVER/argox-collector:$TAG" \
    --set-env-vars "${COLLECTOR_ENV[@]}"
fi

log "Attaching DuckDB volume (/data = Azure Files share argox-index)"
COLLECTOR_YAML="$(mktemp)"
trap 'rm -f "$COLLECTOR_YAML"' EXIT
az containerapp show -n collector -g "$RG" -o yaml > "$COLLECTOR_YAML"
# Patch az's exported YAML in place: idempotently add the mount + volume.
python3 - "$COLLECTOR_YAML" <<'PY'
import sys, yaml
path = sys.argv[1]
with open(path) as f:
    d = yaml.safe_load(f)
tpl = d["properties"]["template"]
container = tpl["containers"][0]
mounts = container.setdefault("volumeMounts", []) or []
container["volumeMounts"] = mounts
if not any(m.get("volumeName") == "index-vol" for m in mounts):
    mounts.append({"volumeName": "index-vol", "mountPath": "/data"})
vols = tpl.setdefault("volumes", []) or []
tpl["volumes"] = vols
if not any(v.get("name") == "index-vol" for v in vols):
    vols.append({"name": "index-vol", "storageName": "argox-index",
                 "storageType": "AzureFile"})
with open(path, "w") as f:
    yaml.safe_dump(d, f, sort_keys=False)
PY
az containerapp update -n collector -g "$RG" --yaml "$COLLECTOR_YAML"

# The Dashboard's nginx proxies to the Collector over plain HTTP (http://collector).
# With allowInsecure=false the internal ingress redirects HTTP->HTTPS, which nginx
# does not follow; allow insecure so same-environment HTTP proxying works. Traffic
# never leaves the environment and the app still enforces API-key/OIDC auth.
az containerapp ingress update -n collector -g "$RG" --allow-insecure true >/dev/null

# --- dashboard: external, stateless ----------------------------------------
log "Dashboard app (external ingress, public)"
if az containerapp show -n dashboard -g "$RG" >/dev/null 2>&1; then
  az containerapp update -n dashboard -g "$RG" \
    --image "$ACR_SERVER/argox-dashboard:$TAG"
else
  az containerapp create -g "$RG" -n dashboard \
    --environment "$ENV" \
    --image "$ACR_SERVER/argox-dashboard:$TAG" \
    --registry-server "$ACR_SERVER" \
    --registry-username "$ACR_USER" \
    --registry-password "$ACR_PASS" \
    --ingress external --target-port 80 \
    --min-replicas 1 --max-replicas 3 \
    --env-vars COLLECTOR_UPSTREAM=http://collector
fi

# --- done ------------------------------------------------------------------
FQDN="$(az containerapp show -n dashboard -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
log "Deploy complete"
echo "Dashboard: https://$FQDN"
echo "Admin key: stored in $ENV_FILE (ADMIN_KEY); not printed."
echo
echo "Smoke test (the Collector is reachable only via /api and /v1 through the"
echo "dashboard proxy; / serves the SPA, so test an /api path):"
echo "  # 401 'missing bearer credential' proves the Collector is reachable:"
echo "  curl -s -o /dev/null -w '%{http_code}\\n' https://$FQDN/api/v1/traces?limit=1"
echo "  # Mint a key with the break-glass admin key (loaded from .env):"
echo "  curl -s -X POST https://$FQDN/api/v1/keys \\"
echo "    -H \"Authorization: Bearer \$ADMIN_KEY\" -H 'Content-Type: application/json' \\"
echo "    -d '{\"name\":\"prod\",\"scopes\":[\"read\",\"ingest\"]}'"
