---
trdd-id: PB64KE0C
title: the privacy scan also checks commit messages for local paths
column: todo
status: tasked
created: 2026-11-04T04:59:00+0100
updated: 2026-11-04T05:03:43+0100
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

Found 2026-11-04 during TRDD-Q6LPJTPO. Commit c502b553 landed with a stale scratch-file error line as its message. That line carries a full machine-local scratchpad path: the macOS uid folder, the drive name and a session id. The pre-commit privacy scan blocked a plugin-and-marketplace id in the staged diff minutes earlier, but it checks only the diff, never the message, so the path went in unchallenged. The message file was not rewritten (fastedit create refused because the file already existed) and the command chain ran the commit anyway, so any agent whose message-file write is refused while the commit still runs can commit a leftover file the same way.

## Done when
- [ ] a commit-msg hook in git-hooks/ (installed via core.hooksPath) checks the message with the SAME rule set as the existing pre-commit privacy scan, so the two cannot drift: home paths, /private/tmp and /var/folders paths, hostnames, and e-mails outside users.noreply.github.com
- [ ] it refuses a message whose first line starts, at its very first character, with fatal:, error: or usage: (so `fix: error: ...` passes)
- [ ] a test commits through the hook with each case and with a clean message
- [ ] publish.py's pre-push gate runs the same check over the commits it is about to push, because --no-verify skips a commit-msg hook; already-pushed history is out of scope, and an unpushed commit the owner has explicitly accepted is allowed by SHA

## Notes

The message check inherits the pre-commit scanner's plugin-and-marketplace id false positive tracked in TRDD-WQDCZEBT; fix or account for that first. The owner's decision on rewording c502b553 must come before item 4 lands, or the new gate refuses the next publish on that commit.

## Approval log

- 2026-11-04T04:59:00+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-04T05:03:43+0100 — column → todo by main-agent@ai-maestro-janitor.
