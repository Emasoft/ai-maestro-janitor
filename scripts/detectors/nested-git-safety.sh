#!/usr/bin/env bash
# Nested-git-safety detector — finds nested `.git` directories that are NOT
# excluded by the parent's gitignore. An unignored nested `.git` is a real
# corruption hazard:
#   * `git add .` from the parent can stage the inner `.git/objects/...`
#     blobs as ordinary files, polluting the parent index.
#   * Cloning the parent recursively lands the inner repo as flat directories
#     (no submodule pointer), silently breaking the inner repo's history.
#
# The fix is mechanical: add the nested directory (or `*/.git` glob) to the
# parent's `.gitignore`. We surface the exact rule the user should add.
#
# Performance: depth-limited (`-mindepth 2 -maxdepth 4`) and prunes the
# .trashcan/, node_modules/, dist/, build/ subtrees so a large monorepo or a
# project with many vendored deps still finishes well under the 10s budget.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/nested-git-safety-seen.txt"

main() {
  local root
  root=$(resolve_project_root)
  cd "$root" 2>/dev/null || {
    log_line nested-git-safety "could not cd to project root '$root' — skipping"
    return
  }

  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line nested-git-safety "not a git repo — skipping"
    return
  }

  # Walk for nested .git entries (directories OR files — git submodule layout
  # uses a .git FILE that points into .git/modules/). Prune common heavyweight
  # vendored trees up-front for speed.
  while IFS= read -r -d '' nested_git; do
    # nested_git looks like ./vendor/lib/.git
    local rel="${nested_git#./}"
    local parent_dir="${rel%/.git}"
    [ -z "$parent_dir" ] && continue
    [ "$parent_dir" = "$rel" ] && continue   # safety: stripping didn't change anything

    # `git check-ignore -q` exits 0 when the path IS ignored, 1 when not, 128
    # on error. We want "not ignored" → emit nudge.
    if git check-ignore -q -- "$parent_dir" 2>/dev/null; then
      continue   # already gitignored, safe
    fi
    if git check-ignore -q -- "$rel" 2>/dev/null; then
      continue   # the .git itself is ignored, safe
    fi

    # Skip if parent_dir is actually tracked as a submodule — `git
    # submodule status -- <path>` exits 0 if known, non-zero otherwise.
    if git submodule status -- "$parent_dir" >/dev/null 2>&1; then
      continue
    fi

    local safe_parent
    safe_parent=$(printf '%q' "$parent_dir")

    emit_once "$SEEN" "nestedgit@${parent_dir}" \
      "[nested-git-safety] URGENT: nested git repo '${parent_dir}/' is NOT in .gitignore. A 'git add .' from the project root can stage the inner .git contents and corrupt both repos. Fix now: echo '/${parent_dir}/' >> .gitignore  (or convert to a submodule with: git submodule add <url> ${safe_parent})."
  done < <(find . \
              \( -path ./.git \
                 -o -path ./.trashcan \
                 -o -path ./node_modules \
                 -o -path ./dist \
                 -o -path ./build \
                 -o -path ./.venv \
                 -o -path ./venv \
              \) -prune \
              -o -mindepth 2 -maxdepth 4 -name .git -print0 \
              2>/dev/null)

  rotate_log_if_big nested-git-safety
}

main
exit 0
