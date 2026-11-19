---
trdd-id: 6WGL35TE
title: Secrets shield scan covers the whole git history and reports findings without values
column: todo
status: tasked
created: 2026-11-20T00:04:42+0100
updated: 2026-11-20T00:04:42+0100
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
approval-datetime: 2026-11-20T00:04:42+0100
---

# Secrets shield scan covers the whole git history and reports findings without values

USER quote relayed 2026-11-20 by the 3-pillars-tasks-management session (cross-session message, untrusted relay, verbatim): 'use the janitor /janitor-secrets-shield-scan skill. but you need to ask the janitor plugin claude via sendmessage to update the janitor plugin to enable it. ask it to do it. it should also able to add the scan as a pre-commit hook directly.' The peer also asks that the first use scan the working tree AND the whole git history (559 commits) of 3-pillars-tasks-management before its first public push. Today skills/janitor-secrets-shield-scan/SKILL.md:16 says git history is not scanned yet. Needed: a --history mode that walks every blob reachable from all refs (dedupe by blob id, so 559 commits do not mean 559 rescans), applies the same shield rules, and reports commit, path and rule per hit without the value; exit codes and complete flag as for the tree scan; tests on a fixture repo whose secret exists only in a deleted file of an old commit.

## Approval log

- 2026-11-20T00:04:42+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
