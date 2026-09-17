---
trdd-id: FKY3NXB8
title: No-headroom fallback livelocks on an idle pane holding abandoned unsubmitted text
column: testing
created: 2026-09-17T07:03:26+0200
updated: 2026-09-17T07:41:32+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-17T07:03:26+0200
priority: critical
---

# No-headroom fallback livelocks on an idle pane holding abandoned unsubmitted text

Symptom: pane_policy._at_idle's NO_HEADROOM row (scripts/lib/pane_policy.py:323-334) defers the model-switch keystrokes on every beat while state.input_field.kind != InputFieldKind.EMPTY -- nothing distinguishes an abandoned leftover (janitor's own stale typed text, a crashed paste) from a live human draft, so a pane that never clears its field never gets switched off the exhausted model. Origin: TRDD-8P4BNY5J follow-up, filed 2026-09-17. AWAITING_USER and UNKNOWN panes get no keystroke at all on NO_HEADROOM either (scripts/lib/pane_policy.py:411-433 falls through to the bare return () for both), a silent no-op accepted as out of scope for 8P4BNY5J. Candidate fixes: (a) an age threshold on unchanged field text, tracked via pane_state, that treats N-beats-unchanged as abandoned and proceeds; (b) an ESC-then-retype recovery when the stale text matches the janitor's own previously-sent command. Acceptance: a test where an idle pane holding stale unsubmitted text older than N beats gets the model-switch keystrokes instead of an indefinite defer.

## Approval log

- 2026-09-17T07:03:26+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T07:21:35+0200 — column → todo by main session (owner standing permission 2026-09-03). regression introduced by 0e8b97c9: no-headroom fallback no longer fires on an idle pane holding the janitor's own leftover text
- 2026-09-17T07:31:42+0200 — column → testing by IMPLEMENTER. code+tests landed; no acceptance checklist exists to leave open (0 boxes); age-store extension explicitly out of scope, noted in STATE

## ⏵ STATE — READ THIS FIRST ON RESUME

2026-09-17T (CLOSER) — moved backburner -> todo, priority set to critical: this is a regression 0e8b97c9 introduces (the no-headroom fallback no longer fires on an idle pane holding the janitor's own leftover text). To be fixed before the 3.5.6 release.
2026-09-17T (IMPLEMENTER) — fixed in pane_policy.py's _at_idle NO_HEADROOM row: idle field EMPTY -> switch as before; TEXT starting with '/model' (the janitor's own unverified leftover retry, the regression 0e8b97c9 introduced) -> one ESC (FIELD_EMPTY) to clear it, then the same switch; any OTHER text (a human draft) -> still defers, unchanged, now with a logged reason (first 40 chars) via pane_actuate.act()'s new NOOP-path log call, since plan() itself must stay pure. No per-pane age store exists anywhere in this codebase for input-field staleness (checked _stamp_declined and state.py's presence-path helpers, both unrelated), so per RULE 1 scope no cross-beat abandonment timer was invented -- box 3's 3-consecutive-beat idea is NOT implemented, left for a follow-up if the logged-foreign-text population turns out to need it. Card carries no acceptance checklist (trddgrep check-box reports 0 boxes; the 'abandoned' hit count trddgrep search reports is word occurrences in prose, not checkboxes). Tests: tests/test_pane_policy.py::test_idle_no_headroom_clears_its_own_leftover_model_text_then_switches, ::test_idle_no_headroom_defers_over_foreign_text_not_its_own_leftover; tests/test_pane_actuate.py::test_idle_no_headroom_logs_the_deferral_reason_over_foreign_text. All 4 gates green (ruff, mypy, pyright, pytest 139 passed).
2026-09-17T (IMPLEMENTER, review follow-up) — tightened the '/model' leftover match: startswith("/model") could also clear a human draft merely starting with those characters ('/models are confusing me'); now requires the whole command word (text == '/model' or startswith('/model ')). New test: test_idle_no_headroom_does_not_clear_a_human_draft_that_merely_starts_with_model. 140 tests pass, gates still green.
2026-09-17T07:41:32+0200 — VERIFY pass: the NO_HEADROOM/leftover-`/model` clear step already carries a real verify Expect (pane_policy._at_idle line ~352 reuses _flush_wedge(final_expect=Expect.FIELD_EMPTY), the same mechanism the wedge row's ESC step uses) -- not a blind key, no change needed. Also deleted the dead 'return False' after satisfied()'s exhaustive Expect-enum if-chain (pyright unreachable, 5-member closed enum, every member already has its own branch); ruff/mypy/pyright clean, 108 tests pass. On the spent-window /model-clear collision: accepted as stated, not an oversight -- a human draft that is exactly /model or /model <text> could not have been sent as written on a spent window anyway; an abandoned non-/model draft still livelocks pending a per-pane age store (out of RULE 1 scope here).
