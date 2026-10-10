---
trdd-id: DM7IJQ1T
title: Four of the five stuck kinds still tell the owner to capture logins
column: testing
status: tasked
created: 2026-10-05T22:11:15+0200
updated: 2026-10-10T16:10:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:15+0200
---

# Four of the five stuck kinds still tell the owner to capture logins

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Only all-accounts-maxed got its own alert text. no-alternates-configured needs another account and expired-and-offline needs a manual login; neither is helped by a login capture.

## Approval log

- 2026-10-05T22:11:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 15:46. BUILT, one code commit carrying this line. READ first by the main session: scripts/lib/rotator_alert.py gave its own text to all-accounts-maxed only and the generic capture-logins text to every other kind; the rotator writes five kinds. CHANGE: one table _STUCK_TEXT in that file; no-alternates-configured, expired-and-offline and identity-unknowable each name their own remedy; no-usable-slot-twin keeps the capture text on purpose, because a capture does repair a slot twin (the card counted it among the four; that part is declined with this reason); an unknown kind falls back to the generic text. TEST: tests/test_rotator_alert.py::test_stuck_alert_text_per_kind (six cases), red on the three new kinds before the change and green after, per the worker report reports/board/20261010_154500+0200-dm7ijq1t-worker.md; the main session read the whole diff. The worker also narrowed the older control test test_stuck_alert_for_other_kinds_keeps_the_capture_remedy to the one kind that still keeps the capture text; its docstring still says 'the identity kinds' and the new test covers the same case, so it is redundant: fix or drop at the next touch of that file. FIELD CASE UNOBSERVED: no marker of these three kinds was on disk today. NOT DONE: the heartbeat detector's own remedy table (scripts/detectors/oauth-login-needed.py) is untouched; the two-texts question is TRDD-MI018FID and this change makes it four pairs of texts, not one. Column testing until the full gate on this commit is green; then complete (release-via publish).
2026-10-10 16:10. GATE GREEN on ff50e5a6 (18319 passed, 2 skipped; ruff, mypy, pyright exit 0; reports/board/gate-ff50e5a6.txt). Review of ff50e5a6 (0.32 million tokens): no blocker. CHECKED afterwards by the main session: rotation-stuck.json is absent on disk and the retained rotator log holds no line of the three kinds, so 'no marker of these three kinds today' stands for the retained window; the worker report shows the three failing cases before the change. ACCEPTED: the 'capture-all-logins not in text' assertion cannot fail on its own, the exact-text equality decides it; str() now coerces a non-string kind before the lookup; 'four pairs of texts' was miscounted and is moot, since TRDD-MI018FID's change removes the detector's table. The redundant control test is deleted in that change.
