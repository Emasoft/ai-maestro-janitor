---
trdd-id: LUQKXP3R
title: Usage caps were recorded for an account that was not the live one
column: complete
status: archived
created: 2026-10-05T22:11:16+0200
updated: 2026-10-10T16:31:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:16+0200
---

# Usage caps were recorded for an account that was not the live one

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The rotator state on 2026-10-05 held five 5h and five 7d cap samples of 0.0 for an alternate account. Cap learning runs only for the live account, so how these were written was never explained.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T16:31:38+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Corrections

2026-10-05 (review): the account may have been the live one when the samples were written; the state shows no history, so 'not the live one' describes the day it was read, not when the caps were learned.

## Findings

2026-10-10 16:31. EXPLAINED as far as the evidence reaches, by the main session, no code. In the code as it stood before the fix (git show 95bbddeb^), usage caps had exactly ONE writer: cmd_auto's 429 branch called burn_gate.observe_wall(state, live_email, now) once the streak was debounced. The email it wrote under is the state's live_email, and each sample is that account's freshest usage reading. So the five 0.0 samples per window mean: five debounced usage-endpoint 429 answers arrived while the state named that account as live and its last reading was 0 percent, which is a throttle and not a limit. Two readings fit and the state keeps no history to tell them apart: (a) the account really was live then and was rotated away later (the card's own correction); (b) the state's live_email was stale on mirror ticks and named an account that was not in use (the gap described on TRDD-EMCS2S0B). Either way the writer no longer exists: 95bbddeb removed the call and discards stored caps every tick, released since v3.7.1; the installed 3.8.11 has no caller of the cap writers outside burn_gate.py. NOT DONE: telling (a) from (b); the rotator log of 2026-10-05 is no longer on disk.

## Acceptance

- [x] The card says usage caps were recorded for an account that was not the live one and that how they were written was never explained. Explained by the single writer in the pre-fix code (observe_wall under the state's live_email on a debounced usage-endpoint 429); which of two readings applied on 2026-10-05 cannot be recovered. The writer was removed in 95bbddeb (release v3.7.1 and later), pinned by tests/test_oauth_rotator.py::test_usage_endpoint_429_streak_teaches_no_cap, in today's green suites and not re-run by name. FIELD CASE UNOBSERVED since the fix; none can occur while nothing calls the writer.
