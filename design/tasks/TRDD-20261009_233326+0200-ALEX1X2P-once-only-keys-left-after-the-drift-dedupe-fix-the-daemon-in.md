---
trdd-id: ALEX1X2P
title: Once-only keys left after the drift dedupe fix — the daemon inbox error log, three oauth-login-needed day keys and three leftover seen files
column: testing
status: tasked
created: 2026-10-09T23:33:26+0200
updated: 2026-10-11T02:00:36+0200
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
implementation-commits: [c2799b35]
---

# Once-only keys left after the drift dedupe fix — the daemon inbox error log, three oauth-login-needed day keys and three leftover seen files

Follow-up of TRDD-37H7QFSF (closed 2026-10-09), which bounded the dispatcher's own line dedupe to one local day and exempted the self-deduping detectors. Three items it named and did not do: (1) the daemon's notification inbox error log uses the same once-only key with no forget, so an error text logged once is never logged again (read in the code only, no observed loss); (2) in scripts/detectors/oauth-login-needed.py the keys due-<day>-<sig>, stalled-<day>-<sig2> and topup-<day> have no forget, so a condition that clears and recurs the same day with the same signature stays silent until the day rolls over; decide whether a same-day re-alarm is wanted before changing them; (3) three seen files that nothing reads any more remain in the machine-wide state folder: host-load-seen.txt, marketplace-refresh-failing-seen.txt, memory-guard-alert-seen.txt. They are outside the project tree, so removing them needs the owner's word. Also missing: a test that every detector in _SELF_DEDUPING_DETECTORS actually calls emit_forget (today's test checks membership only).

## Approval log

- 2026-10-09T23:33:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-11T01:41:21+0200 — column → dev. item 1 fix and the roster test in build by one worker
- 2026-10-11T02:00:36+0200 — column → testing. fix committed in c2799b35; field proof waits on a release

## Findings

2026-10-11 00:52 (clock). READ IN CODE by the main session, nothing built (git log on scripts/detectors/oauth-login-needed.py run first: last change cc8ce274, not about its keys). (a) THE MISSING TEST AS WORDED WOULD BE WRONG: of the six names in dispatch._SELF_DEDUPING_DETECTORS, five call dedupe.emit_forget (host-load, oauth-login-needed, stale-index-lock, system-daemon-runaway, trdd-cross-card-blindspot); memgrep-binary-stale does not and needs none, since its key is (reason, stamp, installed sha), so a new occurrence has a new key (its own comment at line 146 says so). The existing test (tests/test_dispatch_phases.py, test_every_self_deduping_detector_is_on_the_roster_and_uses_emit_once) checks the roster and the word emit_once only. A correct test: each name either calls emit_forget or is on a short list of detectors whose key changes with the occurrence, each with its reason. (b) Item 2 confirmed: oauth-login-needed.py lines 288, 342 and 452 use keys due-<day>-<sig>, stalled-<day>-<sig2>, topup-<day> with no forget; its one emit_forget (line 226) serves another key. Whether a same-day repeat is wanted is still undecided. (c) Items 1 and 3 not looked at. Card stays in todo.
2026-10-11 01:00 (clock). READ AFTER THE REVIEW of ff0e3b8c, both claims of the line above now rest on code: memgrep-binary-stale.py emits two keys, 'stale:<stamp>:<sha>' (line 175) and 'cant-tell:<why>:<stamp>:<sha>' (line 148), both carrying the build stamp and the installed commit, so no forget is needed; oauth-login-needed.py's one emit_forget (line 226, _forget_resolved_stuck) clears every key of .oauth-rotation-stuck-seen.txt, the file of a FOURTH alarm (key 'stuck-<kind>-<detail>', line 392), not of the three day-keys. That each of the other four detectors' forget call clears its own alarm key was read for host-load and system-daemon-runaway only.
2026-10-11 01:41. DECISIONS and build. Item 1 CONFIRMED in code (scripts/daemon.py task_gh_notify_inbox): the fetch-error key in gh-notify-inbox.err.seen is never forgotten, so an error logged once is never logged again after a recovery; fix in build (forget the keys on a successful fetch), test first. Item 2 DECIDED, no change: the three day-keys of oauth-login-needed stay as they are; a login alarm that clears and returns the same day with the same accounts is the same alarm, and the owner rule is to warn once, not to repeat a line (TRDD-0NWG4LKJ); the day roll-over is the re-alarm. Item 3 DECIDED, no act: the three unread seen files in the machine-wide state folder are left in place; they are inert, outside the project tree, and removing them is the owner's call. The roster test is being corrected as written in the 00:52 line (emit_forget, or a named exception with its reason).
2026-10-11 02:00. BUILT, committed alone in c2799b35 (worker diff read by the main session; reviewed, no blocker). Item 1: a successful fetch forgets every key of gh-notify-inbox.err.seen; the read catches ValueError beside OSError (review finding, added after the gate; re-checked with the two daemon test files, ruff, mypy, pyright). TRADE-OFF: a fetch that flaps logs once per failure, no longer once ever. The real seen file on this host holds keys from 2026-10-09 and is cleared by the first successful fetch after a release. Roster test: each self-deduping detector calls emit_forget or is a named exception (memgrep-binary-stale only); it checks a word in the source, not behaviour, and that each forget clears its own alarm key was read for two of five detectors. Full gate on the tree holding both fixes: 18384 passed, 2 skipped; ruff, mypy, pyright clean (reports/board/gate-alex-2uv.txt). The worker edited with a python rewrite against the editing rule; the diff was read in full. FIELD CHECK after a release: global-state/daemon.log shows a second gh-notify-inbox fetch failed line with the same text after a published line between them.
