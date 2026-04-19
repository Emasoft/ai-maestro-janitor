#!/usr/bin/env bash
# UserPromptSubmit hook — fires when the user types a prompt. Refreshes the
# idle timer so the heartbeat doesn't emit stale keepalive cues.
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state
atomic_write "$STATE_DIR/last-activity.ts" "$(date +%s)"

exit 0
