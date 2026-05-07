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

# --- Phase 0: paused sentinel ----------------------------------------------
# /janitor-pause writes $STATE_DIR/paused with an optional epoch-second
# expiry on its first line. Empty file = pause indefinitely. We exit early
# with no output, leaving the cron itself in place — the user can resume
# without re-running /janitor-arm.
PAUSED_FILE="$STATE_DIR/paused"
if [ -f "$PAUSED_FILE" ]; then
  paused_until=$(read_int_state "$PAUSED_FILE" 0)
  now_ts=$(date +%s)
  if [ "$paused_until" = "0" ] || [ "$now_ts" -lt "$paused_until" ]; then
    log_line dispatch "skipped: paused (until=${paused_until})"
    exit 0
  fi
  # Expiry passed → auto-resume. Remove the sentinel and continue.
  rm -f "$PAUSED_FILE"
  log_line dispatch "auto-resumed: pause expiry passed (was ${paused_until})"
fi

# --- Phase 0.5: log retention ----------------------------------------------
# Bound .janitor/logs/ growth. Fires at most once per LOCAL day via a stamp
# (`%Y%m%d` in the user's timezone — consistent with the rest of the plugin's
# local-time convention). Successive heartbeats inside the same day re-read
# the stamp and skip the find call; the cost per fire is one stat() + one
# string compare.
#
# `find ... -mtime +N -delete` is safe-by-design: GNU and BSD find both
# expand the path argument before evaluating tests, so we only ever delete
# regular files older than N days INSIDE our own log dir; the dir itself
# is never targeted by `-type f`.
log_retention_days=$(coerce_int "${CLAUDE_PLUGIN_OPTION_LOG_RETENTION_DAYS:-}" 30)
if [ "$log_retention_days" -gt 0 ]; then
  log_retention_stamp="$STATE_DIR/log-retention-last-day.txt"
  today=$(date +%Y%m%d)
  prev_day=""
  [ -f "$log_retention_stamp" ] && prev_day=$(cat "$log_retention_stamp" 2>/dev/null || true)
  if [ "$prev_day" != "$today" ]; then
    find "$LOG_DIR" -type f \( -name '*.log' -o -name '*.log.1' \) -mtime "+${log_retention_days}" -delete 2>/dev/null || true
    atomic_write "$log_retention_stamp" "$today"
  fi
fi

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
run_detector version-update   "$(coerce_int "${CLAUDE_PLUGIN_OPTION_VERSION_CHECK_INTERVAL:-}"   86400)"
run_detector trashcan-purge   "$(coerce_int "${CLAUDE_PLUGIN_OPTION_TRASHCAN_PURGE_INTERVAL:-}"  86400)"

# Detectors added in v0.4.0 from the high-fit catalogue ideas:
run_detector remote-credentials  "$(coerce_int "${CLAUDE_PLUGIN_OPTION_REMOTE_CREDENTIALS_INTERVAL:-}"  3600)"
run_detector stale-stash         "$(coerce_int "${CLAUDE_PLUGIN_OPTION_STALE_STASH_INTERVAL:-}"        86400)"
run_detector nested-git-safety   "$(coerce_int "${CLAUDE_PLUGIN_OPTION_NESTED_GIT_SAFETY_INTERVAL:-}"   3600)"
run_detector tracked-ignored     "$(coerce_int "${CLAUDE_PLUGIN_OPTION_TRACKED_IGNORED_INTERVAL:-}"     3600)"
run_detector plugin-updates      "$(coerce_int "${CLAUDE_PLUGIN_OPTION_PLUGIN_UPDATES_INTERVAL:-}"     86400)"
run_detector mcp-config-drift    "$(coerce_int "${CLAUDE_PLUGIN_OPTION_MCP_CONFIG_DRIFT_INTERVAL:-}"   3600)"

rotate_log_if_big dispatch
exit 0
