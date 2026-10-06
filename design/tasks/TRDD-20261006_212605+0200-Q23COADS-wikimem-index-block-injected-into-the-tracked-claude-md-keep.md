---
trdd-id: Q23COADS
title: Wikimem index block injected into the tracked CLAUDE.md keeps the file permanently dirty
column: todo
status: tasked
created: 2026-10-06T21:26:05+0200
updated: 2026-10-06T21:26:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:05+0200
---

# Wikimem index block injected into the tracked CLAUDE.md keeps the file permanently dirty

Source: GitHub issue Emasoft/ai-maestro-janitor#328 (opened 2026-10-03). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The session start hook writes an auto-generated index block with a fresh timestamp into the tracked CLAUDE.md, so it always shows as modified and a by-name add sweeps the block into a commit. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
