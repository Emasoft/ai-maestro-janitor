---
trdd-id: 7T4J5T6Z
title: The rotator's stuck marker restarts its first-seen time on every tick so the measured duration is always zero
column: testing
status: tasked
created: 2026-10-05T22:08:48+0200
updated: 2026-10-10T15:00:09+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:48+0200
---

# The rotator's stuck marker restarts its first-seen time on every tick so the measured duration is always zero

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed: a marker read during a stuck episode had first_seen_epoch equal to last_seen_epoch. From reading the code, on a tick that works from the mirror copy the marker is cleared when the beacon fingerprint matches and written again at the end of a still-stuck tick, so on mirror-sourced ticks first-seen never accumulates. Consequences to verify: the detector that reports 'rotation impossible for N hours' can never reach its hours; the alert reader only tests that the file exists and has no check on the marker's age, so a marker left by a rotator that stopped ticking would alert forever. Also seen: the kind all-accounts-maxed is written for a token that is only close to its expiry.

## Approval log

- 2026-10-05T22:08:48+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Implementation notes

2026-10-07 — wording corrected per the 2026-10-05 review recorded on TRDD-P9D6QWMU ('first-seen never accumulates' to 'first-seen never accumulates on mirror-sourced ticks only'); the correction was not re-measured.
2026-10-10 15:00, wave 9 card 3, built in the commit that carries this line. CONFIRMED by reading: the two identity-resolution call sites in _resolve_untrusted_live deleted a marker of any kind, so on a tick that reads the mirror an all-accounts-maxed marker was deleted and rewritten and its first-seen time never accumulated; the alert reader only tested that the file exists. CHANGE: _clear_stuck takes only_kinds and those two callers pass the two identity kinds; _mark_stuck inherits first-seen only from a same-kind marker seen within the last hour (found by the review of the brief: otherwise a marker outliving a recovery would lend its start time to a later episode); rotator_alert reports rotation-stuck only for a marker with a kind and a last-seen within the hour. TESTS: 8 new or changed; before the change the mirror-path test, the stale-prior test and the two alert tests failed for behaviour, two failed only for the missing keyword, one is a control. Worker checks: 257 tests in the three files pass, ruff, mypy, pyright clean (worker-run; the full gate is started after the commit). FIELD CASE UNOBSERVED: today's stuck episode (13:33 to 13:57, 31 stuck lines, 34 mirror lines in rotator.log) left no marker on disk and no ledger entry, so the marker's content during it was not seen. NOT BUILT, known limits: nothing clears the marker when the live account recovers without a rotation, the two one-hour checks bound that; the kind all-accounts-maxed is still written when the alternates are expired, not maxed, which sends the wrong alert text; the detector keeps its own literal 3600; a marker with no kind no longer alerts (the writer always writes one). DETECT after a release: during a stuck episode longer than a few minutes, rotation-stuck.json in the rotator home shows first_seen_epoch earlier than last_seen_epoch.
