---
trdd-id: S6GX1DHN
title: Board drain — complete every open TRDD under the owner mandate of 2026-10-09
column: dev
status: tasked
created: 2026-10-09T22:05:40+0200
updated: 2026-10-09T22:05:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T22:05:40+0200
---

# Board drain — complete every open TRDD under the owner mandate of 2026-10-09

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-09

OWNER MANDATE, verbatim, 2026-10-09: 'you don't need me. just complete all TRDDs and decide yourself. base your decisions on verified facts and accurate comparisons and tests. go on and finish all tasks. when all TRDDs are done, i have a big task for you that will finally solve the disaster of your compaction timing breaking the cache every time. but now work on the TRDDs.' Earlier the same day: 'the limit of 5000 tokens per skill cannot be violated. but you can create reference files and move some text there'.

Still stop for: destructive or irreversible acts, anything outward-facing (push, publish outside scripts/publish.py, posting to GitHub), credential work, and human-only acts. No publish until the board is drained (project rule: finish pending cards first).

BOARD MEASURED 2026-10-09 (trddgrep board, 361 open cards in design/tasks): backburner 93, complete-but-unarchived 86, todo 81, testing 57, blocked 27, human_review 10, design 4, dev 1, verify_assumptions 1, live_auditing 1.

NEXT ACTION: run the waves below in order. One worker per card, one writer per file set, the main session alone touches git (stage by name, commit per card with the card id in the subject). Every decision rests on a measurement recorded on the card it closes.

WAVES:
1. complete-but-unarchived (86): for each, find why trddgrep did not archive it (missing acceptance checklist, open box, release-via) and either archive it or re-column it with the reason. Cheap, clears a quarter of the board.
2. human_review (10): the owner delegated these; decide each from its evidence, record the decision and its basis, close or re-column.
3. testing (57): run each card's own Verify clause; close on a pass, return to todo with the failure on a fail. Event-gated cards (C22 JD2QR5SQ, C31 OLNPXGBC: need a real repair dispatch with an observed refusal) stay, each with a machine-checkable unblock-when.
4. todo (81) and dev (1): implement, ranked by trddgrep next (unblock count first). Code changes get the full gate before commit: ruff, mypy, pyright, uv run pytest.
5. blocked (27): re-evaluate each blocked-by after waves 1 to 4; a blocker that names a closed card is cleared.
6. design (4), verify_assumptions (1), live_auditing (1): advance each one step or record why it cannot move.
7. backburner (93): decide each on the facts — do it, or cancel it with the reason recorded. Deferred is not a resting place under this mandate.

OWNER-QUESTION CARDS now mine to decide: C30 I4MOD020 (discovery trigger: lint-driven surface versus extending repair_has_work to consult lint) — decide by measuring both on a scratch corpus.

KNOWN CONSTRAINTS: every paid account was at its usage limit at 2026-10-09 evening (rotator alert), so worker fan-out may stall until a window resets; the strict publish validator needs PLUGIN_SKIP_GITHUB_INTEGRITY=1 in the environment and exits 0 on main as of 746da19b.

## Acceptance

- [ ] trddgrep board shows no card in todo, dev, testing, human_review, design, verify_assumptions or backburner that lacks a recorded, dated reason for being there.
- [ ] No complete card remains in design/tasks.
- [ ] Every blocked card names a blocker that is itself still open.
- [ ] uv run pytest, ruff, mypy and pyright pass on main, and the strict validator exits 0.

## Approval log

- 2026-10-09T22:05:40+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
