#!/usr/bin/env bash
# Stop hook — nudge to run /argox-doc when source changed but docs/devlog did not.
# Fires at most once per session (marker file). Never writes prose; only reminds.
set -euo pipefail

input="$(cat)"

# Parse fields from the Stop payload without a jq dependency.
read_field() {
  printf '%s' "$input" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null \
    || true
}

stop_active="$(read_field stop_hook_active)"
session_id="$(read_field session_id)"

# Avoid loops: do nothing if already continuing from a stop hook.
case "$stop_active" in True|true) exit 0 ;; esac

project_dir="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$project_dir" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

# Fire at most once per session.
marker_dir="$project_dir/.argox"
marker="$marker_dir/doc-nudge-${session_id:-nosession}"
[ -f "$marker" ] && exit 0

# Collect changed paths: committed vs dev + working tree + staged + untracked.
changed=""
if git rev-parse --verify --quiet dev >/dev/null 2>&1; then
  changed="$(git diff --name-only dev...HEAD 2>/dev/null || true)"
fi
changed="$changed
$(git diff --name-only HEAD 2>/dev/null || true)
$(git diff --name-only --staged 2>/dev/null || true)
$(git ls-files --others --exclude-standard 2>/dev/null || true)"

# Source changed under any argox-* package src tree?
src_changed="$(printf '%s\n' "$changed" | grep -E 'argox-[^/]+/src/.*\.py$' || true)"
[ -z "$src_changed" ] && exit 0

# Devlog already touched this round?
devlog_touched="$(printf '%s\n' "$changed" | grep -E 'docs/devlog/.+\.md$' || true)"
[ -n "$devlog_touched" ] && exit 0

# Source changed, devlog not — nudge exactly once.
mkdir -p "$marker_dir"
: > "$marker"

cat <<'JSON'
{"decision":"block","reason":"Source files under argox-*/src changed but docs/devlog has no new entry. Run /argox-doc to record what changed and why before wrapping up. If this change intentionally needs no documentation, state why and stop again."}
JSON
