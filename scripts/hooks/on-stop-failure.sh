#!/usr/bin/env bash
# StopFailure hook — fires when an API error (rate-limit, auth failure, etc.)
# ends the turn instead of Stop. Writes a flag file that the heartbeat cron's
# dispatch.sh reads on its next fire. When the API is reachable again, that
# fire succeeds, dispatch sees the flag, clears it, and emits [janitor-resume]
# so Claude picks up where it left off.
#
# This is the ONE hook that absolutely must never silently fail — if the flag
# isn't written, resume is disabled for this rate-limit window. The guard
# below exits non-zero? No — it exits 0 with a stderr note. Claude Code
# treats non-zero hook exits as blocking, and we'd rather degrade (no resume
# cue) than block the session on a plugin misconfig.
set -euo pipefail

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  printf '[on-stop-failure] CLAUDE_PLUGIN_ROOT unset; resume cue will not be captured for this turn\n' >&2
  exit 0
fi
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state
touch "$STATE_DIR/rate-limited.flag"
atomic_write "$STATE_DIR/rate-limited-since.ts" "$(date +%s)"

log_line stop-failure "rate-limit captured; dispatch.sh will emit resume cue on next heartbeat fire"
exit 0
