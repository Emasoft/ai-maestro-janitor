#!/usr/bin/env bash
# Dirty-tree detector — nudges Claude Code to commit when the working tree
# has been dirty for longer than the configured threshold. Frequent commits
# are the recovery net: every commit is a restore point if a later change
# introduces a bug. When the git safety guard blocks a destructive op, the
# right moves are: move files to a `_dev/` folder, `git rm` to stage a
# recoverable deletion, `git stash`, or stash+branch as a backup.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/dirty-tree-seen.txt"
DIRTY_SINCE="$STATE_DIR/dirty-tree-since.ts"

THRESHOLD="${CLAUDE_PLUGIN_OPTION_DIRTY_TREE_THRESHOLD:-1800}"

main() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line dirty-tree "not a git repo — skipping"
    return
  }

  local dirty_lines
  dirty_lines=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

  if [ "$dirty_lines" -eq 0 ]; then
    # Clean tree — clear state and rearm.
    rm -f "$DIRTY_SINCE"
    [ -f "$SEEN" ] && : > "$SEEN"
    return
  fi

  local now since age
  now=$(date +%s)
  if [ ! -f "$DIRTY_SINCE" ]; then
    atomic_write "$DIRTY_SINCE" "$now"
    since="$now"
  else
    since=$(cat "$DIRTY_SINCE" 2>/dev/null || echo "$now")
  fi
  age=$(( now - since ))

  [ "$age" -lt "$THRESHOLD" ] && return

  # Re-emit once per threshold-sized window so a long-ignored dirty tree
  # keeps nudging. Guard against THRESHOLD=0 (user-misconfig) with a 60s floor.
  local window=$THRESHOLD
  [ "$window" -lt 60 ] && window=60
  local bucket=$(( age / window ))
  local age_m=$(( age / 60 ))

  emit_once "$SEEN" "dirty@b${bucket}" \
    "[dirty-tree] Working tree has been dirty for ~${age_m}min (${dirty_lines} uncommitted change(s)). Commit now — frequent commits are the recovery net. Stage specific files by name (never 'git add -A'). If git safety blocks a destructive op: move files to a _dev/ folder, use 'git rm' to stage a recoverable deletion, 'git stash' to park work, or create a backup branch."

  rotate_log_if_big dirty-tree
}

main
exit 0
