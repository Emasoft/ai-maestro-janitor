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
#   2. If the heartbeat cron is approaching its 7-day auto-expiry, emit a
#      single [janitor-renew] line so Claude re-runs /janitor-arm before the
#      cron dies. The skill is idempotent (CronDelete old + CronCreate new).
#   3. Otherwise run each drift detector in --one-shot mode, respecting its
#      configured internal cadence via per-detector last-run state files.
#   4. Emit only new findings — the detectors' seen-files handle dedupe.
#
# State:
#   $PROJECT_ROOT/.janitor/state/rate-limited.flag
#   $PROJECT_ROOT/.janitor/state/rate-limited-since.ts
#   $PROJECT_ROOT/.janitor/state/last-run-<detector>.ts
#   $PROJECT_ROOT/.janitor/state/heartbeat-armed-at.ts   # written by /janitor-arm
#   $PROJECT_ROOT/.janitor/state/heartbeat-renew-seen.txt
#
# Exit code: 0 on normal completion (including no drift). Non-zero only on
# unrecoverable errors (missing state lib, malformed detector).

set -euo pipefail

# Resolve script dir so we can find the detectors regardless of cwd.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=./lib/state.sh
source "$HERE/lib/state.sh"
# shellcheck source=./lib/dedupe.sh
source "$HERE/lib/dedupe.sh"

init_state

# --- Phase 1: rate-limit recovery ------------------------------------------
# State-file reads are coerced to int via read_int_state: a corrupted or
# hand-edited since-file otherwise aborts the whole heartbeat under `set -u`
# ("$(( now - abc ))" → unbound variable).
if [ -f "$STATE_DIR/rate-limited.flag" ]; then
  since=$(read_int_state "$STATE_DIR/rate-limited-since.ts" "$(date +%s)")
  now=$(date +%s)
  age=$(( now - since ))
  if [ "$age" -gt 0 ]; then
    echo "[janitor-resume] rate-limit cleared after ${age}s — API is reachable again. Resume the previous pending task."
  else
    # since-file was missing or in the future (clock skew); still cue resume.
    echo "[janitor-resume] rate-limit cleared (duration unknown) — API is reachable again. Resume the previous pending task."
  fi
  rm -f "$STATE_DIR/rate-limited.flag" \
        "$STATE_DIR/rate-limited-since.ts"
  log_line dispatch "rate-limit cleared after ${age}s, resume cue emitted"
  # Skip drift detectors this fire so resume gets clean attention.
  exit 0
fi

# --- Phase 1.5: heartbeat auto-renew ---------------------------------------
# Durable recurring CronCreate jobs auto-expire after 7 days. dispatch.sh
# can't call CronCreate itself (that's session-tool territory), so we emit a
# renewal nudge at day 6, the model notices, and re-runs /janitor-arm which
# idempotently replaces the cron with a fresh 7-day one. Dedupe by day bucket
# so repeated heartbeat fires don't spam the line.
#
# armed-at.ts is written by /janitor-arm on every successful CronCreate. If
# the file is missing (e.g. a plugin upgrade or a user-deleted state dir),
# skip the renew check — the SessionStart hook will still nudge the user to
# /janitor-arm on the next session, which recreates both the cron and the
# timestamp.
renew_threshold_days=$(coerce_int "${CLAUDE_PLUGIN_OPTION_HEARTBEAT_RENEWAL_THRESHOLD_DAYS:-}" 6)
renew_threshold_sec=$(( renew_threshold_days * 86400 ))
armed_at_file="$STATE_DIR/heartbeat-armed-at.ts"
if [ -f "$armed_at_file" ]; then
  armed_at=$(read_int_state "$armed_at_file" 0)
  now=$(date +%s)
  age=$(( now - armed_at ))
  if [ "$armed_at" -gt 0 ] && [ "$age" -ge "$renew_threshold_sec" ]; then
    age_days=$(( age / 86400 ))
    bucket=$(( age / 86400 ))  # one emit per day once we pass the threshold
    emit_once "$STATE_DIR/heartbeat-renew-seen.txt" "renew@day${bucket}" \
      "[janitor-renew] heartbeat cron is ${age_days} day(s) old, approaching the 7-day auto-expiry. Run /janitor-arm to renew — it is idempotent (deletes the old cron and creates a fresh one)."
  fi
fi

# --- Phase 2: drift detectors ----------------------------------------------
# Each detector has a minimum internal cadence. The heartbeat may fire more
# often than that; this loop guards per-detector work.
detector_is_due() {
  local name="$1" interval="$2"
  local last_file="$STATE_DIR/last-run-${name}.ts"
  [ -f "$last_file" ] || return 0  # never run → due
  local last now age
  last=$(read_int_state "$last_file" 0)
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

# Intervals come from userConfig; fall back to sensible defaults. Every value
# is coerced to int because a user typo like "900 seconds" or "15m" would
# otherwise crash the heartbeat on the very next arithmetic operation.
run_detector pr-reconciler    "$(coerce_int "${CLAUDE_PLUGIN_OPTION_PR_RECONCILER_INTERVAL:-}"    900)"
run_detector worktree-janitor "$(coerce_int "${CLAUDE_PLUGIN_OPTION_WORKTREE_JANITOR_INTERVAL:-}" 900)"
run_detector trdd-drift       "$(coerce_int "${CLAUDE_PLUGIN_OPTION_TRDD_DRIFT_INTERVAL:-}"       3600)"
run_detector trdd-reminder    "$(coerce_int "${CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL:-}"    14400)"
run_detector task-pr-mismatch "$(coerce_int "${CLAUDE_PLUGIN_OPTION_TASK_PR_MISMATCH_INTERVAL:-}" 1800)"
run_detector stale-task       "$(coerce_int "${CLAUDE_PLUGIN_OPTION_STALE_TASK_INTERVAL:-}"       1800)"
run_detector dirty-tree       "$(coerce_int "${CLAUDE_PLUGIN_OPTION_DIRTY_TREE_INTERVAL:-}"       300)"
run_detector subagent-report  "$(coerce_int "${CLAUDE_PLUGIN_OPTION_SUBAGENT_REPORT_INTERVAL:-}"  3600)"

rotate_log_if_big dispatch
exit 0
