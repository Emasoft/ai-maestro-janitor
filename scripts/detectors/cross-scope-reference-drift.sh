#!/usr/bin/env bash
# Cross-scope reference drift — enforces SCOPE PARITY between a source
# (agent/skill/command/CLAUDE.md) and the targets it references. Per the
# project-wide rule:
#
#   "If a skill or agent under <proj>/.claude/{skills,agents}/ references
#    a skill or agent under <proj>/.claude/{skills,agents}/, then BOTH
#    must be either git-tracked (project scope) OR gitignored (local
#    scope). They must travel together as one bundle."
#
# Two classes of drift fall out of this rule, both flagged here:
#
#   1. SILENT-CLONE-BREAK — tracked source → gitignored or ambiguous
#      target. The source ships to the repo on push; the target
#      doesn't. Teammates' clones see the source reference a target
#      that isn't there, the slash-command silently no-ops, and the
#      bug is invisible in code review.
#
#      Example:
#        .claude/agents/reviewer.md   (tracked)  — "use /lint-helper"
#        .claude/skills/lint-helper/  (gitignored)
#        → reviewer.md ships, lint-helper/ doesn't, reviewer breaks.
#
#   2. SCOPE-MISMATCH — gitignored source → tracked target. The
#      personal/local source has a hidden dependency on a team-shared
#      target. Locally everything works; if the team later renames or
#      removes the target, the local source silently breaks (with no
#      visibility for the team because they never see the source).
#      Either elevate the source to project scope ('git add'), or
#      copy the target into a local-scope skill so the dependency is
#      contained.
#
# Sources scanned (regardless of their own tracking status — we need to
# see local sources to flag class 2):
#   * .claude/agents/**/*.md
#   * .claude/skills/**/SKILL.md  and  Skill.md
#   * .claude/commands/**/*.md
#   * CLAUDE.md  and  .claude/CLAUDE.md
#
# References we extract:
#   * `/<name>`           — slash-command (skill, command, or built-in)
#   * `Skill('<name>')` / `Skill("<name>")` — explicit invocation
#
# Targets we resolve to (in priority order):
#   * .claude/skills/<name>/SKILL.md
#   * .claude/skills/<name>/Skill.md
#   * .claude/agents/<name>.md
#   * .claude/commands/<name>.md
#
# Status pair → verdict (where status ∈ {tracked, gitignored, ambiguous,
# missing, no-repo}):
#
#   tracked/tracked         OK — both ship together
#   gitignored/gitignored   OK — both stay personal
#   tracked/gitignored      → silent-clone-break (class 1)
#   tracked/ambiguous       → silent-clone-break (target won't ship)
#   gitignored/tracked      → scope-mismatch    (class 2)
#   ambiguous/anything      → handled by subagent-scope-drift /
#                             claude-md-scope-drift (source itself
#                             needs a tracking decision first)
#   anything/missing        → reference is dangling (different drift
#                             class — not our concern here)
#   anything/no-repo        → not a git repo (no scope signal)
#
# Out of scope (good follow-ups):
#   * User-scope references (~/.claude/skills/<name>/) — needs a way
#     to distinguish "user skill we'd lose on clone" from "plugin
#     skill the team also has installed".
#   * Plain-prose mentions ("see the foo skill") — too lossy.
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

  # Collect ALL .md sources in scope-anchored locations — tracked,
  # gitignored, and ambiguous. We need the gitignored ones to detect
  # class-2 drift (gitignored source → tracked target). `find -print0`
  # so paths with whitespace survive, then read into a NUL-delimited
  # while loop.
  local sources_buf="" src
  while IFS= read -r -d '' src; do
    sources_buf="${sources_buf}${src}"$'\n'
  done < <(
    {
      [ -d .claude/agents ]   && find .claude/agents   -type f -name '*.md' -print0
      [ -d .claude/skills ]   && find .claude/skills   -type f \( -name 'SKILL.md' -o -name 'Skill.md' \) -print0
      [ -d .claude/commands ] && find .claude/commands -type f -name '*.md' -print0
      [ -f CLAUDE.md ]         && printf 'CLAUDE.md\0'
      [ -f .claude/CLAUDE.md ] && printf '.claude/CLAUDE.md\0'
    } 2>/dev/null
  )

  [ -z "$sources_buf" ] && return 0

  # Process each source. The dedup key is (src, target, src_status,
  # target_status) so a status flip on either side rotates the key
  # naturally and re-emits with the new advice.
  while IFS= read -r src; do
    [ -z "$src" ] && continue
    [ -f "$src" ] || continue

    local src_status
    src_status=$(scope_tracking_status "$src")
    # Source must have a clear scope to participate in the parity
    # check. ambiguous sources are flagged by subagent-scope-drift
    # (or claude-md-scope-drift / settings-scope-drift) — once the
    # user resolves them to tracked or gitignored, this detector
    # picks up any resulting parity violation on the next fire.
    case "$src_status" in
      tracked|gitignored) ;;
      *) continue ;;
    esac

    local refs
    refs=$(extract_refs "$src")
    [ -z "$refs" ] && continue

    while IFS= read -r ref; do
      [ -z "$ref" ] && continue

      local target_rel
      target_rel=$(resolve_ref "$ref" "$root") || continue

      local target_status
      target_status=$(scope_tracking_status "$target_rel")

      local pair="${src_status}/${target_status}"
      local drift_class="" drift_msg=""

      case "$pair" in
        tracked/tracked|gitignored/gitignored)
          continue
          ;;
        tracked/gitignored|tracked/ambiguous)
          drift_class="silent-clone-break"
          ;;
        gitignored/tracked)
          drift_class="scope-mismatch"
          ;;
        *)
          # ambiguous target with gitignored source, or unexpected
          # combination — let the dedicated scope-drift detector
          # surface the underlying ambiguity. Not our concern here.
          continue
          ;;
      esac

      local safe_src safe_target
      safe_src=$(sanitize_for_drift_line "$src")
      safe_target=$(sanitize_for_drift_line "$target_rel")

      case "$drift_class" in
        silent-clone-break)
          drift_msg="[cross-scope-reference-drift] '${safe_src}' is git-tracked but references '/${ref}' → '${safe_target}' (${target_status}, not in repo). On clone or push the source ships without its target — the reference will dangle in every teammate's checkout and in CI. Fix: 'git add ${safe_target}' to ship the target with the team, OR 'git rm --cached ${safe_src}' to keep both files private."
          ;;
        scope-mismatch)
          drift_msg="[cross-scope-reference-drift] '${safe_src}' is gitignored (local scope) but references '/${ref}' → '${safe_target}' (git-tracked, project scope). The reference works locally but creates a hidden dependency: if the team renames or removes the target, your local source silently breaks. Either 'git add ${safe_src}' to elevate the source to project scope, OR copy the target into a local-scope sibling and reference that copy instead so the dependency is self-contained."
          ;;
      esac

      local fp
      fp=$(printf '%s\t%s\t%s' "$src" "$target_rel" "$pair" \
             | cksum | awk '{print $1}')

      emit_once "$SEEN" "${drift_class}@${fp}" "$drift_msg"
    done <<< "$refs"
  done <<< "$sources_buf"

  rotate_log_if_big cross-scope-reference-drift
}

main
exit 0
