---
trdd-id: 8COB99QQ
title: memgrep update-mem-atom with piped stdin reports success but writes nothing
column: todo
status: tasked
created: 2026-10-06T21:25:57+0200
updated: 2026-10-06T22:04:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:57+0200
implementation-commits: [84541ac7, 6f45acf8]
---

# memgrep update-mem-atom with piped stdin reports success but writes nothing

Source: GitHub issue Emasoft/ai-maestro-janitor#322 (opened 2026-09-29). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Piping a new body into update-mem-atom prints an updated message and exits 0, yet the file is unchanged, because stdin is ignored unless a body flag is given. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

landed on main as 84541ac7,6f45acf8; ships in the next release; issue stays open until then.
