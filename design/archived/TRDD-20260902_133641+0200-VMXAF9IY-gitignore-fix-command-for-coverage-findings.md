---
trdd-id: VMXAF9IY
title: a janitor-gitignore-fix command — the remedy path for gitignore-coverage findings (D5 of TRDD-6WM4BFKF)
column: complete
created: 2026-09-02T13:36:41+0200
updated: 2026-09-03T10:05:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02 23:13

Orchestrator review correction, 23:38 (on top of the worker's `1c576fd4`): (1) a failing
`git check-ignore` / `git ls-files` returned `{}` / `[]`, which read as "nothing ignored / nothing
tracked" — with `--apply` that would have appended EVERY class pattern on a git error; both now
`sys.exit` non-zero (unknown ≠ none). (2) the write path split lines and re-joined them, so a
`.gitignore` with CRLF endings or no final newline was normalised, not appended; it now reads
and writes with `newline=""` and appends after the existing bytes verbatim. Criterion-3 test
re-seeded with CRLF + no trailing newline and asserts on bytes; new
`test_a_git_failure_exits_nonzero_and_writes_nothing`.

Shipped: `scripts/gitignore_fix.py` (propose/`--apply`, reuses `lib/gitignore_coverage`'s
class table + `is_protected`, git-check-ignore-backed, never runs `git rm`), `skills/janitor-
gitignore-fix/SKILL.md`, `tests/test_gitignore_fix.py` (4 tests, one per criterion 1-4:
`test_missing_dotenv_is_proposed_and_only_written_after_apply`,
`test_a_tracked_dotenv_prints_git_rm_cached_but_never_runs_it`,
`test_apply_preserves_existing_lines_order_and_negations_byte_identical`,
`test_protected_prefixes_never_appear_in_either_direction`). All 16 (4 new + 12 existing
`gitignore_coverage`) green; ruff + mypy clean. Skills are auto-discovered from `skills/` —
no `.claude-plugin/plugin.json` registration needed (grep confirmed no skill-name array
there). Roster line added next to the real `safe_delete.py` entry in
`janitor-core-files-reference.md` (not `janitor-skills-and-agents-roster.md` as drafted —
that page never actually names `safe-delete`; `janitor-core-files-reference.md` is where the
`safe_delete.py` line genuinely lives), via `memgrep update-mem-topic`; validate + lint clean.
No Agent tool available to this lean-worker, so the fable-advisor threshold hook could not be
honored — noted, not silently skipped; task was fully specified by the orchestrator.

NEXT ACTION: run `/janitor-gitignore-fix` for real on one of the ten fleet repos already
carrying `ADVISORY-GITIGNORE-COVER` lines, confirm the proposed diff, apply it, and manually
`git rm --cached` any tracked offender after user confirmation.

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

## Approval log

- 2026-09-03T10:05:00+0200 — CLOSE (testing → complete) by janitor-main-session acting for USER
  (delegation 2026-09-03 09:58). Audit `reports/board-drain/20260903_092000+0200-testing-cards-evidence-audit.md`
  verdict CLOSE: criteria 1-4 proven by `test_gitignore_fix.py` (5 passed), criterion 5 by
  `janitor-core-files-reference.md:28` + clean ruff/mypy. Follow-up: run the command live on one
  fleet repo before the next publish is called final (STATE's own NEXT ACTION, not yet done).
