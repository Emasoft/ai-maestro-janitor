#!/usr/bin/env bash
# TRDD reminder — consolidated reminder of all TRDDs currently "In progress".
# Uses a time-bucket key for dedupe so the reminder fires at most once per
# configured interval even when the heartbeat cron fires more often.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

INTERVAL=$(coerce_int "${CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL:-}" 14400)

# Prefer a sha1 tool that's always present; shasum is Perl-based and absent
# on minimal Alpine images, sha1sum is GNU coreutils.
sha1_stream() {
  if command -v sha1sum >/dev/null 2>&1; then
    sha1sum | awk '{print $1}'
  else
    shasum | awk '{print $1}'
  fi
}

session_key() {
  # Prefer CLAUDE_SESSION_ID for true session scoping. Otherwise fall back to
  # hostname + date (NOT PPID — inside a cron-fire subshell PPID is the hook's
  # short-lived shell, different on every fire, so the dedupe file rotated
  # every 5 minutes and the reminder re-emitted on every heartbeat).
  if [ -n "${CLAUDE_SESSION_ID:-}" ]; then
    echo "$CLAUDE_SESSION_ID"
  else
    printf '%s@%s' "$(hostname -s)" "$(date +%Y-%m-%d)" | sha1_stream | cut -c1-12
  fi
}

main() {
  local root trdd_dir
  root=$(resolve_project_root)
  trdd_dir="$root/${CLAUDE_PLUGIN_OPTION_TRDD_PATH:-design/tasks}"
  trdd_dir="${trdd_dir%/}"

  [ -d "$trdd_dir" ] || { log_line trdd-reminder "TRDD dir $trdd_dir not present — skipping"; return; }

  local now
  now=$(date +%s)
  local session
  session=$(session_key)
  local seen="$STATE_DIR/trdd-reminder-session-${session}.txt"

  local entries=""
  local count=0
  shopt -s nullglob
  local f
  for f in "$trdd_dir"/TRDD-*.md; do
    local status
    status=$(grep -E '^\*\*Status:\*\*' "$f" 2>/dev/null | head -1 \
             | sed -E 's/^\*\*Status:\*\*[[:space:]]*//' \
             | tr -d '\r' | xargs) || status=""
    [ "$status" = "In progress" ] || continue

    local touched_epoch
    touched_epoch=$(git -C "$root" log -1 --format=%ct -- "$f" 2>/dev/null) || touched_epoch=""
    [[ "$touched_epoch" =~ ^[0-9]+$ ]] || touched_epoch=""
    [ -z "$touched_epoch" ] && touched_epoch=$(file_mtime "$f")
    [ "$touched_epoch" = "0" ] && touched_epoch="$now"
    local age_days=$(( (now - touched_epoch) / 86400 ))
    local uuid
    uuid=$(basename "$f" | sed -nE 's/^TRDD-([0-9a-f-]{36})-.+\.md$/\1/p')
    [ -z "$uuid" ] && continue

    entries+="TRDD-${uuid:0:8} (${age_days}d), "
    count=$(( count + 1 ))
  done
  shopt -u nullglob

  [ "$count" = "0" ] && return

  entries="${entries%, }"
  local tick_key
  tick_key="tick-$(( now / INTERVAL ))"
  emit_once "$seen" "$tick_key" \
    "[trdd-reminder] ${count} TRDD(s) currently In progress: ${entries}."

  rotate_log_if_big trdd-reminder
}

main
exit 0
