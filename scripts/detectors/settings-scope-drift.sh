#!/usr/bin/env bash
# Settings-scope drift — audits the tracking status of the project's
# Claude Code settings files against the documented scope policy:
#
#   * `.claude/settings.json`        SHOULD be git-tracked. It carries
#                                    project-scope settings (permissions,
#                                    hooks, MCP allowlists, etc.) that
#                                    every collaborator needs. Gitignoring
#                                    it silently breaks teammates' access
#                                    to those settings.
#
#   * `.claude/settings.local.json`  SHOULD be gitignored. It carries
#                                    local-scope personal overrides
#                                    (autoMode opt-ins, personal hooks,
#                                    MCP server allow/deny choices). If
#                                    tracked, it leaks personal config —
#                                    and worse, can include
#                                    `enabledPlugins` overrides that
#                                    teammates don't want to inherit.
#
# Three drift classes per file:
#   * wrong-direction-tracked:    settings.local.json IS tracked   → fix
#   * wrong-direction-gitignored: settings.json IS gitignored      → fix
#   * ambiguous (neither/nor):    file exists but git status unset → decide
#
# All checks reuse `scope_tracking_status` from scripts/lib/git-utils.sh
# so the per-detector logic stays declarative.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
# shellcheck source=../lib/git-utils.sh
source "$HERE/../lib/git-utils.sh"
init_state

SEEN="$STATE_DIR/settings-scope-drift-seen.txt"

main() {
  # `.claude/settings.json` — should be tracked.
  local proj_status
  proj_status=$(scope_tracking_status ".claude/settings.json")
  case "$proj_status" in
    tracked|missing|no-repo) ;;
    gitignored)
      emit_once "$SEEN" "settings-tracked-but-ignored@.claude/settings.json" \
        "[settings-scope-drift] .claude/settings.json is gitignored — its purpose is project-scope (team-shared) settings. Teammates' checkouts won't see your hooks, permissions, or MCP allowlists. Either rename to .claude/settings.local.json, OR remove the matching .gitignore rule and 'git add .claude/settings.json'."
      ;;
    ambiguous)
      emit_once "$SEEN" "ambig@.claude/settings.json" \
        "[settings-scope-drift] .claude/settings.json is neither git-tracked nor gitignored — its scope is ambiguous. For team-shared settings: 'git add .claude/settings.json'. For personal: rename to .claude/settings.local.json AND ignore that name in .gitignore."
      ;;
  esac

  # `.claude/settings.local.json` — should be gitignored.
  local local_status
  local_status=$(scope_tracking_status ".claude/settings.local.json")
  case "$local_status" in
    gitignored|missing|no-repo) ;;
    tracked)
      emit_once "$SEEN" "local-leaked@.claude/settings.local.json" \
        "[settings-scope-drift] .claude/settings.local.json is git-tracked — its purpose is personal local-scope overrides (autoMode flags, personal hooks, enabledPlugins overrides). Tracking it leaks your config to the team. Run: git rm --cached .claude/settings.local.json && grep -qxF '/.claude/settings.local.json' .gitignore || echo '/.claude/settings.local.json' >> .gitignore"
      ;;
    ambiguous)
      emit_once "$SEEN" "ambig@.claude/settings.local.json" \
        "[settings-scope-drift] .claude/settings.local.json exists but is neither tracked nor gitignored. It SHOULD be gitignored (it's personal config). Run: echo '/.claude/settings.local.json' >> .gitignore"
      ;;
  esac

  rotate_log_if_big settings-scope-drift
}

main
exit 0
