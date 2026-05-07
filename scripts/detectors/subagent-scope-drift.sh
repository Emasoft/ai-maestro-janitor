#!/usr/bin/env bash
# Subagent-scope drift — flags `.claude/agents/*.md` files whose tracking
# status is ambiguous. Per the docs (settings#what-uses-scopes):
#
#   * Subagents have NO formal local scope — Claude Code reads agents from
#     `~/.claude/agents/` (user) and `<root>/.claude/agents/` (project).
#     There is no `<root>/.claude/agents.local/` or similar.
#
#   * Functionally, the user can keep an agent personal by gitignoring it
#     under `.claude/agents/`; it still loads at session start, but it
#     never reaches a teammate's checkout.
#
# So the only legitimate states for a project-level agent file are:
#   * git-tracked  → "project scope" — shared with the team
#   * gitignored   → "informally local" — personal to this checkout
#
# Anything else (file on disk, neither tracked nor ignored) is the
# tracking-ambiguity bug: agents disappear from teammates' checkouts
# without warning, OR personal agents get committed accidentally.
#
# The detector batches: rather than emit one drift line per ambiguous
# file (which could be noisy on first arming of a project with many
# agents), we collect ALL ambiguous files and emit a single summary
# line listing the first 5 + a count. Each summary is dedup'd by the
# concatenation of file names so re-running is silent until the set
# changes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
# shellcheck source=../lib/git-utils.sh
source "$HERE/../lib/git-utils.sh"
init_state

SEEN="$STATE_DIR/subagent-scope-drift-seen.txt"

main() {
  local root agents_dir
  root=$(resolve_project_root)
  agents_dir="$root/.claude/agents"
  [ -d "$agents_dir" ] || return 0

  # Find every .md file under .claude/agents/ — newer Claude Code allows
  # nested subdirs (categories), so we recurse. NUL-separated read so
  # filenames with whitespace survive.
  local ambiguous_list=""
  local count=0

  while IFS= read -r -d '' agent_path; do
    # Convert to project-relative for the helper.
    local rel="${agent_path#"$root"/}"
    local status
    status=$(scope_tracking_status "$rel")
    case "$status" in
      ambiguous)
        ambiguous_list="${ambiguous_list}${rel}"$'\n'
        count=$((count + 1))
        ;;
    esac
  done < <(find "$agents_dir" -type f -name '*.md' -print0 2>/dev/null)

  [ "$count" -eq 0 ] && return 0

  # Build summary: first 5 lines indented, plus a count line if more.
  local sample
  sample=$(printf '%s' "$ambiguous_list" | head -5 | sed 's/^/  - /')
  if [ "$count" -gt 5 ]; then
    sample="${sample}
  - …and $(( count - 5 )) more"
  fi

  # Dedup key is a hash of the full sorted file list — re-emits only when
  # the SET of ambiguous files changes (a single new agent appearing or
  # disappearing rotates the key).
  local fp
  fp=$(printf '%s' "$ambiguous_list" | sort | cksum | awk '{print $1}')

  emit_once "$SEEN" "ambig-set@${fp}" \
    "[subagent-scope-drift] ${count} agent file(s) under .claude/agents/ are neither git-tracked nor gitignored. Each must be either: 'git add' (project scope, shared with team) OR added to .gitignore (informally local, personal to this checkout). Subagents have no formal local scope — the git status IS the scope signal. Affected:
${sample}"

  rotate_log_if_big subagent-scope-drift
}

main
exit 0
