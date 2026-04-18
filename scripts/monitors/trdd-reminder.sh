#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/dedupe.sh"
init_state

ONE_SHOT=0
[ "${1:-}" = "--one-shot" ] && ONE_SHOT=1

INTERVAL="${CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL:-14400}"

session_key() {
  # Pick a stable session-scoped key: prefer CLAUDE_SESSION_ID, fall back to
  # hostname+pid hash so the dedupe file still rotates across sessions.
  if [ -n "${CLAUDE_SESSION_ID:-}" ]; then
    echo "$CLAUDE_SESSION_ID"
  else
    printf '%s@%s' "$(hostname -s)" "$PPID" | shasum | awk '{print $1}' | cut -c1-12
  fi
}

run_once() {
  local root trdd_dir
  root=$(resolve_project_root)
  trdd_dir="$root/${CLAUDE_PLUGIN_OPTION_TRDD_PATH:-design/tasks}"
  trdd_dir="${trdd_dir%/}"

  [ -d "$trdd_dir" ] || { log_line trdd-reminder "TRDD dir $trdd_dir not present — skipping tick"; return; }

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
    [ -z "$touched_epoch" ] && touched_epoch=$(date -r "$f" +%s 2>/dev/null || echo "$now")
    local age_days=$(( (now - touched_epoch) / 86400 ))
    local uuid
    uuid=$(basename "$f" | sed -E 's/^TRDD-([0-9a-f-]+)-.*/\1/')

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

if [ "$ONE_SHOT" = "1" ]; then
  run_once
  exit 0
fi

# First fire happens 10s after monitor start so hooks have initialized state.
sleep 10
while true; do
  run_once
  sleep "$INTERVAL"
done
