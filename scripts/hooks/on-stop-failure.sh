#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state
# Presence of this flag arms the rate-limit-retry monitor and suppresses the
# cache-keepalive monitor. Cleared by Stop when a successful turn completes.
touch "$STATE_DIR/rate-limited.flag"
atomic_write "$STATE_DIR/rate-limited-since.ts" "$(date +%s)"
atomic_write "$STATE_DIR/retry-count" "0"

log_line stop-failure "rate-limit captured, rate-limit-retry monitor armed"
exit 0
