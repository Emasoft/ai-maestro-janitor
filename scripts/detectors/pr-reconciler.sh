#!/usr/bin/env bash
# PR reconciler — one-shot drift detector.
# Invoked by scripts/dispatch.sh (the cron heartbeat) or by the /janitor-audit
# skill. Accepts --one-shot for backward compatibility; runs once either way.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

STALE_DAYS=$(coerce_int "${CLAUDE_PLUGIN_OPTION_STALE_PR_DAYS:-}" 14)
SEEN="$STATE_DIR/pr-reconciler-seen.txt"

main() {
  local repo="${CLAUDE_PLUGIN_OPTION_GITHUB_REPO:-}"
  if [ -z "$repo" ]; then
    repo=$(git remote get-url origin 2>/dev/null \
      | sed -E 's|.*github\.com[:/]([^/]+/[^/.]+)(\.git)?|\1|' \
      | head -1) || true
  fi
  if [ -z "$repo" ]; then
    log_line pr-reconciler "no github_repo and no origin remote — skipping"
    return
  fi

  local main_sha
  main_sha=$(git rev-parse origin/main 2>/dev/null) || {
    log_line pr-reconciler "origin/main not resolvable — skipping"
    return
  }

  # jq computes per-PR age in seconds so we don't need platform-specific date parsing.
  local prs
  prs=$(gh pr list --repo "$repo" --state open \
          --json number,title,headRefOid,updatedAt \
          --jq '.[] | [.number, .headRefOid, (.title | gsub("\\s+"; " ")), ((now - (.updatedAt | fromdateiso8601)) | floor)] | @tsv' \
        2>> "$LOG_DIR/pr-reconciler.log") || {
    log_line pr-reconciler "gh pr list failed (auth? offline?) — skipping"
    return
  }

  if [ -z "$prs" ]; then
    # Distinguish "no stale PRs" from "lost access" in the log — silent
    # no-output otherwise makes this detector look broken when it is in fact
    # just idle (empty repo, private repo without token, or all PRs closed).
    log_line pr-reconciler "no open PRs returned for $repo — nothing to do"
    return
  fi

  while IFS=$'\t' read -r num head title age_sec; do
    [ -z "$num" ] && continue
    title=${title:0:80}
    # Guard against malformed jq output landing a non-integer in age_sec.
    [[ "$age_sec" =~ ^[0-9]+$ ]] || age_sec=0
    local age_days=$(( age_sec / 86400 ))

    if git merge-base --is-ancestor "$head" "$main_sha" 2>/dev/null; then
      emit_once "$SEEN" "noop@PR#${num}@${head}" \
        "[pr-reconciler] PR #${num} '${title}' HEAD ${head:0:8} is already on main — candidate for close."
    fi

    if [ "$age_days" -ge "$STALE_DAYS" ]; then
      local bucket=$(( age_days / 7 ))
      emit_once "$SEEN" "stale@PR#${num}@bucket-${bucket}" \
        "[pr-reconciler] PR #${num} '${title}' has been open ${age_days}d with no new commits — stale."
    fi
  done <<< "$prs"

  rotate_log_if_big pr-reconciler
}

main
exit 0
