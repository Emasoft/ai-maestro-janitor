---
trdd-id: G14LKPEC
title: Env dumps Bash guard, live-value matcher and agent-folder sweep for issue 354
column: todo
status: tasked
created: 2026-11-15T23:02:40+0100
updated: 2026-11-15T23:02:40+0100
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
approval-datetime: 2026-11-15T23:02:40+0100
---

# Env dumps Bash guard, live-value matcher and agent-folder sweep for issue 354

Issue Emasoft/ai-maestro-janitor#354. Delivers: Bash guard for commands that print a process environment (opt-in hook), shared secret-name test, janitor_env helper, report-only detector env-secret-on-disk (CRED-002). Deferred, owner decisions: in-place redaction, Rust Aho-Corasick, shield needles (blocked on 2V7OAUPE), saved-login needles (rotator freeze), moving pat/cookie/oauth/bearer/key into the shield (Q6LPJTPO), enabling pre_bash_safety by default. Related: Q6LPJTPO 11KWFU5L 119JBB8C 0Y3UW1NF M1218EMH 2V7OAUPE.

## Approval log

- 2026-11-15T23:02:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
