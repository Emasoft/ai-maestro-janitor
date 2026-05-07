#!/usr/bin/env bash
# Stale-stash detector — surfaces git stashes that have been sitting longer
# than the configured threshold. A forgotten stash is a real WIP signal: the
# work is recoverable but invisible to `git status` and `git log`, so it
# rarely surfaces until a stash conflict on `git pull` reminds the user it
# exists. Threshold default 30d; tune via `stash_stale_days` userConfig.
#
# Dedup uses (stash-ref, creation-timestamp) so dropping/reapplying a stash
# rotates the dedup key naturally, and `git stash list` reordering after a
# `git stash drop stash@{0}` doesn't false-trigger a re-emit on stashes that
# were already nudged.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/stale-stash-seen.txt"

STALE_DAYS=$(coerce_int "${CLAUDE_PLUGIN_OPTION_STASH_STALE_DAYS:-}" 30)

main() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line stale-stash "not a git repo — skipping"
    return
  }

  # Stash list with one tab-separated row per entry: ref, ISO-8601 creation
  # time (committer date — what the user expects), short subject. `--format`
  # uses %x09 for literal tab so subjects with colons or whitespace parse
  # cleanly downstream.
  local stashes
  stashes=$(git stash list --format='%gd%x09%cI%x09%s' 2>/dev/null) || {
    log_line stale-stash "git stash list failed — skipping"
    return
  }

  [ -z "$stashes" ] && return

  local now threshold_sec
  now=$(date +%s)
  threshold_sec=$(( STALE_DAYS * 86400 ))

  while IFS=$'\t' read -r ref iso_ts subject; do
    [ -z "$ref" ] && continue
    [ -z "$iso_ts" ] && continue

    # Cross-platform ISO-8601 → epoch. GNU date understands -d "<iso>"; BSD
    # (macOS) date needs -j -f "%Y-%m-%dT%H:%M:%S%z". Try GNU first since most
    # CI runners are Linux; fall back to BSD; emit nothing on parse failure
    # rather than risk a bogus age.
    local created
    if created=$(date -d "$iso_ts" +%s 2>/dev/null); then
      :
    else
      # BSD strptime can't parse the trailing colon in `+02:00`; strip it.
      local bsd_ts
      bsd_ts=$(printf '%s' "$iso_ts" | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/')
      created=$(date -j -f '%Y-%m-%dT%H:%M:%S%z' "$bsd_ts" +%s 2>/dev/null) || {
        log_line stale-stash "could not parse date '$iso_ts' for $ref — skipping entry"
        continue
      }
    fi

    local age_sec=$(( now - created ))
    [ "$age_sec" -lt "$threshold_sec" ] && continue

    local age_days=$(( age_sec / 86400 ))
    local clean_subject="${subject:0:80}"

    # Re-emit at most once per week of additional staleness so a long-ignored
    # stash doesn't go fully silent — the user still gets a cue every 7d.
    local week_bucket=$(( age_sec / (7 * 86400) ))

    # Use the ref together with the ISO timestamp as the entropy of the dedup
    # key: `git stash drop` shifts higher refs down by one, but the timestamp
    # of any given stash never changes once committed.
    local fp
    fp=$(printf '%s\t%s' "$ref" "$iso_ts" | cksum | awk '{print $1}')

    emit_once "$SEEN" "stash@${fp}@w${week_bucket}" \
      "[stale-stash] ${ref} '${clean_subject}' has been stashed for ${age_days}d. Inspect with: git stash show -p ${ref}. Then either reapply (git stash pop ${ref}) or discard (git stash drop ${ref})."
  done <<< "$stashes"

  rotate_log_if_big stale-stash
}

main
exit 0
