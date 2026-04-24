#!/usr/bin/env bash
# Worktree janitor — one-shot drift detector.
# Scans `git worktree list --porcelain` and reports worktrees whose branch
# has been deleted or merged into origin/main.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/worktree-janitor-seen.txt"

main() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line worktree-janitor "not a git repo — skipping"
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
        # Canonicalize both paths with `pwd -P` so macOS /tmp vs /private/tmp
        # symlink asymmetry doesn't break the comparison.
        local canonical_current canonical_root
        canonical_current=$(cd "$current_path" 2>/dev/null && pwd -P) || canonical_current="$current_path"
        canonical_root=$(cd "$(resolve_project_root)" 2>/dev/null && pwd -P) || canonical_root=$(resolve_project_root)
        if [ "$canonical_current" = "$canonical_root" ]; then
          continue
        fi

        # Shell-escape path and branch for the emitted remediation command.
        # Worktree paths can contain spaces (macOS: "My Project") and git's
        # check-ref-format accepts branch names containing `;`, `&`, `|`, and
        # `$(...)`. Unquoted use of those strings in the suggested command
        # would create a paste-and-run shell injection vector.
        local safe_path safe_branch
        safe_path=$(printf '%q' "$current_path")
        safe_branch=$(printf '%q' "$current_branch")

        if ! git show-ref --verify --quiet "refs/heads/$current_branch" 2>/dev/null; then
          emit_once "$SEEN" "gone@${current_path}@${current_branch}" \
            "[worktree-janitor] worktree ${current_path} — branch '${current_branch}' no longer exists — prunable. Run: git worktree remove --force ${safe_path} && git worktree prune"
        fi

        if [ -n "$main_sha" ]; then
          local branch_sha
          branch_sha=$(git rev-parse "refs/heads/$current_branch" 2>/dev/null) || branch_sha=""
          if [ -n "$branch_sha" ] && git merge-base --is-ancestor "$branch_sha" "$main_sha" 2>/dev/null; then
            emit_once "$SEEN" "merged@${current_path}@${current_branch}" \
              "[worktree-janitor] worktree ${current_path} — branch '${current_branch}' is merged into main — prunable. Run: git worktree remove --force ${safe_path} && git update-ref -d refs/heads/${safe_branch} && git worktree prune"
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

main
exit 0
