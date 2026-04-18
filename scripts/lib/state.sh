#!/usr/bin/env bash
# Shared state helpers for ai-maestro-janitor hooks and monitors.
# Resolves the project-local state/log dirs from $CLAUDE_PROJECT_DIR, or $PWD as
# a last-resort fallback when the env var is unset (e.g. --one-shot mode in CI).

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
# readers (monitors polling the flag) from seeing a half-written file.
atomic_write() {
  local target="$1"
  local value="$2"
  local tmp="${target}.tmp.$$"
  printf '%s' "$value" > "$tmp"
  mv -f "$tmp" "$target"
}

# Append one log line with ISO timestamp to the monitor's log file.
# Usage: log_line <monitor-name> <message...>
log_line() {
  local name="$1"; shift
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_DIR/$name.log"
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
