#!/usr/bin/env bash
# Stop hook — fires when Claude completes a turn successfully. Resets the idle
# timer so the heartbeat's cache-keepalive semantics track the latest activity.
# Does NOT clear rate-limited.flag here — that belongs to the heartbeat itself,
# since a successful turn after a rate-limit is exactly the signal that triggers
# the dispatch.sh [janitor-resume] emission on the next fire.
set -euo pipefail

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  printf '[on-stop] CLAUDE_PLUGIN_ROOT unset; skipping\n' >&2
  exit 0
fi
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state
atomic_write "$STATE_DIR/last-activity.ts" "$(date +%s)"

exit 0
