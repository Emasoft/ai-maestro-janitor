#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state
atomic_write "$STATE_DIR/last-activity.ts" "$(date +%s)"
rm -f "$STATE_DIR/keepalive-sent.flag" \
      "$STATE_DIR/rate-limited.flag" \
      "$STATE_DIR/rate-limited-since.ts"
atomic_write "$STATE_DIR/retry-count" "0"

exit 0
