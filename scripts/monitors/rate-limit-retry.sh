#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"
init_state

ONE_SHOT=0
[ "${1:-}" = "--one-shot" ] && ONE_SHOT=1

INTERVAL="${CLAUDE_PLUGIN_OPTION_RATE_LIMIT_RETRY_INTERVAL:-120}"

run_once() {
  [ -f "$STATE_DIR/rate-limited.flag" ] || return 0

  local since now age count
  since=$(cat "$STATE_DIR/rate-limited-since.ts" 2>/dev/null || date +%s)
  now=$(date +%s)
  age=$(( now - since ))
  count=$(cat "$STATE_DIR/retry-count" 2>/dev/null || echo 0)

  # Stdout line becomes a Claude notification. When the API is reachable again
  # (token rotation, rate-limit window cleared), Claude interjects and resumes.
  echo "[rate-limit-retry] rate-limit active ${age}s (attempt ${count}). Please resume your previous turn when the API is reachable."

  atomic_write "$STATE_DIR/retry-count" "$(( count + 1 ))"
  rotate_log_if_big rate-limit-retry
}

if [ "$ONE_SHOT" = "1" ]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$INTERVAL"
done
