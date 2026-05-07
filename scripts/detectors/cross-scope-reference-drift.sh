#!/usr/bin/env bash
# Cross-scope reference drift — catches the silent-clone-break bug:
#
#   A tracked agent (or skill, or CLAUDE.md, or command) references a
#   slash-command or Skill() target whose definition lives in a project
#   file that is GITIGNORED or has AMBIGUOUS tracking status. On the
#   author's machine everything works (the target is on disk). On a
#   teammate's clone — or in CI — the source file ships but the target
#   doesn't, so every invocation of the reference dangles.
#
# Concrete example from the user that motivated this detector:
#
#   .claude/agents/reviewer.md   (tracked) — body says "use /lint-helper"
#   .claude/skills/lint-helper/  (gitignored)
#
#   git push → reviewer.md goes to GitHub. Teammate clones → lint-helper/
#   is not in the repo. Reviewer agent fires `/lint-helper` → silent
#   failure (skill not found, falls through to default behavior, no
#   loud error). The bug is invisible until someone reads the agent
#   body and notices the reference doesn't work.
#
# Scope of the v1 detector (kept small, high-signal):
#
#   SOURCES we scan (only tracked files in scope-anchored locations):
#     * .claude/agents/**/*.md
#     * .claude/skills/**/SKILL.md
#     * .claude/commands/**/*.md     (Claude Code custom commands)
#     * CLAUDE.md  and  .claude/CLAUDE.md
#
#   REFERENCES we extract:
#     * `/<name>`  — slash-command shape (skills, commands, built-ins).
#                    Loosely matched; non-local names are dropped during
#                    resolution so URLs and built-ins (/help, /clear)
#                    produce no nudge.
#     * `Skill('<name>')` / `Skill("<name>")` — explicit invocation.
#
#   TARGETS we resolve a reference to (in this priority order):
#     * .claude/skills/<name>/SKILL.md
#     * .claude/skills/<name>/Skill.md
#     * .claude/agents/<name>.md
#     * .claude/commands/<name>.md
#
#   DRIFT we emit:
#     * Source is tracked AND target is gitignored OR ambiguous → flag.
#     * Source is tracked AND target is tracked → fine.
#     * Source is tracked AND target doesn't exist locally → silently
#       skipped (could be a plugin command, a built-in, or a typo —
#       different drift class, not our concern here).
#
# Out of scope for v1 (potential follow-ups):
#   * User-scope references (~/.claude/skills/<name>/). Detecting these
#     requires distinguishing "user skill we'd lose on clone" from
#     "plugin skill the team also has installed", which is hard.
#   * Plugin-provided skills/agents the team's settings disagree on.
#   * Plain-prose mentions ("see the foo skill") — too lossy to detect.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
# shellcheck source=../lib/git-utils.sh
source "$HERE/../lib/git-utils.sh"
init_state

SEEN="$STATE_DIR/cross-scope-reference-drift-seen.txt"

# Pull slash-command and Skill() references from a markdown file. Always
# returns 0 (the `|| true` on the outer block handles the zero-match
# case under set -o pipefail; same gotcha as in mcp-config-drift).
extract_refs() {
  local file="$1"
  {
    # Slash-command shape: `/<lowercase-ident>` of length ≥3 (avoids
    # false matches on `/a` and `/x` in URLs/paths). Tolerates leading
    # garbage (e.g. backtick or whitespace) by capturing only the
    # `/<name>` substring.
    grep -hoE '/[a-z][a-z0-9-]{2,}' "$file" 2>/dev/null \
      | sed 's|^/||'
    # Explicit Skill('<name>') / Skill("<name>") invocations. The
    # outer single quotes around the regex contain a Bash-escaped
    # literal single quote (`'"'"'`) inside a character class so jq /
    # bash both pass it through to grep correctly.
    grep -hoE 'Skill\(["'"'"'][a-zA-Z][a-zA-Z0-9_-]+["'"'"']\)' "$file" 2>/dev/null \
      | sed -E 's/.*\(["'"'"']([^"'"'"']+)["'"'"']\).*/\1/'
  } 2>/dev/null | sort -u | grep -v '^$' || true
}

# Resolve a reference name to a project-local file. Echoes the relative
# path on first hit, else nothing. Returns 0 on hit, 1 on miss.
resolve_ref() {
  local name="$1" root="$2"
  local cand
  for cand in \
    ".claude/skills/$name/SKILL.md" \
    ".claude/skills/$name/Skill.md" \
    ".claude/agents/$name.md" \
    ".claude/commands/$name.md"; do
    if [ -f "$root/$cand" ]; then
      printf '%s\n' "$cand"
      return 0
    fi
  done
  return 1
}

main() {
  local root
  root=$(resolve_project_root)
  cd "$root" 2>/dev/null || return 0
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line cross-scope-reference-drift "not a git repo — skipping"
    return
  }

  # Collect tracked sources via `git ls-files`. Restricting to *.md
  # avoids scanning binary or unrelated files. Multiple paths are
  # accepted by ls-files; non-existent paths are silently dropped.
  local tracked_sources
  tracked_sources=$(git ls-files -- \
      ':(glob).claude/agents/**/*.md' \
      ':(glob).claude/skills/**/SKILL.md' \
      ':(glob).claude/skills/**/Skill.md' \
      ':(glob).claude/commands/**/*.md' \
      'CLAUDE.md' \
      '.claude/CLAUDE.md' \
      2>/dev/null \
      || true)
  [ -z "$tracked_sources" ] && return 0

  # Process each tracked source. We dedup the (source, target) pair so a
  # single source referencing the same target multiple times produces ONE
  # drift line, but two different sources referencing the same target
  # both fire (each owner needs to know).
  while IFS= read -r src; do
    [ -z "$src" ] && continue
    [ -f "$src" ] || continue

    local refs
    refs=$(extract_refs "$src")
    [ -z "$refs" ] && continue

    while IFS= read -r ref; do
      [ -z "$ref" ] && continue

      local target_rel
      target_rel=$(resolve_ref "$ref" "$root") || continue

      # `scope_tracking_status` is the shared primitive in
      # scripts/lib/git-utils.sh. The same helper drives the four
      # scope-drift detectors and now this one.
      local target_status
      target_status=$(scope_tracking_status "$target_rel")
      case "$target_status" in
        tracked|missing|no-repo) ;;   # nothing to flag
        gitignored|ambiguous)
          local safe_src safe_target
          safe_src=$(sanitize_for_drift_line "$src")
          safe_target=$(sanitize_for_drift_line "$target_rel")
          # Dedup key: stable hash of (src, target) so swapping the
          # tracking status of either re-emits naturally.
          local fp
          fp=$(printf '%s\t%s\t%s' "$src" "$target_rel" "$target_status" \
                 | cksum | awk '{print $1}')
          emit_once "$SEEN" "xref@${fp}" \
            "[cross-scope-reference-drift] '${safe_src}' is git-tracked but references '/${ref}' → '${safe_target}' (${target_status}, not in repo). On clone or push the source ships without its target — the reference will dangle. Fix: 'git add ${safe_target}' to ship the target with the team, OR 'git rm --cached ${safe_src}' to keep the source private too."
          ;;
      esac
    done <<< "$refs"
  done <<< "$tracked_sources"

  rotate_log_if_big cross-scope-reference-drift
}

main
exit 0
