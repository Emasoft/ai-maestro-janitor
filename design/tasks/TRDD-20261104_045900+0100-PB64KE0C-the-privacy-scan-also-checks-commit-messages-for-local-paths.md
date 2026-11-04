---
trdd-id: PB64KE0C
title: the privacy scan also checks commit messages for local paths
column: backburner
status: tasked
created: 2026-11-04T04:59:00+0100
updated: 2026-11-04T04:59:00+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T04:59:00+0100
---

# the privacy scan also checks commit messages for local paths

Found 2026-11-04 during TRDD-Q6LPJTPO. Commit c502b553 landed with a stale scratch-file error line as its message. That line carries a full machine-local scratchpad path: the macOS uid folder, the drive name and a session id. The pre-commit privacy scan blocked a plugin-and-marketplace id in the staged diff minutes earlier, but it checks only the diff, never the message, so the path went in unchallenged. Any agent whose message file fails to write can commit a leftover file the same way.

Done when:
- [ ] a commit-msg hook (or the existing privacy scan extended to the message) refuses a message containing a home path, a /private/tmp or /var/folders path, a hostname or an e-mail outside users.noreply.github.com
- [ ] it refuses a message whose first line starts with fatal:, error: or usage:
- [ ] a test commits through the hook with each case and with a clean message
- [ ] publish.py's pre-push gate runs the same check over the commits it is about to push.

## Approval log

- 2026-11-04T04:59:00+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
