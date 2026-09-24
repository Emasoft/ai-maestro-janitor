---
trdd-id: U6C3YXEL
title: Items excluded from the injected Jev copy get a pointer and are counted in the elided line
column: todo
created: 2026-09-24T08:29:57+0200
updated: 2026-09-24T19:19:45+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:29:57+0200
implementation-commits: [f87a1a79, 09b769b2]
---

# Items excluded from the injected Jev copy get a pointer and are counted in the elided line

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-24

- 2026-09-24 13:40 — column todo. Landed in f87a1a79 (with TRDD-BLGZTHQ9): excluded decision-passing items get pointers and the elided count includes byte-stage exclusions; the decision reserve is HELD (deviation D2, accepted). Acceptance not met: b2bf5b7b shows 5 decision pointers against min(6, excluded) = 6.
- KNOWN DESIGN LIMIT (not a tuning miss): an early owner message Jev did not score as a decision always loses to newer ones. The F1b re-render shows b2bf5b7b's missing message inline only by a byte-budget side effect; the limit stands.
- NEXT: re-measure with accept.py after 825e5da8, f2e6ead7 and 1fe03838 (content-free wrapper pointers inflated the earlier numbers). The owner's 2026-09-24 directive to keep all owner and assistant prose verbatim and unscored (TRDD-RAEGS1D5 STATE) likely changes this card's owner-tier premise: decide after that design lands.

Follow-up to TRDD-AW4XD53Q (complete). Measured 2026-09-24 on three cached real transcripts: items that survive the token stage but are excluded by the injected copy's byte admission (or evicted by the backstop) get neither a body nor a pointer, and are missing from the '[[elided: N more items]]' count. That is 39/24/18 items, including 21/22/7 decision-passing owner messages. Fix: every excluded decision-passing item gets at least a pointer line, and the elided count includes byte-stage exclusions, reserving the line's width up front so counting cannot change the fit. Tests must fail without the fix.
Amendment S1 re-read (2026-09-24): non-owner inline eligibility now keys on "Jev kept" (s.kept and not s.oversized), not on the token stage's admitted set. Tool and event items shown inline, before and after, on 4 cached sessions: 4->7, 0->8, 2->10, 3->10. Pointers did not drop: 3->5, 5->6, 4->4, 7->10. The injected copy stays under 8,192 bytes. S1 landed in 09b769b2; its negative test in 73df900b.

## Approval log

- 2026-09-24T08:29:57+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review corrections 2026-09-24

Landed in f87a1a79 (with TRDD-BLGZTHQ9; reports/compaction-replacement/20260924_130147+0200-injected-selection-worker.md §2 item 1). Deviation D2, accepted: the decision reserve is HELD, not refunded. Its byte limit is fixed at fill step 3 as min(25% of available, room left after steps 1-2), and a reserved item goes inline only if the next-newest excluded decision item can take its pointer place. Measured decision pointers on the four cached transcripts b2bf5b7b/d30bf250/4eb7bf5d/fd5cc3e0: design literal (refund) 2/0/2/1, refund then re-reserve 3/4/8/2, held (shipped) 5/6/9/2, against 7/12/230/2 excluded decision items. b2bf5b7b still falls short of the acceptance row min(6, excluded) = 6, with 5.
Fill-order trade, accepted: the held reserve is paid for with the owner's verbatim text (owner items inline 5 -> 4 on b2bf5b7b). Its measured value was inflated by content-free command wrappers (3 of 9 decision pointers on 4eb7bf5d were /compact wrappers, 1 of 6 on d30bf250 was /ponytail) until 825e5da8 made them control inputs; re-measure before quoting the numbers above again (review of f87a1a79).
KNOWN DESIGN LIMIT, not a tuning miss: b2bf5b7b reaches 7 of 8 key owner directives. The owner tier is ordered (decision_passed, newest first), so an early owner message Jev did not score as a decision (score 0.14) always loses to newer ones, and no constant or share can fix that. The unreachable one is the message that started the incident: "i had to manually rotate again. why?". Recorded as a limit of this design, not as "7/8 accepted".
2026-09-24, in the F1b re-render (1fe03838, reports/compaction-replacement/20260924_133447+0200-f1b-worker.md): on b2bf5b7b "i had to manually rotate again. why?" (9a2ca9ba) is inline as a BYTE-BUDGET SIDE EFFECT (a title-only task-notification left the inline set and freed its bytes). The KNOWN DESIGN LIMIT above is NOT fixed: an older owner message Jev did not score as a decision still loses to newer ones and will recur on other sessions. Not re-measured by accept.py yet.
