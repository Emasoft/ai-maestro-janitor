---
trdd-id: S6GX1DHN
title: Board drain — complete every open TRDD under the owner mandate of 2026-10-09
column: dev
status: tasked
created: 2026-10-09T22:05:40+0200
updated: 2026-10-09T22:17:11+0200
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

NEXT ACTION: FIRST read the section '## Rules added by the review of 4de85716' at the end of this card — its six rules BIND every wave below and win over the wave text (cost measured on one card and a cap written before any worker launches; order by trddgrep next; event-gated and human-only cards stay put; no cancellations). THEN start wave 1 with ONE card done by the main session, record its cost here, and write the cap and deadline before any fan-out. No cap or deadline is written yet. run the waves below in order. One worker per card, one writer per file set, the main session alone touches git (stage by name, commit per card with the card id in the subject). Every decision rests on a measurement recorded on the card it closes.

WAVES:
1. complete-but-unarchived (86): for each, find why trddgrep did not archive it (missing acceptance checklist, open box, release-via) and either archive it or re-column it with the reason. Cheap, clears a quarter of the board.
2. human_review (10): the owner delegated these; decide each from its evidence, record the decision and its basis, close or re-column.
3. testing (57): run each card's own Verify clause; close on a pass, return to todo with the failure on a fail. Event-gated cards (C22 JD2QR5SQ, C31 OLNPXGBC: need a real repair dispatch with an observed refusal) stay, each with a machine-checkable unblock-when.
4. todo (81) and dev (1): implement, ranked by trddgrep next (unblock count first). Code changes get the full gate before commit: ruff, mypy, pyright, uv run pytest.
5. blocked (27): re-evaluate each blocked-by after waves 1 to 4; a blocker that names a closed card is cleared.
6. design (4), verify_assumptions (1), live_auditing (1): advance each one step or record why it cannot move.
7. backburner (93): NO cancellations. Backburner is this board's deliberate deferral and the owner's words ('complete all TRDDs') do not say to cancel parked intent; cancelling is terminal and archived cards are immutable. Pull a backburner card into work only when it is ready and worth doing on the facts; otherwise leave it with a dated one-line reason. Cancelling any card needs the owner's explicit word.

OWNER-QUESTION CARDS now mine to decide: C30 I4MOD020 (discovery trigger: lint-driven surface versus extending repair_has_work to consult lint) — decide by measuring both on a scratch corpus.

KNOWN CONSTRAINTS: every paid account was at its usage limit at 2026-10-09 evening (rotator alert), so worker fan-out may stall until a window resets; the strict publish validator needs PLUGIN_SKIP_GITHUB_INTEGRITY=1 in the environment and exits 0 on main as of 746da19b.

## Acceptance

- [ ] trddgrep board shows no card in todo, dev, testing, human_review, design, verify_assumptions or backburner that lacks a recorded, dated reason for being there.
- [ ] No complete card remains in design/tasks.
- [ ] Every blocked card names a blocker that is itself still open.
- [ ] uv run pytest, ruff, mypy and pyright pass on main, and the strict validator exits 0.

## Approval log

- 2026-10-09T22:05:40+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Rules added by the review of 4de85716

2026-10-09 — these bind every wave and win over the wave text where they differ: (1) COST BEFORE FAN-OUT: no wave launches workers until one card of that wave has been done and its cost measured (tokens, wall-clock), a maximum card count and a deadline are written here, and the stop condition is checked before each card. (2) ORDER inside a wave follows trddgrep next (unblock count first), not column listing. (3) EVENT-GATED cards are exempt from 'back to todo on fail' BY KIND, not by id: any card whose completion waits on an external event stays where it is with a machine-checkable unblock-when. (4) HUMAN-ONLY cards (an act only the owner can perform, such as running a command in a live interactive session) stay in human_review with that reason; the mandate does not make them agent-decidable. (5) The working figure is 275 live cards: 361 includes the 86 already in the complete column. (6) This card sits in dev because the main session is working it; if the session stalls on usage limits, re-column it to todo with the date.
2026-10-09 WAVE 1 MEASURED, no card moved: all 86 cards in the complete column carry release-via: publish (49 with no Acceptance section, 37 with one; none has an open box). They are not stuck: complete is not their terminal column, the next step is a release through scripts/publish.py, which moves them to published and archives them. Wave 1 as written (archive or re-column) is VOID. They clear in one act, a publish, which the project rule places after the pending cards are finished. Cost of the measurement: one shell command, no worker.
2026-10-09 WAVE 2 FIRST CARD, cost measured: BW4Q08J8 closed by the main session in 8 shell calls and about 10 minutes, no worker (read the card, verify its one open claim, apply, verify against a backup, close). CAP for wave 2: the 9 remaining human_review cards (VT332PJG, BUR8AW77, RAEGS1D5, IKZROIE5, G9Z8PXCM, JY0OBQZ4, QQ7QCS3T, 3OS6AXV3, 5MOX0FPO), at most one worker per card, each worker capped at 40 tool calls, deadline 2026-10-10 06:00 local. STOP CONDITION checked before each card: a usage-limit refusal, a failing gate on main, or a card that turns out to need a human-only act (VT332PJG reads as one: 'run /effort once in a live session') — that card stays in human_review with the reason.
