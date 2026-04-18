# Dedupe helper: emits a message to stdout the FIRST time a given key is seen,
# stays silent on repeats. Keys persist in a per-monitor seen-file so dedupe
# survives session restarts.

# Usage: emit_once <seen_file> <key> <message>
emit_once() {
  local seen="$1"
  local key="$2"
  local msg="$3"
  mkdir -p "$(dirname "$seen")"
  touch "$seen"
  if ! grep -qxF -- "$key" "$seen"; then
    printf '%s\n' "$msg"
    printf '%s\n' "$key" >> "$seen"
  fi
}

# Forget a key (use when the underlying condition resolves, so the next
# occurrence re-emits). Usage: emit_forget <seen_file> <key>
emit_forget() {
  local seen="$1"
  local key="$2"
  [ -f "$seen" ] || return 0
  local tmp="${seen}.tmp.$$"
  grep -vxF -- "$key" "$seen" > "$tmp" || true
  mv -f "$tmp" "$seen"
}
