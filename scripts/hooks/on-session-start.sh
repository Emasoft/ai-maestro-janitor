#!/usr/bin/env bash
# SessionStart hook — initializes .janitor state and reminds Claude to arm the
# heartbeat cron if this is a fresh session. Runs as part of the plugin's hook
# lifecycle, NOT at cron-fire time.
set -euo pipefail

# Claude Code always sets CLAUDE_PLUGIN_ROOT for plugin hooks, but guard under
# `set -u` anyway so direct-shell invocations or future harness changes fail
# softly rather than aborting with "unbound variable".
if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  printf '[on-session-start] CLAUDE_PLUGIN_ROOT unset; skipping\n' >&2
  exit 0
fi
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"

init_state

# Clear any stale flag from a prior session crash. If the last session ended
# mid-rate-limit, the flag is preserved and the heartbeat cron will emit a
# resume cue on its next fire — which is what we want. So only clear flags that
# cannot represent valid cross-session state.
rm -f "$STATE_DIR/keepalive-sent.flag"

atomic_write "$STATE_DIR/last-activity.ts" "$(date +%s)"

log_line session-start "state initialized at $STATE_DIR"

# Stdout from this hook becomes additional context for the first user turn.
# Remind Claude to arm the heartbeat cron. /janitor-arm is idempotent, so even
# if the durable cron survived a previous session, re-arming is safe.
cat <<'EOS'
[ai-maestro-janitor] The janitor heartbeat keeps drift detection and rate-limit recovery running in this session. If you have not done so yet (or if the previous cron hit its 7-day auto-expiry), run /janitor-arm to arm it. The skill is idempotent — safe to re-run.
EOS
