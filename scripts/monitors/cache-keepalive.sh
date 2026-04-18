#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"
init_state

ONE_SHOT=0
[ "${1:-}" = "--one-shot" ] && ONE_SHOT=1

# Default 270s = 4m30s, 30s margin under the 5-min prompt-cache TTL.
# Raise to 3600 if the session explicitly opts into the 1-hour cache.
THRESHOLD="${CLAUDE_PLUGIN_OPTION_CACHE_KEEPALIVE_THRESHOLD:-270}"
POLL=30

run_once() {
  # Suppress during rate-limit — API can't service the nudge anyway.
  [ -f "$STATE_DIR/rate-limited.flag" ] && return 0
  [ -f "$STATE_DIR/last-activity.ts" ]  || return 0
  [ -f "$STATE_DIR/keepalive-sent.flag" ] && return 0

  local last now age
  last=$(cat "$STATE_DIR/last-activity.ts")
  now=$(date +%s)
  age=$(( now - last ))

  if [ "$age" -ge "$THRESHOLD" ]; then
    echo "[cache-keepalive] ${age}s idle — prompt cache at risk of expiry. Acknowledge with 'ack' or resume the last pending task."
    touch "$STATE_DIR/keepalive-sent.flag"
  fi
}

if [ "$ONE_SHOT" = "1" ]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$POLL"
done
