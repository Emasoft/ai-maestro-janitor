---
name: janitor-dependabot-doctor
description: Audits and auto-fixes Dependabot (or Renovate) config so dependency-update PRs land safely. Scaffolds a hardened .github/dependabot.yml when none exists, matching detected ecosystems (pip, npm, cargo, gomod, bundler, github-actions). Use when the user asks to "audit dependabot", "fix dependabot config", "set up dependabot", "harden dependency updates", "review renovate config", or after adding a new ecosystem. Trigger with /janitor-dependabot-doctor.
---

# Janitor dependabot-doctor

## Overview

Audits `.github/dependabot.yml` (or `renovate.json`) against the hardened invariants and scaffolds a hardened config when none exists. Modifications apply via Edit — never `sed` / `awk`. Findings without a recipe surface as `[NEEDS-HUMAN-REVIEW]`. Detail in references/dependabot-template.md, references/renovate-equivalents.md, references/audit-table.md.

## Prerequisites

- `git` on PATH, working tree clean.
- At least one detectable ecosystem signal in repo root.

## Instructions

1. **Resolve report dir and detect ecosystems.**

   ```bash
   # Anchor on CLAUDE_PROJECT_DIR, then resolve THAT repo's MAIN checkout (janitor#264).
   # Two real failure modes, and each single-source form hits one: resolving from the CWD
   # picks whichever nested repo the agent happens to be standing in, so two passes of one
   # chore wrote into two different `reports/` trees; using CLAUDE_PROJECT_DIR alone writes
   # into a LINKED WORKTREE, whose reports die with the branch. Anchoring the git call fixes
   # both — the anchor is stable for the whole session, and `git -C` still resolves a
   # worktree to its main checkout.
   ANCHOR="${CLAUDE_PROJECT_DIR:-$PWD}"
   MAIN_ROOT="$(git -C "$ANCHOR" worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p')"
   MAIN_ROOT="${MAIN_ROOT:-$ANCHOR}"
   REPORT_DIR="$MAIN_ROOT/reports/janitor-dependabot-doctor"
   mkdir -p "$REPORT_DIR"
   TIMESTAMP="$(date +%Y%m%d_%H%M%S%z)"
   ```

   Signals: pyproject.toml/requirements → `pip`; package.json → `npm`; Cargo.toml → `cargo`; go.mod → `gomod`; Gemfile → `bundler`; workflows → `github-actions`. Zero ecosystems → abort.

2. **Branch.** No dependabot AND no renovate → scaffold per the template reference, jump to step 5. Renovate present → audit per the renovate reference. Else → audit `.github/dependabot.yml`.

3. **Audit invariants** per the audit-table reference: weekly+off-minute schedule, `open-pull-requests-limit: 5`, `commit-message.prefix: "deps"`, dev/prod groups for npm+pip, `versioning-strategy: increase` for pip, explicit `ignore:` for pinned majors. No recipe → `[NEEDS-HUMAN-REVIEW]`.

4. **Apply fixes file by file** via Edit. After every edit validate the YAML parses; revert and mark `[FIX-FAILED]` on parse error.

5. **Write report** `$REPORT_DIR/$TIMESTAMP-fixes.md`: file:line, audit id, before/after hunk, ecosystems list.

6. **Stage explicitly named files** (NEVER `git add -A`):

   ```bash
   git add .github/dependabot.yml
   git commit -m "ci(deps): harden dependabot config (auto-applied)"
   ```

7. **One-line summary:** `janitor-dependabot-doctor: <action> <N> finding(s) across <M> ecosystem(s). Report: <path>`.

## Output

Step-7 line + `$REPORT_DIR/<TS>-fixes.md`.

## Error Handling

- Working tree dirty → abort.
- Zero ecosystem signals → abort `[FAILED] no detectable package ecosystem`.
- YAML parse fails after Edit → `git checkout HEAD -- .github/dependabot.yml`, mark `[FIX-FAILED]`, continue.
- Both dependabot AND renovate present → abort `[FAILED] pick one`.
- Finding without recipe → `[NEEDS-HUMAN-REVIEW]`, never silently skip.

## Examples

```text
User: /janitor-dependabot-doctor
User: doctor the dependabot config
User: audit dependabot
User: set up dependabot for this repo
```

## Scope

ONLY edits `.github/dependabot.yml` or the renovate config. Does NOT touch source, README, package metadata, or workflows. Does NOT push. Does NOT bump dependency versions. Pairs with `/janitor-github-workflow-doctor` and `/janitor-github-workflow-create`.

## Resources

- [dependabot-template](references/dependabot-template.md) — per-ecosystem templates and signal-detection table.
  - [Signal-detection table](references/dependabot-template.md#signal-detection-table)
  - [Shared invariants and schedule-stagger rule](references/dependabot-template.md#shared-invariants-and-schedule-stagger-rule)
  - [Per-ecosystem templates](references/dependabot-template.md#per-ecosystem-templates)
  - [Full example and rationale](references/dependabot-template.md#full-example-and-rationale)
- [renovate-equivalents](references/renovate-equivalents.md) — invariant ↔ renovate-key mapping.
  - [Why this file exists](references/renovate-equivalents.md#why-this-file-exists)
  - [Mapping and baseline](references/renovate-equivalents.md#mapping-and-baseline)
  - [Per-ecosystem rules and edge cases](references/renovate-equivalents.md#per-ecosystem-rules-and-edge-cases)
- [audit-table](references/audit-table.md) — finding ↔ surgical fix mapping.
  - [How the doctor applies a fix](references/audit-table.md#how-the-doctor-applies-a-fix)
  - [Findings by config type](references/audit-table.md#findings-by-config-type)
  - [Findings the doctor refuses to auto-fix](references/audit-table.md#findings-the-doctor-refuses-to-auto-fix)
- [Dependabot docs](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file).
