#!/usr/bin/env bash
# Shared git helpers used by multiple detectors. Sourced — does not run
# anything on import.

# is_squash_merged <branch_ref> <base_ref>
#
# Returns 0 (true) if <branch_ref> appears to have been squash-merged into
# <base_ref>, else returns 1.
#
# Plain `git branch --merged` and `git merge-base --is-ancestor` only catch
# branches whose tip commit appears in <base_ref>'s history. Squash-merge
# does NOT preserve the branch tip — it lands a single new commit on the
# base whose tree captures the cumulative diff — so those checks miss it.
# Without this helper, every squash-merged branch would be permanently
# flagged as "unmerged" by worktree-janitor and pr-reconciler, producing
# persistent false-positive drift lines that erode user trust.
#
# Algorithm (canonical `git-delete-squashed` pattern):
#
#   1. Find the merge base mb = git merge-base <branch> <base>.
#   2. Construct a synthetic commit S with the BRANCH's tree, parented at
#      the merge base. S represents "what a squash of <branch> onto mb
#      would look like as a single commit".
#   3. Run `git cherry <base> S` — git compares S's patch-id against every
#      commit in <base>..mb. If a matching patch-id is found, cherry's
#      output line for S starts with '-'; otherwise '+'.
#
# This works even when <base> has additional commits AFTER the squash
# merge (the tree-equality approach in earlier drafts of this helper
# missed that case). It also produces false negatives only on heavy
# rebases that change patch-ids — which is the safe direction (we'd just
# fall back to the existing --is-ancestor check, no false flagging).
is_squash_merged() {
  local branch_ref="$1" base_ref="$2"
  [ -z "$branch_ref" ] && return 1
  [ -z "$base_ref" ] && return 1

  local branch_sha base_sha
  branch_sha=$(git rev-parse --verify --quiet "$branch_ref" 2>/dev/null) || return 1
  base_sha=$(git rev-parse --verify --quiet "$base_ref" 2>/dev/null) || return 1

  # Empty branch (tip equals base) is not "squash-merged" — it has nothing
  # to merge. Caller's existing --is-ancestor check handles this correctly,
  # but we add a guard to avoid producing a confusing positive here.
  [ "$branch_sha" = "$base_sha" ] && return 1

  # If branch is a regular ancestor, the caller's --is-ancestor check
  # already returned true and we wouldn't be invoked. Returning false here
  # is harmless — we trust the caller to have run --is-ancestor first.
  if git merge-base --is-ancestor "$branch_sha" "$base_sha" 2>/dev/null; then
    return 1
  fi

  local mb branch_tree synthetic
  mb=$(git merge-base "$branch_sha" "$base_sha" 2>/dev/null) || return 1
  [ -z "$mb" ] && return 1
  branch_tree=$(git rev-parse --verify --quiet "${branch_ref}^{tree}" 2>/dev/null) || return 1

  # `git commit-tree` writes a new commit object referencing branch_tree as
  # its tree and mb as its parent. The commit message is irrelevant; we
  # only need the SHA so cherry can compute its patch-id.
  synthetic=$(git commit-tree "$branch_tree" -p "$mb" -m "_janitor_squash_probe_" 2>/dev/null) || return 1
  [ -z "$synthetic" ] && return 1

  # `git cherry <upstream> <head>` prints one line per commit in
  # <upstream>..<head>, prefixed with '-' if the commit's patch-id matches
  # something on <upstream>, '+' if it's unique. We pass <base_ref> as
  # upstream and our synthetic commit as head, so a single line comes back.
  local cherry_out
  cherry_out=$(git cherry "$base_ref" "$synthetic" 2>/dev/null) || return 1

  case "$cherry_out" in
    "- "*) return 0 ;;   # synthetic patch already in base → squash-merged
    *)     return 1 ;;
  esac
}
