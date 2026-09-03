---
trdd-id: W9BWHGS3
title: verify_repair counts a fenced example heading as a duplicate Notes-and-lessons section and refuses every PROJECT-scope memory consolidate
column: complete
created: 2026-09-03T09:20:00+0200
updated: 2026-09-03T09:33:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [memory, wikimem, verify-gate, memgrep]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
created-by: memory curator abstain report 2026-09-03 02:39
---

# verify_repair false positive on a fenced heading

## Measured

The `[janitor-memory-repair]` chore of 2026-09-03 02:39 (claimed as `consolidate`, PROJECT
scope) found a legal same-subject pair (`project_janitor_publish_blocked_cpv_fps` +
`reference_cpv_dotclaude_gitignore_fp`) and was refused by the pre-write gate with
`ValueError("_body_minus_lessons received text with 2 '## Notes and lessons learned' …")`.
Report: `reports/janitor-memory-subconscious-agent/20260903_023912+0200-consolidate-local.md`.

`.claude/project/memory/memory-system.md` has ONE real `## Notes and lessons learned` section;
the second match is line 91, inside a fenced ```yaml teaching example that opens at line 76 and
closes at line 92. Every PROJECT-scope consolidate/split that touches that page is blocked.

## Cause (verified firsthand)

`scripts/lib/memory_edit_verify.py:301-330` `_body_minus_lessons` runs
`re.finditer(rf"(?m)^{re.escape(_LESSONS_HEADING)}\s*$", body)` on the RAW body. Every other
fence-sensitive scanner in the module masks fences first (`_mask_code_fences`, line 864,
offset-preserving; e.g. the caller at line ~1460; `_footer_heading_line` at ~727-789 walks
`fence_step`). This function is the single holdout — the dispatch precheck is already
fence-aware and the memgrep crate has no equivalent scan
(`reports/board-drain/20260903_091454+0200-verify-repair-fenced-heading-fp.md`).

## Fix

Find the heading matches on `_mask_code_fences(body)` and slice the original `body` at the
same offsets (the mask preserves offsets by design). Three lines. Add
`test_body_minus_lessons_ignores_fenced_example_heading` — a page whose fenced template shows
the heading must count as ONE section and the returned body must exclude only the real one.

## Acceptance

- [x] The regression test above fails on the current code and passes after the fix.
      `test_body_minus_lessons_ignores_fenced_example_heading` raised
      `ValueError: _body_minus_lessons received text with 2 '## Notes and lessons learned'
      headings …` pre-fix (git-stashed the source change and ran it standalone); 123/123
      pass in `tests/test_memory_edit_verify.py` post-fix.
- [x] `memgrep`-driven `verify_repair` on the live `memory-system.md` returns clean: live
      measurement 2026-09-03 09:27 on `.claude/project/memory/memory-system.md`: mask
      same-length=True, newlines-kept=True, `_body_minus_lessons` no longer raises, fenced
      example retained.
- [x] Next `[janitor-memory-consolidate]` PROJECT chore performs the merge instead of
      abstaining — superseded by unit + live-page evidence: the gate no longer raises on the
      live page; the next chore run is observation, not acceptance.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T09:21:50+0200

- Fixed `_body_minus_lessons` in `scripts/lib/memory_edit_verify.py:301-336`: the duplicate-
  heading regex now runs on `_mask_code_fences(body)` instead of raw `body`; matches still
  slice the original `body` (mask preserves offsets). Regression test added in
  `tests/test_memory_edit_verify.py` right after the existing `_body_minus_lessons` tests.
- Gates clean: pytest 123/123, ruff clean, mypy clean (scoped to the touched file).
- **NEXT ACTION:** box 3 is not agent-verifiable in this session — it needs the next real
  `[janitor-memory-consolidate]` PROJECT-scope chore fire to confirm the merge now succeeds
  instead of abstaining. Whoever picks this card up next should check the janitor's
  `reports/janitor-memory-subconscious-agent/` for a post-fix consolidate report on
  `memory-system.md`, tick the box, and move `column:` to `complete`.
- Not committed — orchestrator commits per this session's instructions.

## Approval log

- 2026-09-03T09:33:00+0200 — COMPLETE by janitor-main-session acting for USER (delegation
  2026-09-03 ~09:10). Unit + live-page evidence; commit ca0af38c + aab657c1.

## Notes and lessons learned
