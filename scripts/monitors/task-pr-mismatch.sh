#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/dedupe.sh"
init_state

ONE_SHOT=0
[ "${1:-}" = "--one-shot" ] && ONE_SHOT=1

INTERVAL="${CLAUDE_PLUGIN_OPTION_TASK_PR_MISMATCH_INTERVAL:-1800}"
SEEN="$STATE_DIR/task-pr-mismatch-seen.txt"

# Resolve the team UUID under ~/.claude/tasks/. Claude Code uses one dir per
# running team/session; we pick the most recently modified one since that's
# almost always the current session's own task directory.
resolve_team_uuid() {
  local tasks_root="$HOME/.claude/tasks"
  [ -d "$tasks_root" ] || return 1
  local newest
  newest=$(ls -t "$tasks_root" 2>/dev/null | head -1) || return 1
  [ -z "$newest" ] && return 1
  echo "$newest"
}

run_once() {
  local repo="${CLAUDE_PLUGIN_OPTION_GITHUB_REPO:-}"
  if [ -z "$repo" ]; then
    repo=$(git remote get-url origin 2>/dev/null \
      | sed -E 's|.*github\.com[:/]([^/]+/[^/.]+)(\.git)?|\1|' | head -1) || true
  fi
  [ -z "$repo" ] && { log_line task-pr-mismatch "no github_repo — skipping tick"; return; }

  local team
  team=$(resolve_team_uuid) || { log_line task-pr-mismatch "no task directory under ~/.claude/tasks — skipping tick"; return; }
  local tasks_dir="$HOME/.claude/tasks/$team"
  [ -d "$tasks_dir" ] || { log_line task-pr-mismatch "team dir $tasks_dir missing — skipping tick"; return; }

  shopt -s nullglob
  local t
  for t in "$tasks_dir"/*.json; do
    local id status subject description
    id=$(jq -r '.id // empty' "$t" 2>/dev/null) || continue
    [ -z "$id" ] && continue
    status=$(jq -r '.status // "pending"' "$t")
    subject=$(jq -r '.subject // ""' "$t")
    description=$(jq -r '.description // ""' "$t")

    # Only cross-check for PR refs on completed or in_progress tasks.
    case "$status" in
      completed|in_progress) ;;
      *) continue ;;
    esac

    # Extract PR numbers: #123 style only. Avoid issue-number-looking things
    # embedded in UUIDs or commit SHAs.
    local refs
    refs=$(printf '%s %s' "$subject" "$description" \
           | grep -oE '(^|[[:space:]])#[0-9]+' \
           | tr -d '# ' | sort -u) || refs=""
    [ -z "$refs" ] && continue

    local pr_num
    for pr_num in $refs; do
      local pr_state
      pr_state=$(gh pr view "$pr_num" --repo "$repo" --json state --jq .state 2>/dev/null) || continue
      local clean_subject="${subject:0:60}"

      if [ "$status" = "completed" ] && [ "$pr_state" = "OPEN" ]; then
        emit_once "$SEEN" "task-${id}@pr-${pr_num}@completed-OPEN" \
          "[task-pr-mismatch] Task #${id} '${clean_subject}' marked completed but PR #${pr_num} is still open."
      elif [ "$status" = "in_progress" ] && { [ "$pr_state" = "MERGED" ] || [ "$pr_state" = "CLOSED" ]; }; then
        emit_once "$SEEN" "task-${id}@pr-${pr_num}@in_progress-${pr_state}" \
          "[task-pr-mismatch] Task #${id} '${clean_subject}' still in-progress but PR #${pr_num} is already ${pr_state}."
      fi
    done
  done
  shopt -u nullglob

  rotate_log_if_big task-pr-mismatch
}

if [ "$ONE_SHOT" = "1" ]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$INTERVAL"
done
