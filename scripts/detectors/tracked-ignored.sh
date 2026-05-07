#!/usr/bin/env bash
# Tracked-ignored detector — surfaces files that are CURRENTLY tracked by git
# but ALSO match a rule in the active `.gitignore`. These typically arrive
# when a `.gitignore` rule is added AFTER the file was committed: git keeps
# tracking the file (existing entries survive ignore changes by design),
# while the rule misleads the user into thinking the file is excluded.
#
# `git ls-files --ignored --exclude-standard` produces this list directly.
# Common offenders: `.env` committed before the rule was added, build
# artifacts (`dist/`, `*.pyc`), IDE files (`.idea/`, `.vscode/`), OS noise
# (`.DS_Store`).
#
# Dedup is keyed by HEAD SHA: this list cannot change without a git op
# (commit, rm, ignore-edit), so we re-run the check at most once per HEAD
# rather than once per heartbeat. Saves ~50ms per fire on large repos.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/tracked-ignored-seen.txt"
LAST_HEAD_FILE="$STATE_DIR/tracked-ignored-last-head.ts"

main() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line tracked-ignored "not a git repo — skipping"
    return
  }

  local head_sha
  head_sha=$(git rev-parse HEAD 2>/dev/null) || {
    log_line tracked-ignored "no HEAD (empty repo?) — skipping"
    return
  }

  # If HEAD hasn't moved since last check, the answer can't have changed.
  if [ -f "$LAST_HEAD_FILE" ]; then
    local prev_head
    prev_head=$(cat "$LAST_HEAD_FILE" 2>/dev/null || true)
    if [ "$prev_head" = "$head_sha" ]; then
      return
    fi
  fi

  # `git ls-files --ignored --exclude-standard` requires `--cached` to scope
  # to tracked files (otherwise it walks the working tree and lists ignored
  # files that are not tracked, which is the opposite of what we want).
  local offenders
  offenders=$(git ls-files --ignored --exclude-standard --cached 2>/dev/null) || {
    log_line tracked-ignored "git ls-files failed — skipping"
    atomic_write "$LAST_HEAD_FILE" "$head_sha"
    return
  }

  # Stamp the HEAD as scanned regardless of result, so an empty answer also
  # gets cached and we don't re-shell `git ls-files` on the next heartbeat.
  atomic_write "$LAST_HEAD_FILE" "$head_sha"

  [ -z "$offenders" ] && return

  # Cap the displayed list to avoid drowning the model in a 200-line nudge
  # for projects that committed an entire `node_modules/`. Show the count and
  # the first 10; the user can run `git ls-files -i -c -X .gitignore` to see
  # the full set.
  local count
  count=$(printf '%s\n' "$offenders" | grep -c .)

  local sample
  sample=$(printf '%s\n' "$offenders" | head -10 | sed 's/^/  - /')
  if [ "$count" -gt 10 ]; then
    sample="${sample}
  - …and $(( count - 10 )) more"
  fi

  emit_once "$SEEN" "trackedignored@${head_sha}" \
    "[tracked-ignored] ${count} tracked file(s) match current .gitignore rules — they were committed before the rule was added and git keeps tracking them. Stop tracking with: git rm --cached -r -- <path> (then commit). Affected:
${sample}"

  rotate_log_if_big tracked-ignored
}

main
exit 0
