#!/usr/bin/env bash
# Cron-fire entry point for the janitor heartbeat (v0.2.0+).
#
# Invoked by the CronCreate heartbeat armed by /janitor-arm. Each fire is a
# fresh user turn inside the running Claude Code session: the cron prompt
# shells out to this script, captures stdout, and surfaces any drift lines to
# the model. Exits silently with no output when nothing is drifting.
#
# Behavior:
#   1. If rate-limited.flag exists, emit a single [janitor-resume] line and
#      clear the flag. The cron fire itself proves the API is reachable again,
#      so the model treats the line as a cue to resume the prior task.
#   2. Otherwise run each drift detector in --one-shot mode, respecting its
#      configured internal cadence via per-detector last-run state files.
#   3. Emit only new findings — the detectors' seen-files handle dedupe.
#
# State:
#   $PROJECT_ROOT/.janitor/state/rate-limited.flag
#   $PROJECT_ROOT/.janitor/state/rate-limited-since.ts
#   $PROJECT_ROOT/.janitor/state/last-run-<detector>.ts
#
# Exit code: 0 on normal completion (including no drift). Non-zero only on
# unrecoverable errors (missing state lib, malformed detector).

set -euo pipefail

# Resolve script dir so we can find the detectors regardless of cwd.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=./lib/state.sh
source "$HERE/lib/state.sh"

init_state

# --- Phase 1: rate-limit recovery ------------------------------------------
if [ -f "$STATE_DIR/rate-limited.flag" ]; then
  since=$(cat "$STATE_DIR/rate-limited-since.ts" 2>/dev/null || date +%s)
  now=$(date +%s)
  age=$(( now - since ))
  echo "[janitor-resume] rate-limit cleared after ${age}s — API is reachable again. Resume the previous pending task."
  rm -f "$STATE_DIR/rate-limited.flag" \
        "$STATE_DIR/rate-limited-since.ts"
  log_line dispatch "rate-limit cleared after ${age}s, resume cue emitted"
  # Skip drift detectors this fire so resume gets clean attention.
  exit 0
fi

# --- Phase 2: drift detectors ----------------------------------------------
# Each detector has a minimum internal cadence. The heartbeat may fire more
# often than that (e.g. every 4 min); this loop guards per-detector work.
detector_is_due() {
  local name="$1" interval="$2"
  local last_file="$STATE_DIR/last-run-${name}.ts"
  [ -f "$last_file" ] || return 0  # never run → due
  local last now age
  last=$(cat "$last_file" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - last ))
  [ "$age" -ge "$interval" ]
}

mark_detector_ran() {
  atomic_write "$STATE_DIR/last-run-${1}.ts" "$(date +%s)"
}

run_detector() {
  local name="$1" interval="$2"
  local script="$HERE/detectors/${name}.sh"
  [ -x "$script" ] || { log_line dispatch "detector '${name}' missing at $script"; return; }
  detector_is_due "$name" "$interval" || return 0
  # stdout of the detector passes through to the cron prompt as drift findings.
  # stderr goes to the detector's own log via state.sh.
  "$script" --one-shot || log_line dispatch "detector '${name}' exited non-zero"
  mark_detector_ran "$name"
}

# Intervals come from userConfig; fall back to sensible defaults.
run_detector pr-reconciler    "${CLAUDE_PLUGIN_OPTION_PR_RECONCILER_INTERVAL:-900}"
run_detector worktree-janitor "${CLAUDE_PLUGIN_OPTION_WORKTREE_JANITOR_INTERVAL:-900}"
run_detector trdd-drift       "${CLAUDE_PLUGIN_OPTION_TRDD_DRIFT_INTERVAL:-3600}"
run_detector trdd-reminder    "${CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL:-14400}"
run_detector task-pr-mismatch "${CLAUDE_PLUGIN_OPTION_TASK_PR_MISMATCH_INTERVAL:-1800}"

rotate_log_if_big dispatch
exit 0
