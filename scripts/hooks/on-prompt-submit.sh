#!/usr/bin/env bash
# UserPromptSubmit hook — fires when the user types a prompt. Refreshes the
# idle timer so the heartbeat doesn't emit stale keepalive cues.
set -euo pipefail

if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  printf '[on-prompt-submit] CLAUDE_PLUGIN_ROOT unset; skipping\n' >&2
  exit 0
fi
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state
atomic_write "$STATE_DIR/last-activity.ts" "$(date +%s)"

exit 0
