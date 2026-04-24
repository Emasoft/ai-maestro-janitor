#!/usr/bin/env bash
# Shared state helpers for ai-maestro-janitor hooks and detectors.
# Resolves the project-local state/log dirs from $CLAUDE_PROJECT_DIR, or $PWD as
# a last-resort fallback when the env var is unset (e.g. one-shot mode in CI).

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
# Usage: log_line <detector-name> <message...>
log_line() {
  local name="$1"; shift
  printf '[%s] %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)" "$*" >> "$LOG_DIR/$name.log"
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
