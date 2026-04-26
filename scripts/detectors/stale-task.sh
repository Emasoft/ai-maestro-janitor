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
  local team
  team=$(resolve_team_uuid) || { log_line stale-task "no task directory — skipping"; return; }
  local tasks_dir="$HOME/.claude/tasks/$team"
  [ -d "$tasks_dir" ] || { log_line stale-task "team dir $tasks_dir missing — skipping"; return; }

  local now
  now=$(date +%s)

  shopt -s nullglob
  local t
  for t in "$tasks_dir"/*.json; do
    local id task_status subject threshold mtime age bucket
    id=$(jq -r '.id // empty' "$t" 2>/dev/null) || continue
    [ -z "$id" ] && continue
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
