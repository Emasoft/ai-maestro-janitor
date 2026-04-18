#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/dedupe.sh"
init_state

ONE_SHOT=0
[ "${1:-}" = "--one-shot" ] && ONE_SHOT=1

INTERVAL="${CLAUDE_PLUGIN_OPTION_PR_RECONCILER_INTERVAL:-900}"
STALE_DAYS="${CLAUDE_PLUGIN_OPTION_STALE_PR_DAYS:-14}"
SEEN="$STATE_DIR/pr-reconciler-seen.txt"

run_once() {
  local repo="${CLAUDE_PLUGIN_OPTION_GITHUB_REPO:-}"
  if [ -z "$repo" ]; then
    repo=$(git remote get-url origin 2>/dev/null \
      | sed -E 's|.*github\.com[:/]([^/]+/[^/.]+)(\.git)?|\1|' \
      | head -1) || true
  fi
  if [ -z "$repo" ]; then
    log_line pr-reconciler "no github_repo and no origin remote — skipping tick"
    return
  fi

  local main_sha
  main_sha=$(git rev-parse origin/main 2>/dev/null) || {
    log_line pr-reconciler "origin/main not resolvable — skipping tick"
    return
  }

  # jq computes per-PR age in seconds so we don't need platform-specific date parsing.
  local prs
  prs=$(gh pr list --repo "$repo" --state open \
          --json number,title,headRefOid,updatedAt \
          --jq '.[] | [.number, .headRefOid, (.title | gsub("\\s+"; " ")), ((now - (.updatedAt | fromdateiso8601)) | floor)] | @tsv' \
        2>> "$LOG_DIR/pr-reconciler.log") || {
    log_line pr-reconciler "gh pr list failed (auth? offline?) — skipping tick"
    return
  }

  while IFS=$'\t' read -r num head title age_sec; do
    [ -z "$num" ] && continue
    title=${title:0:80}
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

if [ "$ONE_SHOT" = "1" ]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$INTERVAL"
done
