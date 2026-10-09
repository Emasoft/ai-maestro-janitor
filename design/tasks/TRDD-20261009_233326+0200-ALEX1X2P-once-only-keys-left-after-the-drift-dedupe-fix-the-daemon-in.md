---
trdd-id: ALEX1X2P
title: Once-only keys left after the drift dedupe fix — the daemon inbox error log, three oauth-login-needed day keys and three leftover seen files
column: todo
status: tasked
created: 2026-10-09T23:33:26+0200
updated: 2026-10-09T23:33:26+0200
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
