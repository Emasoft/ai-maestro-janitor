---
trdd-id: YELTOX2S
title: The burn gate docstring still describes usage cap learning as active
column: complete
status: tasked
created: 2026-10-05T22:11:16+0200
updated: 2026-10-10T16:29:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:16+0200
blocked-by: []
pre-block-column: 
unblock-when: [trdd:6NMQ95TQ terminal]
blocker-probe: trddgrep --porcelain show 6NMQ95TQ | cut -f3
blocker-holds-if: not-match:^(complete|completed|cancelled|superseded|published|live|failed|live_auditing)$
release-via: publish
implementation-commits: [1634f4b8]
---

# The burn gate docstring still describes usage cap learning as active

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

scripts/oauth_rotator/burn_gate.py opens with a description of learned caps that TRDD-YVC3F06V switched off. fastedit refused the edit that would have corrected it.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 — owner refused plain edits after a fastedit refusal (verbatim: 'the answer is no. if the trddgrep tool is not flexible enough to make the changes you need, open an issue on Emasoft/ai-maestro'). The burn_gate.py docstring fix stays undone until fastedit accepts the edit.
- 2026-10-10T16:29:11+0200 — column → complete by main-agent@ai-maestro-janitor.  Cleared blocked-by (--clear-blocker override).

## STATE

2026-10-06: blocked on TRDD-6NMQ95TQ: fastedit refuses the docstring edit (reported as Emasoft/fastedit#14); the owner ruled out a plain-edit fallback. Resumes when a fastedit release accepts the edit.
2026-10-10 16:29. ALREADY PAID, no code in this commit. The docstring was corrected in 1634f4b8 on 2026-10-10 by a worker writing through fastedit (the owner's ruling against plain edits was kept): scripts/oauth_rotator/burn_gate.py now opens its cap paragraph with CAP LEARNING IS OFF and says nothing calls observe_wall (read today by the main session, lines 23 to 38). The blocker TRDD-6NMQ95TQ is still open in backburner but no longer holds this card: the edit it was waiting for has landed. OPEN ITEM carried on TRDD-S6GX1DHN since 14:45: the sentence that learned_caps is currently always absent on disk is too strong for a host whose ticks reach no save path.

## Acceptance

- [x] The card says the burn gate docstring still describes usage cap learning as active. It no longer does (1634f4b8, on main, unreleased; documentation only, no test can pin it). One sentence in it is still stronger than the facts and is recorded as an open item on TRDD-S6GX1DHN.
