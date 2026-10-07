---
trdd-id: 37H7QFSF
title: A heartbeat line that repeats with identical text is silenced for ever by the dispatcher's own line dedupe
column: testing
status: tasked
created: 2026-10-05T23:16:34+0200
updated: 2026-10-07T08:20:05+0200
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
implementation-commits: [a3583bbf, 876296de, f1910cc4, 864864ba]
---

# A heartbeat line that repeats with identical text is silenced for ever by the dispatcher's own line dedupe

Goal: investigate, verify and fix the root cause. READ in scripts/dispatch.py (the function _dedupe_drift_line, about lines 802 to 826): every drift line is keyed as detector name plus normalized text in drift-lines-seen.txt with a once-only primitive and no forget, so a detector that correctly forgets its own key when a condition clears and later prints the same text again is dropped at this layer. Affected by construction, where the text has no varying number: the stale index lock lines, the project-memory-tracked lines, the daily autofix-off line, janitor-install-scope, nested-git-safety for the same path. The same pattern, a once-only key with no forget, exists in the daemon's notification inbox error log (six error texts will never be logged again) and in about a dozen detectors listed in report 20261005_231015 fork-dedupe-keys-and-small-anomalies, section 1a. The only exit today is a trim to the newest 500 lines of per-project seen files, which is not a time bound and does not cover machine-wide files. Not verified: that a re-emitted line was actually swallowed (read in the code only). Smallest fixes named in the report: add the local day to the generic key; forget a key in the branch where the condition is found absent. Related: TRDD-BZ3BT0NJ change 2 (the memory guard key), TRDD-0NWG4LKJ (covered means silent must not become silent for ever).

## Approval log

- 2026-10-05T23:16:34+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:47:59+0200 — column → testing by main-agent@ai-maestro-janitor. implemented in batch B5, awaiting verification
2026-10-07: DECISION: the per-fire forget (a3583bbf, merge f1910cc4) was reverted in 876296de because detectors exit 0 silently while a condition holds (throttle, offline, own dedupe). Now four self-deduping detectors (oauth-login-needed, stale-index-lock, system-daemon-runaway, trdd-cross-card-blindspot) bypass the dispatcher dedupe = fixed for them. Every other detector's key carries the local date = bounded to one day, not fixed: a standing line of a non-exempt detector without its own dedupe now repeats once a day, and after the next release every standing line prints once (key format change). Merge 864864ba. Moved to testing by main-agent@ai-maestro-janitor.
2026-10-07: shipped in v3.8.4; release observation starts.

## Corrections

2026-10-05 (review): this dedupe was introduced by TRDD-7ZMQSXO6 (archived, complete, 2026-09-16), whose criterion was that a line surfaced in the immediately preceding fire is not repeated in the next one; its log records the seen file as append-only with a known ceiling. Suppression for ever goes beyond that criterion; this card is the follow-up, not a duplicate. The table in the report has sixteen rows, not about a dozen. 'Six error texts will never be logged again' is a reading of the seen file and of the code, not an observed loss. Leftover seen files of things that no longer run, to remove when this is fixed: host-load-seen.txt (the detector is unregistered, TRDD-8524H5V1) and marketplace-refresh-failing-seen.txt (the detector was retired 2026-09-17). The findings on this card are from a fork's report; the session checked only that the function has no forget.
2026-10-05 (second review): TRDD-7ZMQSXO6 was completed on 2026-09-17; 2026-09-16 is the day its dedupe landed.
2026-10-06: the memory guard's alert key, named in the body as related, is fixed by removing its deduplication (485596ca, TRDD-BZ3BT0NJ). Its seen file memory-guard-alert-seen.txt in the machine-wide state folder is now a leftover that nothing reads, to remove with the two others listed above. That fix is specific to a branch that runs rarely; it is not the general rule this card still needs.
2026-10-07: detector read-only check (emit_once/emit_forget), result: stale-index-lock and system-daemon-runaway are fixed (self-dedupe with per-key forget verified: stale-index-lock keys removed/no-probe/error/no-snapshot forgotten at scripts/detectors/stale-index-lock.py:97-100 when the lock is gone; system-daemon-runaway key runaway forgotten at system-daemon-runaway.py:188,236,249). oauth-login-needed: stuck-<kind>-<detail> fixed (forgotten at oauth-login-needed.py:225 via _forget_resolved_stuck, called at 253 and 426); but keys due-<day>-<sig> (:287), stalled-<day>-<sig2> (:341) and topup-<day> (:468) have no forget, so a condition that clears and recurs the same day with the same signature stays silent until the next day, still silent until the day rolls over for those keys - not forever, follow-up needed if same-day re-alarm is wanted. trdd-cross-card-blindspot: GAP, keys blindspot@<ref>@<a>@<b> (:346) and blindspot-content@<a>@<b>@<words> (:365) are forgotten only for pairs dropped by the display cap (:379), never when a pair is cross-linked and later un-linked, so still silent forever for those keys - follow-up needed.
2026-10-07: a3583bbf listed in implementation-commits was reverted by 876296de.

## Implementation notes

2026-10-07: trdd-cross-card-blindspot's never-forgotten pairs are fixed on main by TRDD-61PLV7WS (merge 6e623375), shipping in the next release; removing it from _SELF_DEDUPING_DETECTORS is blocked: fastedit cannot target a module-level constant, plain edits not authorised (owner asked 2026-10-07).
2026-10-07: CORRECTION to the line above: TRDD-61PLV7WS (merge 6e623375) makes trdd-cross-card-blindspot forget cleared pairs, so it now meets the exemption contract and stays in _SELF_DEDUPING_DETECTORS; the earlier 'silent forever' note for it is fixed on main, shipping in the next release.
2026-10-07: correction: TRDD-61PLV7WS (merge 6e623375) makes trdd-cross-card-blindspot forget cleared pairs, so it now meets the exemption contract and stays in _SELF_DEDUPING_DETECTORS; nothing needs removing, and the line above saying its removal is blocked is superseded.
