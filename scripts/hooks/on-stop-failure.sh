#!/usr/bin/env bash
# StopFailure hook — fires when an API error (rate-limit, auth failure, etc.)
# ends the turn instead of Stop. Writes a flag file that the heartbeat cron's
# dispatch.sh reads on its next fire. When the API is reachable again, that
# fire succeeds, dispatch sees the flag, clears it, and emits [janitor-resume]
# so Claude picks up where it left off.
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state
touch "$STATE_DIR/rate-limited.flag"
atomic_write "$STATE_DIR/rate-limited-since.ts" "$(date +%s)"

log_line stop-failure "rate-limit captured; dispatch.sh will emit resume cue on next heartbeat fire"
exit 0
