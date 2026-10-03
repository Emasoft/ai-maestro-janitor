---
trdd-id: WQDCZEBT
title: Privacy scanner flags plugin at marketplace identifiers as user at host
column: backburner
status: tasked
created: 2026-10-03T04:02:16+0200
updated: 2026-10-03T04:02:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T04:02:16+0200
project-id: ai-maestro-janitor

---

# Privacy scanner flags plugin at marketplace identifiers as user at host

The pre-commit privacy scan (`scripts/lib/staged_privacy_scan.py`, rule `private-path.ssh-user-host`) flagged the public `<plugin>@<marketplace>` identifier of the janitor plugin (the same identifier is written in CLAUDE.md Working rules) as a user-at-host target on 2026-10-03. It forced a paraphrase of a runnable `claude plugin update` command in cards JSQSJ3PZ and K9AHY1ZB.

Fix: allowlist the known plugin-name AT marketplace-name pattern in `_allow_ssh_host` (`scripts/lib/private_path_patterns.py`), so a runnable plugin update command can be written verbatim in a card. No private data in this card.

## Approval log

- 2026-10-03T04:02:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
