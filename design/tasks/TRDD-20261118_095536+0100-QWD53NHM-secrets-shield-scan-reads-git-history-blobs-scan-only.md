---
trdd-id: QWD53NHM
title: secrets-shield-scan reads git history blobs, scan only
column: todo
status: tasked
created: 2026-11-18T09:55:36+0100
updated: 2026-11-18T09:55:36+0100
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
approval-datetime: 2026-11-18T09:55:36+0100
parent-trdd: BAQB9SYO
---

# secrets-shield-scan reads git history blobs, scan only

Increment 1b of TRDD-BAQB9SYO, split out on 2026-11-18. Add the git-history option of the Design of TRDD-BAQB9SYO: scan only, over the blobs reachable from all refs through git cat-file, read-only, never redacted (owner, 2026-11-17, verbatim in TRDD-BAQB9SYO: "note that git history redaction is complex. it can broke in progress merge resolutions, add conflicts, corrupt or lose synch with upstream, etc."). As the Design says, each finding gives the secret type, the path and the line, and the blob id for history. Tests: in a fixture repo, a secret committed and then deleted is found with its blob id, and the working tree and the refs are unchanged.

## Approval log

- 2026-11-18T09:55:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
