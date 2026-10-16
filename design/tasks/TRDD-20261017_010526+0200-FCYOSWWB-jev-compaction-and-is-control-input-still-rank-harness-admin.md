---
trdd-id: FCYOSWWB
title: Jev compaction and is_control_input still rank harness-admin commands as owner items
column: testing
status: tasked
created: 2026-10-17T01:05:26+0200
updated: 2026-10-17T01:30:33+0200
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
approval-datetime: 2026-10-17T01:05:26+0200
implementation-commits: [a8014587]
---

# Jev compaction and is_control_input still rank harness-admin commands as owner items

Split from TRDD-2UV4BBHP (b271c935). transcript_roles.is_control_input, used by external_clear.py:580,598 and jev_compaction.py:614, does not use is_non_instruction_command, so an owner-typed /login, /model or /plugin enable ... is still ranked as an owner item in the Jev-compacted copy and the external-clear digest, with the same slot-displacement effect fixed in session_continuity. To do: decide whether is_control_input should also return True for is_non_instruction_command (its control-word branch for resume/continue must stay), measure on real compacted copies, test.

## Approval log

- 2026-10-17T01:05:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-17T01:29:49+0200 — BUILT in a8014587: is_control_input now also returns True for is_non_instruction_command, so /login, /model, /plugin (wrapped, or a raw single-line queued /admin-name) are kind control in Jev compaction (verbatim, out of the owner tier, digest and newest-owner pick) and dropped from the external-clear digest tail. Meaning widened from content-free to content-free or not an instruction; session_continuity keeps calling is_non_instruction_command directly so a bare resume stays carried. Raw branch is REASONED from the queued /ponytail shape; no queued admin command observed. Accepted risk: a raw plain-text prompt starting with an admin name would be dropped. Measured before: 4 of 113 owner items in 56 transcripts were admin wrappers. 6 tests failed first, 342 pass; ruff, mypy, pyright clean. FIELD CHECK: the next compacted copy whose source has an admin command shows it outside the owner tier.
- 2026-10-17T01:30:30+0200 — CORRECTION to a8014587's commit message: it says the extra blank lines in the three test files were left because fastedit cannot trim them cleanly; that is wrong (fastedit edit --lines N:N --delete removes them). They were skipped as cosmetic; ruff passes. Remove them in the next commit that touches those files.
