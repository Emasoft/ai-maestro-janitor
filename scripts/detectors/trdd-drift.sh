#!/usr/bin/env bash
# TRDD drift detector — one-shot scan for stale "In progress" / "Not started" TRDDs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

STALE_DAYS=$(coerce_int "${CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS:-}" 14)
SEEN="$STATE_DIR/trdd-drift-seen.txt"

main() {
  local root trdd_dir
  root=$(resolve_project_root)
  trdd_dir="$root/${CLAUDE_PLUGIN_OPTION_TRDD_PATH:-design/tasks}"
  trdd_dir="${trdd_dir%/}"

  [ -d "$trdd_dir" ] || { log_line trdd-drift "TRDD dir $trdd_dir not present — skipping"; return; }

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

    # Prefer git last-commit timestamp, fall back to mtime for uncommitted
    # files. `date -r <path>` is GNU-only — BSD uses `-r <epoch>` — so
    # file_mtime from state.sh is the portable helper.
    local touched_epoch
    touched_epoch=$(git -C "$root" log -1 --format=%ct -- "$f" 2>/dev/null) || touched_epoch=""
    [[ "$touched_epoch" =~ ^[0-9]+$ ]] || touched_epoch=""
    [ -z "$touched_epoch" ] && touched_epoch=$(file_mtime "$f")
    [ "$touched_epoch" = "0" ] && continue

    local age_days=$(( (now - touched_epoch) / 86400 ))
    [ "$age_days" -lt "$STALE_DAYS" ] && continue

    # Require a full 36-char UUID and a non-empty slug. Older regex was too
    # permissive — files like `TRDD-deadbeef.md` landed uuid="" and collided
    # on the shared dedupe key `drift@@bucket-N`.
    local uuid
    uuid=$(basename "$f" | sed -nE 's/^TRDD-([0-9a-f-]{36})-.+\.md$/\1/p')
    [ -z "$uuid" ] && continue
    local bucket=$(( age_days / 7 ))
    emit_once "$SEEN" "drift@${uuid}@bucket-${bucket}" \
      "[trdd-drift] TRDD-${uuid:0:8} status='${status}' but file untouched for ${age_days}d."
  done
  shopt -u nullglob

  rotate_log_if_big trdd-drift
}

main
exit 0
