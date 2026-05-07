#!/usr/bin/env bash
# Worktree janitor — one-shot drift detector.
# Scans `git worktree list --porcelain` and reports worktrees whose branch
# has been deleted or fully merged into origin/main.
#
# Two safety rules baked in (issue #5, plugin v0.3.12):
#
#   * Locked worktrees are NEVER reported. A `locked` line in the porcelain
#     output means an agent or user actively owns the worktree (e.g. an
#     in-flight `Agent({isolation: "worktree"})` run); a `--force` removal
#     suggestion at that moment would destroy unsaved work.
#
#   * The "merged" check requires the branch to be a STRICT ancestor of
#     origin/main, not just an ancestor. `git merge-base --is-ancestor A B`
#     returns true when A == B, so a freshly-spawned branch that hasn't
#     committed yet (still pointing at main HEAD) would otherwise be
#     misreported as "merged — prunable" and the suggested command would
#     destroy the agent's just-started work.
#
# We collect each porcelain block fully before deciding whether to emit,
# because `locked` can appear after `branch` in the block.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
# shellcheck source=../lib/git-utils.sh
source "$HERE/../lib/git-utils.sh"
init_state

SEEN="$STATE_DIR/worktree-janitor-seen.txt"

# Process one fully-parsed porcelain block. Args:
#   $1 path     — worktree path
#   $2 branch   — short branch name (no refs/heads/ prefix), empty for detached
#   $3 locked   — "1" if the block contained a `locked` line, else "0"
#   $4 main_sha — sha of origin/main, or empty if origin/main is unknown
process_block() {
  local path="$1" branch="$2" locked="$3" main_sha="$4"

  [ -z "$path" ] && return 0

  # Skip the primary worktree — that's our active checkout. Canonicalize both
  # paths with `pwd -P` so macOS /tmp vs /private/tmp symlink asymmetry
  # doesn't break the comparison.
  local canonical_current canonical_root
  canonical_current=$(cd "$path" 2>/dev/null && pwd -P) || canonical_current="$path"
  canonical_root=$(cd "$(resolve_project_root)" 2>/dev/null && pwd -P) || canonical_root=$(resolve_project_root)
  if [ "$canonical_current" = "$canonical_root" ]; then
    return 0
  fi

  # Locked worktree → in active use. Suggesting `git worktree remove --force`
  # here is the dangerous case the issue called out: a locked worktree means
  # an agent or user explicitly held the lock to protect work in progress,
  # and `--force` bypasses that lock.
  if [ "$locked" = "1" ]; then
    log_line worktree-janitor "skipping locked worktree '$path' (branch '${branch:-<detached>}')"
    return 0
  fi

  # Detached HEAD — no branch ref to reason about. Skip rather than guess.
  [ -z "$branch" ] && return 0

  # Shell-escape path and branch for the emitted remediation command. Worktree
  # paths can contain spaces and git's check-ref-format accepts branch names
  # with `;`, `&`, `|`, and `$(...)`. Unquoted use of those strings in the
  # printed command would create a paste-and-run shell injection vector.
  local safe_path safe_branch
  safe_path=$(printf '%q' "$path")
  safe_branch=$(printf '%q' "$branch")

  # Branch ref deleted out from under the worktree.
  if ! git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
    emit_once "$SEEN" "gone@${path}@${branch}" \
      "[worktree-janitor] worktree ${path} — branch '${branch}' no longer exists — prunable. Run: git worktree remove --force ${safe_path} && git worktree prune"
    return 0
  fi

  # Branch fully merged into origin/main. STRICT ancestry only — branch_sha
  # MUST differ from main_sha, otherwise we'd flag fresh just-spawned
  # branches that still point at main HEAD because no commits have landed
  # yet. `git merge-base --is-ancestor A B` is true when A == B, so without
  # the equality guard the "no work done yet" steady state is conflated
  # with "fully merged".
  #
  # Two additional safety gates run BEFORE we emit a removal recommendation
  # (issue #1376 — port from worktree-manager-main):
  #
  #   * uncommitted_changes — the worktree has dirty working-tree state.
  #     `git worktree remove --force` would discard that work without
  #     warning. Skip the recommendation; let dirty-tree surface the dirt.
  #
  #   * unpushed_commits — the branch has commits past its upstream that
  #     haven't been pushed. Even if the branch is "merged" into main
  #     locally, the unpushed commits would be lost on remove --force.
  #
  # Either condition is a hard skip (logged but no nudge). The /janitor-pause
  # / /janitor-resume mechanism doesn't help here — the user needs to commit
  # and push, not silence the detector.
  if [ -n "$main_sha" ]; then
    local branch_sha
    branch_sha=$(git rev-parse "refs/heads/$branch" 2>/dev/null) || branch_sha=""
    [ -z "$branch_sha" ] && return 0
    [ "$branch_sha" = "$main_sha" ] && return 0

    local merged="" merge_kind=""
    if git merge-base --is-ancestor "$branch_sha" "$main_sha" 2>/dev/null; then
      merged=1; merge_kind="merged"
    elif is_squash_merged "refs/heads/$branch" "$main_sha"; then
      merged=1; merge_kind="squash-merged"
    fi

    if [ -n "$merged" ]; then
      # Safety gate 1: uncommitted changes inside the worktree.
      local porcelain
      porcelain=$(git -C "$path" status --porcelain 2>/dev/null) || porcelain=""
      if [ -n "$porcelain" ]; then
        log_line worktree-janitor "skipping ${merge_kind} worktree '$path' — has uncommitted changes"
        return 0
      fi

      # Safety gate 2: unpushed commits. We compare branch tip against its
      # configured upstream (if any). If no upstream is configured, we fall
      # back to comparing against origin/<branch>; if that also doesn't
      # exist, we conservatively skip (better a false silent than a data
      # loss). `git rev-list --count upstream..HEAD` counts the unpushed.
      local upstream unpushed=""
      upstream=$(git -C "$path" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) \
        || upstream=""
      if [ -z "$upstream" ]; then
        if git show-ref --verify --quiet "refs/remotes/origin/$branch" 2>/dev/null; then
          upstream="origin/$branch"
        fi
      fi
      if [ -n "$upstream" ]; then
        unpushed=$(git -C "$path" rev-list --count "${upstream}..HEAD" 2>/dev/null) || unpushed=""
      else
        # No upstream and no origin/<branch>: skip removal nudge entirely.
        log_line worktree-janitor "skipping ${merge_kind} worktree '$path' — branch '${branch}' has no upstream tracking and no origin/<branch> — cannot verify all commits are safe"
        return 0
      fi
      if [ -n "$unpushed" ] && [ "$unpushed" != "0" ]; then
        log_line worktree-janitor "skipping ${merge_kind} worktree '$path' — has ${unpushed} unpushed commit(s) past ${upstream}"
        return 0
      fi

      emit_once "$SEEN" "${merge_kind}@${path}@${branch}" \
        "[worktree-janitor] worktree ${path} — branch '${branch}' is ${merge_kind} into main — prunable. Run: git worktree remove --force ${safe_path} && git update-ref -d refs/heads/${safe_branch} && git worktree prune"
    fi
  fi
}

main() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line worktree-janitor "not a git repo — skipping"
    return
  }

  local main_sha
  main_sha=$(git rev-parse origin/main 2>/dev/null) || main_sha=""

  # Parse porcelain format: blocks separated by blank lines, each carrying
  # `worktree <path>`, optionally `HEAD <sha>`, `branch <ref>` or `detached`,
  # plus optional `bare`, `locked [reason]`, `prunable` lines. The order of
  # `branch` and `locked` is not guaranteed, so we accumulate the full block
  # before calling process_block.
  local current_path="" current_branch="" current_locked=0
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        # Flush any in-flight block (defensive — porcelain normally separates
        # blocks with blank lines, but a missing trailer shouldn't lose data).
        process_block "$current_path" "$current_branch" "$current_locked" "$main_sha"
        current_path="${line#worktree }"
        current_branch=""
        current_locked=0
        ;;
      "branch "*)
        current_branch="${line#branch refs/heads/}"
        ;;
      "locked"|"locked "*)
        current_locked=1
        ;;
      "")
        process_block "$current_path" "$current_branch" "$current_locked" "$main_sha"
        current_path=""
        current_branch=""
        current_locked=0
        ;;
    esac
  done < <(git worktree list --porcelain 2>/dev/null || true)

  # Catch a trailing block when porcelain output doesn't end with blank line.
  process_block "$current_path" "$current_branch" "$current_locked" "$main_sha"

  rotate_log_if_big worktree-janitor
}

main
exit 0
