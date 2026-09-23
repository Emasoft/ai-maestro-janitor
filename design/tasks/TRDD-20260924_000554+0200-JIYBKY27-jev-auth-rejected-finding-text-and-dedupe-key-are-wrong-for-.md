---
trdd-id: JIYBKY27
title: Jev auth-rejected finding text and dedupe key are wrong for 402 credits errors
column: backburner
created: 2026-09-24T00:05:54+0200
updated: 2026-09-24T00:05:54+0200
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
