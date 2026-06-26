#!/usr/bin/env bash
#
# Update an existing Argox deployment on Azure Container Apps.
#
# ACA is revision-based: each change makes a new immutable revision and traffic
# shifts to it once healthy. Mounts, secrets and env vars are part of the app
# template and CARRY OVER to new revisions — only what changed is re-specified.
#
# Subcommands:
#   ./update.sh code <tag> [collector|dashboard|both]   # rebuild + roll image
#   ./update.sh env <collector|dashboard> KEY=VAL ...    # set env var(s)
#   ./update.sh rotate-admin-key                         # new admin key + roll
#   ./update.sh rollback <collector|dashboard> <tag>     # redeploy old image
#   ./update.sh revisions <collector|dashboard>          # list revisions
#   ./update.sh deactivate <collector|dashboard> <rev>   # clean DuckDB swap
#
# Always use a FRESH immutable tag (never reuse one) so revisions and rollbacks
# stay traceable.
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
ACR="${ACR:-argoxacraliando}"
ACR_SERVER="$ACR.azurecr.io"
# Collector context is the argox-project/ parent so the image can bundle the
# sibling argox-core package it imports; its Dockerfile is addressed with -f.
COLLECTOR_CTX="../../argox-project"
COLLECTOR_DOCKERFILE="argox-collector/Dockerfile"
DASHBOARD_CTX="../../argox-dashboard"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,30p' "$0"; exit "${1:-1}"; }

# Set KEY=VALUE in an env file in place (python: value written literally, no sed
# delimiter/metacharacter pitfalls).
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

command -v az >/dev/null || die "az CLI not found."
az account show >/dev/null 2>&1 || die "not logged in. Run 'az login'."

CMD="${1:-}"; shift || true

case "$CMD" in
  code)
    NEWTAG="${1:-}"; TARGET="${2:-both}"
    [[ -n "$NEWTAG" ]] || die "usage: ./update.sh code <tag> [collector|dashboard|both]"

    build_collector() {
      log "Building argox-collector:$NEWTAG"
      # az acr build validates --file relative to the CWD (not the context root)
      # for local-context builds, so run from inside the context and pass `.`.
      ( cd "$COLLECTOR_CTX" && az acr build -r "$ACR" -t "argox-collector:$NEWTAG" -f "$COLLECTOR_DOCKERFILE" . )
      log "Rolling collector to $NEWTAG"
      az containerapp update -n collector -g "$RG" --image "$ACR_SERVER/argox-collector:$NEWTAG"
    }
    build_dashboard() {
      log "Building argox-dashboard:$NEWTAG"
      az acr build -r "$ACR" -t "argox-dashboard:$NEWTAG" "$DASHBOARD_CTX"
      log "Rolling dashboard to $NEWTAG"
      az containerapp update -n dashboard -g "$RG" --image "$ACR_SERVER/argox-dashboard:$NEWTAG"
    }

    case "$TARGET" in
      collector) build_collector ;;
      dashboard) build_dashboard ;;
      both)      build_collector; build_dashboard ;;
      *) die "target must be collector|dashboard|both" ;;
    esac

    # Persist the new tag so the next deploy.sh run matches.
    [[ -f "$ENV_FILE" ]] && persist_env TAG "$NEWTAG" "$ENV_FILE"
    echo
    echo "NOTE: for a clean collector swap (DuckDB single-writer lock), deactivate"
    echo "the old revision once the new one is healthy:"
    echo "  ./update.sh revisions collector"
    echo "  ./update.sh deactivate collector <old-revision>"
    ;;

  env)
    APP="${1:-}"; shift || true
    [[ -n "$APP" && $# -gt 0 ]] || die "usage: ./update.sh env <collector|dashboard> KEY=VAL ..."
    log "Setting env vars on $APP: $*"
    az containerapp update -n "$APP" -g "$RG" --set-env-vars "$@"
    ;;

  rotate-admin-key)
    NEW="$(openssl rand -hex 32)"
    log "Rotating collector admin-key secret"
    az containerapp secret set -n collector -g "$RG" --secrets "admin-key=$NEW"
    # Bump a revision so the running replica picks up the new secret value.
    az containerapp update -n collector -g "$RG"
    if [[ -f "$ENV_FILE" ]]; then
      persist_env ADMIN_KEY "$NEW" "$ENV_FILE"
      echo "Rotated admin key and wrote it to $ENV_FILE (not printed here)."
    else
      die "no .env to persist the rotated key into; aborting before it is lost."
    fi
    ;;

  rollback)
    APP="${1:-}"; TAG_TO="${2:-}"
    [[ -n "$APP" && -n "$TAG_TO" ]] || die "usage: ./update.sh rollback <collector|dashboard> <tag>"
    log "Rolling $APP back to $TAG_TO"
    az containerapp update -n "$APP" -g "$RG" --image "$ACR_SERVER/argox-$APP:$TAG_TO"
    ;;

  revisions)
    APP="${1:-}"; [[ -n "$APP" ]] || die "usage: ./update.sh revisions <collector|dashboard>"
    az containerapp revision list -n "$APP" -g "$RG" -o table
    ;;

  deactivate)
    APP="${1:-}"; REV="${2:-}"
    [[ -n "$APP" && -n "$REV" ]] || die "usage: ./update.sh deactivate <collector|dashboard> <revision>"
    log "Deactivating revision $REV of $APP"
    az containerapp revision deactivate -n "$APP" -g "$RG" --revision "$REV"
    ;;

  ""|-h|--help) usage 0 ;;
  *) die "unknown subcommand '$CMD' (see --help)" ;;
esac

log "Done"
