---
trdd-id: 37H7QFSF
title: A heartbeat line that repeats with identical text is silenced for ever by the dispatcher's own line dedupe
column: todo
status: tasked
created: 2026-10-05T23:16:34+0200
updated: 2026-10-05T23:31:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T23:16:34+0200
---

# A heartbeat line that repeats with identical text is silenced for ever by the dispatcher's own line dedupe

Goal: investigate, verify and fix the root cause. READ in scripts/dispatch.py (the function _dedupe_drift_line, about lines 802 to 826): every drift line is keyed as detector name plus normalized text in drift-lines-seen.txt with a once-only primitive and no forget, so a detector that correctly forgets its own key when a condition clears and later prints the same text again is dropped at this layer. Affected by construction, where the text has no varying number: the stale index lock lines, the project-memory-tracked lines, the daily autofix-off line, janitor-install-scope, nested-git-safety for the same path. The same pattern, a once-only key with no forget, exists in the daemon's notification inbox error log (six error texts will never be logged again) and in about a dozen detectors listed in report 20261005_231015 fork-dedupe-keys-and-small-anomalies, section 1a. The only exit today is a trim to the newest 500 lines of per-project seen files, which is not a time bound and does not cover machine-wide files. Not verified: that a re-emitted line was actually swallowed (read in the code only). Smallest fixes named in the report: add the local day to the generic key; forget a key in the branch where the condition is found absent. Related: TRDD-BZ3BT0NJ change 2 (the memory guard key), TRDD-0NWG4LKJ (covered means silent must not become silent for ever).

## Approval log

- 2026-10-05T23:16:34+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): this dedupe was introduced by TRDD-7ZMQSXO6 (archived, complete, 2026-09-16), whose criterion was that a line surfaced in the immediately preceding fire is not repeated in the next one; its log records the seen file as append-only with a known ceiling. Suppression for ever goes beyond that criterion; this card is the follow-up, not a duplicate. The table in the report has sixteen rows, not about a dozen. 'Six error texts will never be logged again' is a reading of the seen file and of the code, not an observed loss. Leftover seen files of things that no longer run, to remove when this is fixed: host-load-seen.txt (the detector is unregistered, TRDD-8524H5V1) and marketplace-refresh-failing-seen.txt (the detector was retired 2026-09-17). The findings on this card are from a fork's report; the session checked only that the function has no forget.
2026-10-05 (second review): TRDD-7ZMQSXO6 was completed on 2026-09-17; 2026-09-16 is the day its dedupe landed.
