#!/usr/bin/env bash
set -euo pipefail
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/state.sh"
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/dedupe.sh"
init_state

ONE_SHOT=0
[ "${1:-}" = "--one-shot" ] && ONE_SHOT=1

INTERVAL="${CLAUDE_PLUGIN_OPTION_WORKTREE_JANITOR_INTERVAL:-900}"
SEEN="$STATE_DIR/worktree-janitor-seen.txt"

run_once() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line worktree-janitor "not a git repo — skipping tick"
    return
  }

  local main_sha
  main_sha=$(git rev-parse origin/main 2>/dev/null) || main_sha=""

  # Parse porcelain format: blocks separated by blank lines, each with
  # worktree <path> / HEAD <sha> / branch <ref>. Bare/detached worktrees are
  # ignored (no branch line).
  local current_path=""
  local current_branch=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) current_path="${line#worktree }" ;;
      "branch "*)
        current_branch="${line#branch refs/heads/}"
        # Skip the primary worktree — that's our active working dir.
        if [ "$current_path" = "$(resolve_project_root)" ]; then
          continue
        fi

        if ! git show-ref --verify --quiet "refs/heads/$current_branch" 2>/dev/null; then
          emit_once "$SEEN" "gone@${current_path}@${current_branch}" \
            "[worktree-janitor] worktree ${current_path} — branch '${current_branch}' no longer exists — prunable."
        fi

        if [ -n "$main_sha" ]; then
          local branch_sha
          branch_sha=$(git rev-parse "refs/heads/$current_branch" 2>/dev/null) || branch_sha=""
          if [ -n "$branch_sha" ] && git merge-base --is-ancestor "$branch_sha" "$main_sha" 2>/dev/null; then
            emit_once "$SEEN" "merged@${current_path}@${current_branch}" \
              "[worktree-janitor] worktree ${current_path} — branch '${current_branch}' is merged into main — prunable."
          fi
        fi
        ;;
      "")
        current_path=""
        current_branch=""
        ;;
    esac
  done < <(git worktree list --porcelain 2>/dev/null || true)

  rotate_log_if_big worktree-janitor
}

if [ "$ONE_SHOT" = "1" ]; then
  run_once
  exit 0
fi

while true; do
  run_once
  sleep "$INTERVAL"
done
