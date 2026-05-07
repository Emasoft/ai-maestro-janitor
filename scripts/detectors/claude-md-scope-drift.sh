#!/usr/bin/env bash
# CLAUDE.md scope drift — audits the project memory files for
# tracking-status correctness:
#
#   * `CLAUDE.md`            (project root, primary location)
#                            SHOULD be tracked. Project memory is
#                            inherently shared with the team.
#   * `.claude/CLAUDE.md`    (alternate project location, equally valid)
#                            SHOULD be tracked, same reasoning.
#   * `CLAUDE.local.md`      Personal memory overrides. SHOULD be
#                            gitignored. Tracking it leaks personal
#                            notes/preferences to the team.
#
# Note that Claude Code reads BOTH `CLAUDE.md` and `.claude/CLAUDE.md` if
# both exist — they're not mutually exclusive. We audit each independently.
#
# Three drift classes per file:
#   * wrong-direction-tracked:    CLAUDE.local.md IS tracked       → fix
#   * wrong-direction-gitignored: CLAUDE.md is gitignored          → fix
#   * ambiguous (neither):        file exists, git status unset    → decide
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
# shellcheck source=../lib/git-utils.sh
source "$HERE/../lib/git-utils.sh"
init_state

SEEN="$STATE_DIR/claude-md-scope-drift-seen.txt"

# Helper: audit one file that SHOULD be tracked.
audit_should_be_tracked() {
  local rel="$1"
  local status
  status=$(scope_tracking_status "$rel")
  case "$status" in
    tracked|missing|no-repo) ;;
    gitignored)
      emit_once "$SEEN" "tracked-but-ignored@${rel}" \
        "[claude-md-scope-drift] ${rel} is gitignored — its purpose is project memory, shared with the team. Teammates won't see it. Either remove the matching .gitignore rule and 'git add ${rel}', OR rename to CLAUDE.local.md if you intended it to be personal."
      ;;
    ambiguous)
      emit_once "$SEEN" "ambig@${rel}" \
        "[claude-md-scope-drift] ${rel} is neither git-tracked nor gitignored. For team-shared project memory: 'git add ${rel}'. For personal context: rename to CLAUDE.local.md and add '/CLAUDE.local.md' to .gitignore."
      ;;
  esac
}

# Helper: audit one file that SHOULD be gitignored.
audit_should_be_gitignored() {
  local rel="$1"
  local status
  status=$(scope_tracking_status "$rel")
  case "$status" in
    gitignored|missing|no-repo) ;;
    tracked)
      emit_once "$SEEN" "local-leaked@${rel}" \
        "[claude-md-scope-drift] ${rel} is git-tracked — its purpose is personal memory overrides, not team-shared content. Tracking it leaks personal notes to the team. Run: git rm --cached ${rel} && grep -qxF '/${rel}' .gitignore || echo '/${rel}' >> .gitignore"
      ;;
    ambiguous)
      emit_once "$SEEN" "ambig@${rel}" \
        "[claude-md-scope-drift] ${rel} exists but is neither tracked nor gitignored. It SHOULD be gitignored (it's personal memory). Run: echo '/${rel}' >> .gitignore"
      ;;
  esac
}

main() {
  audit_should_be_tracked     "CLAUDE.md"
  audit_should_be_tracked     ".claude/CLAUDE.md"
  audit_should_be_gitignored  "CLAUDE.local.md"

  rotate_log_if_big claude-md-scope-drift
}

main
exit 0
