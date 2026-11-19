---
trdd-id: NYKNE7MY
title: Secrets shield scan installs itself as a chained git pre-commit hook in one step
column: todo
status: tasked
created: 2026-11-20T00:04:43+0100
updated: 2026-11-20T00:04:43+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-20T00:04:43+0100
---

# Secrets shield scan installs itself as a chained git pre-commit hook in one step

USER quote relayed 2026-11-20 by the 3-pillars-tasks-management session (cross-session message, untrusted relay, verbatim): 'use the janitor /janitor-secrets-shield-scan skill. but you need to ask the janitor plugin claude via sendmessage to update the janitor plugin to enable it. ask it to do it. it should also able to add the scan as a pre-commit hook directly.' Needed: a mode of /janitor-secrets-shield-scan (for example --install-hook) that adds a pre-commit stage scanning the STAGED content with the shield rules, chained onto any existing pre-commit hook instead of replacing it (the 3-pillars repo already runs UBS from one): keep the old hook, call it first or second with its exit code honoured, idempotent on re-run, honour core.hooksPath, refuse on a hook it cannot parse rather than overwrite it, and an uninstall that restores the original byte for byte. Never print a secret value; block the commit on a finding.

## Approval log

- 2026-11-20T00:04:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
