#!/usr/bin/env bash
# Shared state helpers for ai-maestro-janitor hooks and detectors.
# Resolves the project-local state/log dirs from $CLAUDE_PROJECT_DIR, or $PWD as
# a last-resort fallback when the env var is unset (e.g. one-shot mode in CI).

# sanitize_for_drift_line <text>
#
# Defangs untrusted text before it lands in a drift line on stdout. The
# heartbeat surfaces our drift output to Claude as user-text-like context;
# anyone who can write to a stash message, PR title, branch name, or
# similar non-source content could otherwise prefix `[janitor-resume]` /
# `[janitor-renew]` and try to mimic our marker convention. This is not
# realistically exploitable today (Claude is robust to such mimicry) but
# defense-in-depth costs nothing.
#
# Replacements:
#   * `[` and `]` → `⟦` `⟧`  (visually similar Unicode brackets, distinct
#     from anything we emit ourselves — our markers always use ASCII `[]`)
#   * control chars (0x00-0x1F except tab/newline) → space
#   * trailing whitespace stripped
#
# Cost: one tr + one sed per call; safe for the per-detector budget.
sanitize_for_drift_line() {
  local s="$1"
  # Strip control chars first (they could be terminal escape sequences)
  s=$(printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037')
  # Replace ASCII brackets with their Unicode "mathematical" lookalikes so
  # the result still reads as brackets to a human but does NOT match the
  # `[<token>]` shape of janitor markers.
  s=${s//\[/⟦}
  s=${s//\]/⟧}
  printf '%s' "$s"
}

resolve_project_root() {
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    echo "$CLAUDE_PROJECT_DIR"
  elif root=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "$root"
  else
    pwd
  fi
}

JANITOR_ROOT=$(resolve_project_root)/.janitor
STATE_DIR="$JANITOR_ROOT/state"
LOG_DIR="$JANITOR_ROOT/logs"

init_state() {
  mkdir -p "$STATE_DIR" "$LOG_DIR"
}

# Atomically write a value to a file: write to tmp, then rename. Keeps other
# readers (detectors polling the flag) from seeing a half-written file.
atomic_write() {
  local target="$1"
  local value="$2"
  local tmp="${target}.tmp.$$"
  printf '%s' "$value" > "$tmp"
  mv -f "$tmp" "$target"
}

# Read a state file as a non-negative integer, falling back to 0 on any read
# error or non-numeric content. Detector arithmetic runs under `set -u`, where
# `$(( now - last ))` with a non-numeric `$last` aborts the whole script.
# Usage: value=$(read_int_state <path> [<default>])
read_int_state() {
  local path="$1"
  local default="${2:-0}"
  local value
  value=$(cat "$path" 2>/dev/null || printf '%s' "$default")
  [[ "$value" =~ ^[0-9]+$ ]] || value="$default"
  printf '%s' "$value"
}

# Coerce a user-provided value to a non-negative integer, falling back to the
# supplied default on any non-numeric content. Used to sanitise values coming
# from $CLAUDE_PLUGIN_OPTION_* env vars before they reach `$(( ))`.
coerce_int() {
  local value="${1:-}"
  local default="${2:-0}"
  [[ "$value" =~ ^[0-9]+$ ]] || value="$default"
  printf '%s' "$value"
}

# Return a file's mtime in epoch seconds, portable across GNU coreutils and
# BSD `stat`. Falls back to printing 0 if the file cannot be stat'd.
# Usage: ts=$(file_mtime <path>)
file_mtime() {
  local path="$1"
  if stat -c %Y "$path" >/dev/null 2>&1; then
    stat -c %Y "$path"
  elif stat -f %m "$path" >/dev/null 2>&1; then
    stat -f %m "$path"
  else
    printf '%s' 0
  fi
}

# Append one log line with a local-time timestamp (with GMT offset, compact
# ±HHMM form) to the detector's log file. UTC-only timestamps force humans to
# do timezone arithmetic when debugging; local+offset lets them match their own
# workday at a glance and still recover the absolute time.
#
# When Claude Code 2.1.132+ is running, $CLAUDE_CODE_SESSION_ID is exported into
# Bash subprocess and hook environments. We prepend an `[s:<8-char-prefix>]`
# tag so that .janitor/logs/<detector>.log entries can be correlated across
# concurrent or successive sessions in the same project. Older Claude Code
# versions (and direct shell invocations) leave the var unset and the line
# format degrades gracefully to the original `[ts] msg` shape — no diff.
# Usage: log_line <detector-name> <message...>
log_line() {
  local name="$1"; shift
  local sid="${CLAUDE_CODE_SESSION_ID:-}"
  local ts
  ts=$(date +%Y-%m-%dT%H:%M:%S%z)
  if [ -n "$sid" ]; then
    printf '[%s] [s:%s] %s\n' "$ts" "${sid:0:8}" "$*" >> "$LOG_DIR/$name.log"
  else
    printf '[%s] %s\n' "$ts" "$*" >> "$LOG_DIR/$name.log"
  fi
}

# Rotate a log file when it exceeds 1 MB.
rotate_log_if_big() {
  local name="$1"
  local log="$LOG_DIR/$name.log"
  [ -f "$log" ] || return 0
  local size
  size=$(wc -c < "$log" 2>/dev/null || echo 0)
  if [ "$size" -gt 1048576 ]; then
    mv -f "$log" "$log.1"
  fi
}
