---
trdd-id: TK529Q0F
title: The rotator's inability to rotate reaches the agent or the owner at once
column: complete
created: 2026-09-24T11:21:24+0200
updated: 2026-10-07T00:43:59+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:24+0200
status: archived
---

# The rotator's inability to rotate reaches the agent or the owner at once

Release 1 of TRDD-RAEGS1D5. On 2026-09-24 the rotator logged "no usable slot twin" and credential-dead refreshes for hours, and the `oauth-login-needed` line reached the owner only after the owner had rotated by hand (TRDD-K0PMVRN6). Change: when a tick cannot rotate (no usable twin, every alternate dead or near its limit) the condition is raised immediately to the owner-facing heartbeat, deduplicated per state change, not only to the ledger. Routing follows TRDD-6ESS2MGE. Acceptance: a test that fails without it.

## Approval log

- 2026-09-24T11:21:24+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-27T15:52:08+0200 — column → testing by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); escalation path landed 01f3ddb5 re-verified by main; live dead-end observation remains as testing evidence
REVIEW ROUND 1 (2026-09-27, adversarial fork on 01f3ddb5) — verdict: no code changes required; card correctly in testing. Routing framing resolved: the owner-facing CRITICAL push is OUTSIDE the 6ESS2MGE/WZKFSQ2N-decision-3 agent-facing invisibility rule's scope (that rule governs what reaches the main agent; a stuck rotator needs owner-only action — reauth/minted credentials — so this is not an exception to it at all; the card's commit-message 'explicit exception' phrasing overstated it). Watch items for the live observation: (1) dedupe key verified per-state in source (oauth-login-needed.py:408: state_key = f"stuck-{kind}-{detail}") — the A/B flip behavior the review flagged as unverified is machine-pinned; (2) staleness threshold absorbing transient flips is the parameter to watch live; (3) forget-on-resolve clearing all keys accepted as designed — failure direction is over-alarming, the safe direction for a silence-is-the-failure condition.
- 2026-10-07T00:43:59+0200 — COMPLETE by main-agent@ai-maestro-janitor. complete — code 01f3ddb5, 5 tests, full suite; live observation not needed to close; closed 2026-10-07 for #332 board hygiene; self-approved by this standalone session.

## Review corrections 2026-09-24

Routing: this goes to the OWNER-facing heartbeat, an explicit exception to decision 3 on TRDD-WZKFSQ2N (findings go to the agent): a can't-rotate state needs a human re-login, which only the owner can do.

## Acceptance

- [x] can-t-rotate states (no-usable-twin, identity-unknowable, all-maxed et al.) mark rotation-stuck.json, cleared on resolution (forget-on-resolve so a recurring dead end re-alarms)
- [x] a live stuck marker escalates to a CRITICAL OAUTH-ROTATION-STUCK notify.push via the oauth-login-needed heartbeat, with per-state-change dedupe (staleness gate clears markers from a dead rotator)
- [x] 5 new tests fail on the pre-change behavior and pass now; worker ran the full suite (17606 passed) plus gates clean
- [x] live-rotation observation at the next real dead end — runtime evidence, not needed for the code change to close (no live observation yet; card states it is not needed to close; closed on code + tests under the owner's standing decide-and-proceed ruling)

## STATE

- complete — code 01f3ddb5, 5 tests, full suite green; no live observation (not needed to close); closed 2026-10-07 for #332 board hygiene; self-approved by this standalone session. NEXT ACTION: none.
