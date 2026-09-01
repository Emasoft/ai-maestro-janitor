---
trdd-id: DD5X4O6Z
title: Reconcile the native continue-at-usage-limit-reset with the janitor's rate-limit resume and the OAuth rotator
column: backburner
created: 2026-09-01T19:26:25+0200
updated: 2026-09-01T19:26:25+0200
current-owner: janitor-main-session
task-type: audit
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: user
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: []
---

# The harness now resumes at limit-reset natively — who owns that job?

## Why

Claude Code 2.1.234: *"Claude Code now continues your session automatically when a claude.ai
usage limit resets; turn it off in /config ('Continue automatically at usage limit')."* Plus
2.1.239's `CLAUDE_CODE_RETRY_WATCHDOG` persistent retry mode (now failing fast on spend-limit /
out-of-credits). The janitor's continuity stack (rate-limit auto-resume, the OAuth rotator's
wake-up cron, the TRDD-1222f06a three-component design) was built when NONE of this existed.
Overlap risks: double-resume (native continue + janitor cron both firing a turn at reset),
the rotator rotating an account the native continue was about to resume on, and dead janitor
code nobody dares delete because its harness-side replacement was never confirmed.

## The audit (this card is an audit first, a refactor second)

1. Establish the setting's actual state on this machine and what it does when multiple
   accounts/rotator slots exist (does it wait for THIS account's reset, or any?).
2. Map each janitor continuity component to: superseded / still needed / needs adaptation.
   The rotator's core value — N paid subscriptions rotating on 429 — is NOT superseded
   (native continue waits for a reset; the rotator avoids the wait entirely). The wake-up
   cron's value MAY be.
3. Propose (separate cards) any retirement. Nothing is deleted under this card.

## Acceptance

- [ ] a written matrix: native feature vs janitor component, with the measured behavior of
      "Continue automatically at usage limit" on a rotator-managed host
- [ ] USER decides which janitor components retire; follow-up cards filed

## Notes and lessons learned

*(none yet)*
