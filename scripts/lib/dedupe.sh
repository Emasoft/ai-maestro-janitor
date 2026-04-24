#!/usr/bin/env bash
# Dedupe helper: emits a message to stdout the FIRST time a given key is seen,
# stays silent on repeats. Keys persist in a per-detector seen-file so dedupe
# survives session restarts.
#
# The /janitor-audit skill renames seen-files aside and restores them, and a
# cron fire may overlap that window. `mkdir` is an atomic POSIX primitive (it
# either succeeds or EEXIST-fails without leaving partial state), so we use it
# as a mutex around the grep-then-append sequence — no `flock` dependency,
# works on macOS default userland.

# Usage: emit_once <seen_file> <key> <message>
emit_once() {
  local seen="$1"
  local key="$2"
  local msg="$3"
  mkdir -p "$(dirname "$seen")"
  touch "$seen"
  local lockdir="${seen}.lockdir"
  local retries=50
  while ! mkdir "$lockdir" 2>/dev/null; do
    retries=$((retries - 1))
    if [ "$retries" -le 0 ]; then
      # Lock contention beyond 5s — fail open rather than block dispatch.
      # The caller gets "already seen" semantics; worst case is a dropped
      # nudge that the next fire re-emits.
      return 0
    fi
    sleep 0.1
  done
  if ! grep -qxF -- "$key" "$seen"; then
    printf '%s\n' "$msg"
    printf '%s\n' "$key" >> "$seen"
  fi
  rmdir "$lockdir" 2>/dev/null || true
}

# Forget a key (use when the underlying condition resolves, so the next
# occurrence re-emits). Usage: emit_forget <seen_file> <key>
emit_forget() {
  local seen="$1"
  local key="$2"
  [ -f "$seen" ] || return 0
  local lockdir="${seen}.lockdir"
  local retries=50
  while ! mkdir "$lockdir" 2>/dev/null; do
    retries=$((retries - 1))
    [ "$retries" -le 0 ] && return 0
    sleep 0.1
  done
  local tmp="${seen}.tmp.$$"
  grep -vxF -- "$key" "$seen" > "$tmp" || true
  mv -f "$tmp" "$seen"
  rmdir "$lockdir" 2>/dev/null || true
}
