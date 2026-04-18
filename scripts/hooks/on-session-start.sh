#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state

# Clear any stale flags from prior session crashes.
rm -f "$STATE_DIR/rate-limited.flag" \
      "$STATE_DIR/rate-limited-since.ts" \
      "$STATE_DIR/keepalive-sent.flag"

atomic_write "$STATE_DIR/last-activity.ts" "$(date +%s)"
atomic_write "$STATE_DIR/retry-count" "0"

log_line session-start "state initialized at $STATE_DIR"
