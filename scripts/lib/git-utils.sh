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
#   3. Run `git cherry <base> S` — git lists each commit reachable from S
#      but not from <base> (so just S itself) and prefixes each line with
#      '-' if a commit with the SAME patch-id already exists in <base>'s
#      history, '+' otherwise. A '-' means S's diff is already in <base>,
#      i.e. <branch> was squash-merged.
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

# scope_tracking_status <relative-path-from-project-root>
#
# Probes the git tracking status of a file inside the project. Prints
# exactly one of these tokens to stdout (always exits 0):
#
#   tracked     — file is in `git ls-files`
#   gitignored  — file is matched by a `.gitignore` rule
#   ambiguous   — file exists on disk but is neither tracked nor ignored
#                 (the case the janitor's tracking-ambiguity detectors flag)
#   missing     — file does not exist on disk (no nudge needed)
#   no-repo     — project root is not a git repo (no tracking signal)
#
# This is the primitive shared by every "scope drift" detector
# (mcp-config-drift, settings-scope-drift, subagent-scope-drift,
# claude-md-scope-drift). Each detector applies its own policy on top:
#
#   * `.mcp.json` and subagent files: either tracked OR gitignored is
#     fine — only `ambiguous` is a problem.
#   * `.claude/settings.json` / `CLAUDE.md`: SHOULD be tracked. Flag
#     `gitignored` AND `ambiguous`.
#   * `.claude/settings.local.json` / `CLAUDE.local.md`: SHOULD be
#     gitignored. Flag `tracked` AND `ambiguous`.
#
# Implementation note: the `cd` happens in a subshell so the caller's
# cwd is never disturbed. This matters because the heartbeat fires from
# whatever directory dispatch.sh was launched in, and detectors are
# expected to be cwd-agnostic.
scope_tracking_status() {
  local rel="$1"
  (
    local root
    root=$(resolve_project_root) 2>/dev/null
    cd "$root" 2>/dev/null || { printf 'no-repo'; exit 0; }
    git rev-parse --git-dir >/dev/null 2>&1 || { printf 'no-repo'; exit 0; }
    # `-e` covers files, dirs, and symlinks — we don't constrain to
    # regular files because subagent .md files are regular but a future
    # caller might pass a directory (e.g. `.claude/agents/`).
    [ -e "$rel" ] || { printf 'missing'; exit 0; }
    if git ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
      printf 'tracked'
    elif git check-ignore -q -- "$rel" 2>/dev/null; then
      printf 'gitignored'
    else
      printf 'ambiguous'
    fi
  )
}
