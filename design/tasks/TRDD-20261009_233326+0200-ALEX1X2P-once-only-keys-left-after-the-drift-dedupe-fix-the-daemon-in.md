---
trdd-id: ALEX1X2P
title: Once-only keys left after the drift dedupe fix — the daemon inbox error log, three oauth-login-needed day keys and three leftover seen files
column: todo
status: tasked
created: 2026-10-09T23:33:26+0200
updated: 2026-10-11T01:00:39+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T23:33:26+0200
---

# Once-only keys left after the drift dedupe fix — the daemon inbox error log, three oauth-login-needed day keys and three leftover seen files

Follow-up of TRDD-37H7QFSF (closed 2026-10-09), which bounded the dispatcher's own line dedupe to one local day and exempted the self-deduping detectors. Three items it named and did not do: (1) the daemon's notification inbox error log uses the same once-only key with no forget, so an error text logged once is never logged again (read in the code only, no observed loss); (2) in scripts/detectors/oauth-login-needed.py the keys due-<day>-<sig>, stalled-<day>-<sig2> and topup-<day> have no forget, so a condition that clears and recurs the same day with the same signature stays silent until the day rolls over; decide whether a same-day re-alarm is wanted before changing them; (3) three seen files that nothing reads any more remain in the machine-wide state folder: host-load-seen.txt, marketplace-refresh-failing-seen.txt, memory-guard-alert-seen.txt. They are outside the project tree, so removing them needs the owner's word. Also missing: a test that every detector in _SELF_DEDUPING_DETECTORS actually calls emit_forget (today's test checks membership only).

## Approval log

- 2026-10-09T23:33:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-11 00:52 (clock). READ IN CODE by the main session, nothing built (git log on scripts/detectors/oauth-login-needed.py run first: last change cc8ce274, not about its keys). (a) THE MISSING TEST AS WORDED WOULD BE WRONG: of the six names in dispatch._SELF_DEDUPING_DETECTORS, five call dedupe.emit_forget (host-load, oauth-login-needed, stale-index-lock, system-daemon-runaway, trdd-cross-card-blindspot); memgrep-binary-stale does not and needs none, since its key is (reason, stamp, installed sha), so a new occurrence has a new key (its own comment at line 146 says so). The existing test (tests/test_dispatch_phases.py, test_every_self_deduping_detector_is_on_the_roster_and_uses_emit_once) checks the roster and the word emit_once only. A correct test: each name either calls emit_forget or is on a short list of detectors whose key changes with the occurrence, each with its reason. (b) Item 2 confirmed: oauth-login-needed.py lines 288, 342 and 452 use keys due-<day>-<sig>, stalled-<day>-<sig2>, topup-<day> with no forget; its one emit_forget (line 226) serves another key. Whether a same-day repeat is wanted is still undecided. (c) Items 1 and 3 not looked at. Card stays in todo.
2026-10-11 01:00 (clock). READ AFTER THE REVIEW of ff0e3b8c, both claims of the line above now rest on code: memgrep-binary-stale.py emits two keys, 'stale:<stamp>:<sha>' (line 175) and 'cant-tell:<why>:<stamp>:<sha>' (line 148), both carrying the build stamp and the installed commit, so no forget is needed; oauth-login-needed.py's one emit_forget (line 226, _forget_resolved_stuck) clears every key of .oauth-rotation-stuck-seen.txt, the file of a FOURTH alarm (key 'stuck-<kind>-<detail>', line 392), not of the three day-keys. That each of the other four detectors' forget call clears its own alarm key was read for host-load and system-daemon-runaway only.
