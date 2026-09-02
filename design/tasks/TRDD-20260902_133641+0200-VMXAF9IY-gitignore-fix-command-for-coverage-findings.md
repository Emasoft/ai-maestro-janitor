---
trdd-id: VMXAF9IY
title: a janitor-gitignore-fix command — the remedy path for gitignore-coverage findings (D5 of TRDD-6WM4BFKF)
column: todo
created: 2026-09-02T13:36:41+0200
updated: 2026-09-02T13:36:41+0200
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
---

## Problem

TRDD-6WM4BFKF shipped the `gitignore-coverage` detector (`e607e95a`): it SURFACES a missing
private-class pattern or an already-tracked private file, and by design never mutates. Its
design item D5 — a user-invoked `/janitor-gitignore-fix` that shows the proposed diff and applies
the remedy on confirmation — was never built, and the detector's own acceptance criteria did not
require it, so 6WM4BFKF closed without it.

The remedy path has real demand now, not speculative: on 2026-09-02 the findings ledgers of ten
fleet projects carry `ADVISORY-GITIGNORE-COVER` lines (28 on one repo alone), re-recorded on
every hourly fire, with nobody acting on them — because acting means hand-editing `.gitignore`
and hand-running `git rm --cached`, and the advisory is LOW so it never interrupts anyone.

## Design (D5 of TRDD-6WM4BFKF, verbatim intent)

- Shows the proposed `.gitignore` diff and REQUIRES confirmation before writing.
- Appends only the MISSING canonical patterns (from `lib/gitignore_coverage`'s class table —
  one source of truth, no second list); never reorders or rewrites existing lines; never touches
  a negation line (the `.claude/project/memory/**` block is the reference pattern).
- For CONTAMINATION (a private file already tracked) it emits the exact `git rm --cached <path>`
  invocations for the user to approve — never a working-tree delete, never run unasked.
- The protected allowlist (`design/**`, `.claude/project/memory/**`) is never proposed for
  ignoring and never proposed for untracking.
- Read-only until the user confirms; a refused confirmation leaves `.gitignore` and the index
  byte-identical.

## Acceptance criteria

1. On a seeded temp repo missing `.env`, the command proposes exactly `.env` (canonical form),
   and only writes it after confirmation.
2. On a seeded temp repo with a tracked `.env`, the command prints `git rm --cached .env` and
   does not run it.
3. Existing lines, ordering and every negation line of a seeded `.gitignore` are byte-identical
   after the append.
4. `design/**` and `.claude/project/memory/**` are never proposed, in either direction.
5. ruff + mypy clean, full `pytest tests/` green; the command is registered like the other
   `/janitor-*` skills and appears in the skills roster page.

## Notes and lessons learned
