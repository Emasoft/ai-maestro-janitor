#!/usr/bin/env bash
# Stale task detector — nudges Claude Code about tasks that have been sitting
# in_progress or pending for too long without any update. Relies on the
# mtime of ~/.claude/tasks/<team>/<task>.json as the "last touched" signal,
# which Claude Code updates on every TaskUpdate call.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/stale-task-seen.txt"

IN_PROGRESS_THRESHOLD=$(coerce_int "${CLAUDE_PLUGIN_OPTION_STALE_IN_PROGRESS_THRESHOLD:-}" 7200)
PENDING_THRESHOLD=$(coerce_int "${CLAUDE_PLUGIN_OPTION_STALE_PENDING_THRESHOLD:-}" 86400)

resolve_team_uuid() {
  local tasks_root="$HOME/.claude/tasks"
  [ -d "$tasks_root" ] || return 1
  local newest
  newest=$(ls -t "$tasks_root" 2>/dev/null | head -1) || return 1
  [ -z "$newest" ] && return 1
  echo "$newest"
}

main() {
  local team
  team=$(resolve_team_uuid) || { log_line stale-task "no task directory — skipping"; return; }
  local tasks_dir="$HOME/.claude/tasks/$team"
  [ -d "$tasks_dir" ] || { log_line stale-task "team dir $tasks_dir missing — skipping"; return; }

  local project_dir
  project_dir=$(resolve_project_root)

  local now
  now=$(date +%s)

  shopt -s nullglob
  local t
  for t in "$tasks_dir"/*.json; do
    local id task_status subject threshold mtime age bucket task_project
    id=$(jq -r '.id // empty' "$t" 2>/dev/null) || continue
    [ -z "$id" ] && continue
    # `ls -t` on ~/.claude/tasks picks the most-recently-touched team, which
    # is usually — but not always — the current session's. Filter tasks whose
    # own `project_dir` field points somewhere else so we never nudge the user
    # about tasks from an unrelated project.
    task_project=$(jq -r '.project_dir // empty' "$t" 2>/dev/null)
    if [ -n "$task_project" ] && [ "$task_project" != "$project_dir" ]; then
      continue
    fi
    task_status=$(jq -r '.status // "pending"' "$t")
    subject=$(jq -r '.subject // ""' "$t")

    case "$task_status" in
      in_progress) threshold="$IN_PROGRESS_THRESHOLD" ;;
      pending)     threshold="$PENDING_THRESHOLD" ;;
      *) continue ;;
    esac

    mtime=$(file_mtime "$t")
    [ "$mtime" = "0" ] && continue
    age=$(( now - mtime ))
    [ "$age" -lt "$threshold" ] && continue

    bucket=$(( age / 86400 ))  # re-emit once per day the task stays stale
    local clean_subject="${subject:0:60}"
    local age_h=$(( age / 3600 ))

    emit_once "$SEEN" "task-${id}@${task_status}@d${bucket}" \
      "[stale-task] Task #${id} '${clean_subject}' has been ${task_status} for ~${age_h}h with no update. Resume, close, or defer it. Use TaskUpdate to record progress."
  done
  shopt -u nullglob

  rotate_log_if_big stale-task
}

main
exit 0
