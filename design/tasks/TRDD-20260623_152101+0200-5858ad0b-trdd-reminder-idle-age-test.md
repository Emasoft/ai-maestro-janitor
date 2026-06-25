---
trdd-id: 5858ad0b-d197-400a-a953-8bb40b06fdfd
title: Complete issue #59 — trdd-reminder idle+age label + first test (backburner-exclusion regression)
column: published
created: 2026-06-23T15:21:01+0200
updated: 2026-06-25T10:22:22+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
task-type: bugfix
priority: 4
severity: LOW
effort: S
labels: [detector, trdd-reminder, false-positive, tests]
parent-trdd: TRDD-fe45babc
relevant-rules: []
release-via: publish
test-requirements: [unit]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/59"]
---

# Complete issue #59 — trdd-reminder idle+age label + first test

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-23

**Context:** issue #59 reported two `trdd-reminder` defects. Commit `903e293`
already landed the PRIMARY fix (exclude `backburner`/parked columns from the
"active" set; `_ACTIVE_COLUMNS = {dev, testing, ai_review, human_review}`) but it
(a) is UNPUBLISHED — the live heartbeat runs the cached v0.15.0 pre-fix detector,
so backburner still leaked at runtime this session (`TRDD-631fa3de (13d)` is
`column: backburner` yet was reported active); (b) MIS-fixed Defect 2 — it replaced
the *staleness* number with true age, losing the idle signal the reminder needs; and
(c) shipped with **NO test** (the detector has zero coverage).

**This TRDD completes #59:**
1. **Defect-2 label, done right:** show BOTH metrics — `TRDD-xxxx (idle Nd, age Md)`
   — idle = days since last-touched (git-commit/mtime; the staleness that justifies the
   nag), age = days since `created:` (true age, context). Fall back to `(idle Nd)` when
   `created:` is absent/unparseable. The reminder's PURPOSE is to surface stalled active
   work, so staleness leads; age is context. (The 903e293 interpretation — show only age
   — dropped the load-bearing staleness signal.)
2. **Keep the active set** `{dev, testing, ai_review, human_review}` (903e293) — this
   already fixes Defect 1 (backburner excluded). `blocked` is deliberately NOT included:
   a blocked TRDD is waiting (its blockers are tracked + surfaced by `trdd-drift`), not
   "active work someone forgot"; lumping it under "currently active" would re-introduce
   the same mislabel #59 is about. Explained in the issue reply.
3. **First test** `tests/test_trdd_reminder.py` (real subprocess, no mocks): backburner
   excluded (the #59 regression guard), dev/testing/in-progress included, terminal
   excluded, the idle+age label, the `(idle Nd)` no-created fallback, and the legacy
   full-UUID filename path.

**NEXT ACTION:** none — fix + test committed. Ships on the next `publish.py` (gated on
USER). Then comment+close #59. The runtime leak self-resolves once the fix is cached.

## Notes
- Orthogonal to the wikimem atom-model redesign (TRDD-3b9b2040) — pure TRDD-tracking
  detector logic, picked up as safe overnight work while the memory work is USER-gated.
