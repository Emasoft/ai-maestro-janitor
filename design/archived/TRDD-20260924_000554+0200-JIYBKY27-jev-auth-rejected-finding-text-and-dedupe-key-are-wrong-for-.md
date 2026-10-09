---
trdd-id: JIYBKY27
title: Jev auth-rejected finding text and dedupe key are wrong for 402 credits errors
column: complete
created: 2026-09-24T00:05:54+0200
updated: 2026-10-09T23:23:36+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T00:05:54+0200
implementation-commits: [0ec8951b, cdde522e, 80c0628d, f1910cc4]
status: archived
---

# Jev auth-rejected finding text and dedupe key are wrong for 402 credits errors

Found during the RAEGS1D5 STATE cleanup (2026-09-24): two follow-ups from the 402/403 auth-kind
fix (0b883373) were never carded.

1. record_once_per_reason (scripts/lib/jev_compaction_lane.py) always emits
   "provider key rejected: {reason}" for kind=auth, but JevAuthError now covers 401 (bad key),
   402 (insufficient credits) and 403 (forbidden/guardrail/moderation) alike (see
   scripts/lib/jevctx/openrouter.py). "key rejected" is wrong headline wording for a 402
   credits problem — the key is fine, the account is out of credits.
2. The dedupe key is sha256 of the raw OpenRouter error `reason` text
   (scripts/lib/jev_compaction_lane.py::record_once_per_reason). A 402 error body can vary
   run to run (e.g. a changing balance figure in the message), so the same underlying
   out-of-credits condition can re-fire the JEV-AUTH-REJECTED finding instead of being
   deduped once.

Fix: branch the headline wording on the underlying HTTP status (401 vs 402 vs 403), and key
the dedupe on something stable (status code, not the full reason string).

## Approval log

- 2026-09-24T00:05:54+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:31+0200 — column → testing by main-agent@ai-maestro-janitor. batch B1-B3 merged on main, gated
2026-10-07: a successful Jev compaction clears the auth dedupe so a later 401 surfaces again (cdde522e, 80c0628d, merge f1910cc4); consecutive 401s stay deduped; an llm-ext fallback success does not clear it.
2026-10-07: shipped in v3.8.4; release observation starts.
2026-10-09 CLOSED by the main session (board drain, wave 3). Checked by the main session: fix commits are ancestors of the v3.8.11 tag; the pinning tests pass on a re-run today. Pinning tests: test_auth_402_credits_headline_and_dedupe_keyed_on_status and test_auth_finding_refires_after_a_successful_compaction (2 passed). The card names no field observation; FIELD CASE UNOBSERVED: no real 402 from the provider has been seen in the logs. Assessment: reports/board/20261009_232221+0200-wave3-batchD.md.
- 2026-10-09T23:23:36+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11; pinning tests re-run; see Approval log 2026-10-09.

## STATE

2026-10-07 merged on main (0ec8951b): the auth finding is worded by HTTP status (402 out of credits, 403 refused, 401 or none as before) and deduplicated on the status instead of the reason text; test failed before (assert 2 == 1). Known gap, follow-up: the dedupe key is stored once and never cleared, so a second, different 401 (for example after a key rotation) is no longer surfaced; clear the stored key on the next successful probe. Not in a release yet.

## Acceptance

- [x] See the Approval log entry of 2026-10-09 for the evidence per promise.
