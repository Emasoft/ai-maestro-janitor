---
trdd-id: NGLPQ7SW
title: Headless account switch skips filing the outgoing credential into its slot and logs nothing
column: testing
status: tasked
created: 2026-10-06T21:08:38+0200
updated: 2026-10-10T05:15:23+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:08:38+0200
implementation-commits: [595f5094]
release-via: publish
---

# Headless account switch skips filing the outgoing credential into its slot and logs nothing

Found by the 2026-10-06 field check of TRDD-IT5GEZDZ (reports/board/20261006_210400+0200-testing-field-check.md). Two real switches today (17:22:16 and 20:18:14) ran in the daemon with the primary live credential skipped by policy (JANITOR_ROTATOR_HEADLESS) and the -livebak mirror in use. Per the code (rotator.py around lines 2074-2096, read by the field-check worker, not re-read by the main agent), read_live_blob then returns None and the filing step returns early without any log line, so the outgoing credential is never filed and nothing says so. Fail-silent regardless of the policy choice. Fix options for the owner: file from the mirror, or log the skip explicitly; at minimum the skip must be logged. Acceptance: a headless switch either files the slot or logs a line naming the skip.

## Approval log

- 2026-10-06T21:08:38+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 05:15 BUILT in 595f5094 (board drain, wave 4). PREMISE CORRECTED: the body says read_live_blob returns None when headless. Read by the main session: read_live_blob falls back to the -livebak mirror (rotator.py read_live_blob_with_source, about line 962), so a headless read usually returns the mirror copy, and the two silent switches of 2026-10-06 more likely left through the same-token, no-expiry or slot-newer return; WHICH return fired is UNKNOWN. WHAT LANDED: the five skip returns of _mirror_live_to_outgoing_slot each log one line '[switch] <account>: at-switch slot mirror skipped — <reason> (headless: yes|no)'; reasons: no live credential readable; live credential has no access token; slot already current; live credential has no expiry; slot token is newer or equal (with both expiry numbers). Two returns stay silent by design: the tick is not the janitor's, and no outgoing account. No guard, read or write changed; no token, blob or fingerprint is logged (two tests assert it). NOT FIXED, still open: a headless switch files NOTHING when the mirror copy is not newer than the slot; filing from the mirror is what the function's guards refuse and is credential handling, so that choice stays with the owner. CHECKS: worker-run 201 tests in two files, ruff, mypy, pyright; the whole gate on 595f5094 was started by the main session at this time (reports/board/gate-595f5094.txt). PINNING TESTS (tests/test_oauth_rotator.py): the five test_mirror_skip_logged_* tests and test_mirror_skip_logged_as_headless_with_both_expiries_when_the_slot_is_newer fail on the old code; the two test_mirror_is_silent_* tests and the success test are guards that pass on the old code too. FIELD CHECK, after a release with 595f5094 is installed and the daemon restarted: every 'auto: switched' line in the rotator log is preceded by one 'at-switch slot mirror skipped' or 'filed the outgoing live credential' line for the outgoing account; DETECT: grep -c 'at-switch slot mirror skipped\|filed the outgoing live credential' on rotator.log and rotator.log.1 in the plugin data dir's oauth-rotator folder is above 0 while grep -c 'auto: switched' is above 0; the log spans about 9 hours, so check within hours of a switch. On this host the janitor's own daemon runs the rotator tick (it is not among the six chores the daemon log lists as yielded to the server), so the lines will be written here.
- 2026-10-10T05:15:23+0200 — column → testing by main-agent@ai-maestro-janitor. skip logging landed in 595f5094; waits on the gate, a release and a real switch
