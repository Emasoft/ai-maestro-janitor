#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/dedupe.sh"
init_state

ONE_SHOT=0
[ "${1:-}" = "--one-shot" ] && ONE_SHOT=1

INTERVAL="${CLAUDE_PLUGIN_OPTION_TRDD_DRIFT_INTERVAL:-3600}"
STALE_DAYS="${CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS:-14}"
SEEN="$STATE_DIR/trdd-drift-seen.txt"

run_once() {
  local root trdd_dir
  root=$(resolve_project_root)
  trdd_dir="$root/${CLAUDE_PLUGIN_OPTION_TRDD_PATH:-design/tasks}"
  trdd_dir="${trdd_dir%/}"

  [ -d "$trdd_dir" ] || { log_line trdd-drift "TRDD dir $trdd_dir not present — skipping tick"; return; }

  local now
  now=$(date +%s)

  shopt -s nullglob
  local f
  for f in "$trdd_dir"/TRDD-*.md; do
    local status
    status=$(grep -E '^\*\*Status:\*\*' "$f" 2>/dev/null | head -1 \
             | sed -E 's/^\*\*Status:\*\*[[:space:]]*//' \
             | tr -d '\r' \
             | xargs) || status=""
    case "$status" in
      "Not started"|"In progress") ;;
      *) continue ;;
    esac

    # Prefer git last-commit timestamp, fall back to mtime for uncommitted files.
    local touched_epoch
    touched_epoch=$(git -C "$root" log -1 --format=%ct -- "$f" 2>/dev/null) || touched_epoch=""
    [ -z "$touched_epoch" ] && touched_epoch=$(date -r "$f" +%s 2>/dev/null || echo 0)

    local age_days=$(( (now - touched_epoch) / 86400 ))
    [ "$age_days" -lt "$STALE_DAYS" ] && continue

    local uuid
    uuid=$(basename "$f" | sed -E 's/^TRDD-([0-9a-f-]+)-.*/\1/')
    local bucket=$(( age_days / 7 ))
    emit_once "$SEEN" "drift@${uuid}@bucket-${bucket}" \
      "[trdd-drift] TRDD-${uuid:0:8} status='${status}' but file untouched for ${age_days}d."
  done
  shopt -u nullglob

  rotate_log_if_big trdd-drift
}

if [ "$ONE_SHOT" = "1" ]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$INTERVAL"
done
