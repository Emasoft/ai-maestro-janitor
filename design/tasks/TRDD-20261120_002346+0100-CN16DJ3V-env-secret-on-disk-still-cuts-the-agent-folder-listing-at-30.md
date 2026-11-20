---
trdd-id: CN16DJ3V
title: env-secret-on-disk still cuts the agent-folder listing at 30 s and reads nothing there
column: todo
status: tasked
created: 2026-11-20T00:23:46+0100
updated: 2026-11-20T00:23:46+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-20T00:23:46+0100
---

# env-secret-on-disk still cuts the agent-folder listing at 30 s and reads nothing there

2026-11-20 heartbeat stdout (verbatim): '[env-secret-on-disk] the listing of the agent folders took over 30 s and was cut: no agent-folder file was read this pass and the covered range did not move (TRDD-ZANQ1QW0). A tree this large needs a bigger LISTING_BUDGET_S or fewer files under the agent folders.' TRDD-ZANQ1QW0 (archived complete) bounded the walk, but on this host the listing itself never finishes, so agent folders are never scanned: a coverage hole for the secret detector. The agent folders are defined in scripts/lib/env_secrets.py agent_writable_roots (:233-250, read 2026-11-20): reports, reports_dev, .janitor, the non-batch children of .trashcan, every *_dev folder, and the Claude Code session scratch folder /tmp/claude-<uid>/<project>; NOT the git worktrees. Cause UNMEASURED; hypothesis: one of these roots holds very many files (reports_dev and the session scratch folder grow with every worker run). Needed: measure the file count and listing time per root first; then bound the listing per root with a cursor so a partial listing still advances coverage, and decide per root whether bulky regenerable subtrees may be skipped.

## Approval log

- 2026-11-20T00:23:46+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
