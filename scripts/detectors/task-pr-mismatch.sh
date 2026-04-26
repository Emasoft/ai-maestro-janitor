#!/usr/bin/env bash
# Task/PR mismatch detector — one-shot cross-check between Claude Code task
# entries and the current state of referenced GitHub PRs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/task-pr-mismatch-seen.txt"

# Resolve the team UUID under ~/.claude/tasks/ that belongs to the CURRENT
# project's most-recently-active session. Claude Code writes per-session logs
# to ~/.claude/projects/<project-slug>/<session-uuid>.jsonl, where
# <project-slug> is the project root with `/` rewritten to `-` (so a leading
# `/` becomes a leading `-`). The basename of the latest .jsonl in that dir
# matches the session UUID, which is also the directory name under
# ~/.claude/tasks/. Picking that dir scopes the detector to this project's
# tasks and avoids the cross-project bleed of `ls -t ~/.claude/tasks/`.
resolve_team_uuid() {
  local project_root project_slug session_root newest_jsonl
  project_root=$(resolve_project_root)
  project_slug=$(printf '%s' "$project_root" | sed 's|/|-|g')
  session_root="$HOME/.claude/projects/${project_slug}"
  [ -d "$session_root" ] || return 1
  newest_jsonl=$(ls -t "$session_root"/*.jsonl 2>/dev/null | head -1) || return 1
  [ -z "$newest_jsonl" ] && return 1
  basename "$newest_jsonl" .jsonl
}

main() {
  local repo="${CLAUDE_PLUGIN_OPTION_GITHUB_REPO:-}"
  if [ -z "$repo" ]; then
    repo=$(git remote get-url origin 2>/dev/null \
      | sed -E 's|.*github\.com[:/]([^/]+/[^/.]+)(\.git)?|\1|' | head -1) || true
  fi
  [ -z "$repo" ] && { log_line task-pr-mismatch "no github_repo — skipping"; return; }

  local team
  team=$(resolve_team_uuid) || { log_line task-pr-mismatch "no task directory under ~/.claude/tasks — skipping"; return; }
  local tasks_dir="$HOME/.claude/tasks/$team"
  [ -d "$tasks_dir" ] || { log_line task-pr-mismatch "team dir $tasks_dir missing — skipping"; return; }

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

main
exit 0
