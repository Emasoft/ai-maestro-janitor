---
trdd-id: K2PEAYHR
title: TRDD id matcher cannot parse legacy v1 filenames so cards vanish from four detectors
column: todo
status: tasked
created: 2026-10-06T21:25:44+0200
updated: 2026-10-06T21:25:44+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:44+0200
---

# TRDD id matcher cannot parse legacy v1 filenames so cards vanish from four detectors

Source: GitHub issue Emasoft/ai-maestro-janitor#313 (opened 2026-09-26). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The _TRDD_ID_RE pattern in trdd_common.py accepts only two filename shapes and rejects legacy v1 names with a UUID-style middle segment. Such cards have valid frontmatter but are invisible to four detectors. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:44+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
