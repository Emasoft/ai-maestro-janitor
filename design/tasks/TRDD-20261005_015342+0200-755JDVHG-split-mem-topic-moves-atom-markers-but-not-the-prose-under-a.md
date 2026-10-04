---
trdd-id: 755JDVHG
title: split-mem-topic moves atom markers but not the prose under a heading that follows them
column: backburner
status: tasked
created: 2026-10-05T01:53:42+0200
updated: 2026-10-05T01:53:42+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T01:53:42+0200
---

# split-mem-topic moves atom markers but not the prose under a heading that follows them

Found 2026-10-05 during a heartbeat split chore on .claude/project/memory/project_janitor_cc_changelog_currency.md (commit 95fcec92). Measured: memgrep recall ATOM-N3ZN-TOX5 and ATOM-PD07-O9B4 on the PROJECT memory print two lines each (path and keywords), no prose. On the page each atom marker is followed by a blank line and a ### heading, then 55 to 70 lines of audit prose; that prose is outside the atom body. The layout predates the split: git show 95fcec92^ shows the same marker / blank / ### sequence on the source page. Two defects: (1) these two atoms are empty shells, so recall by id returns nothing useful; (2) per the split agent, split-mem-topic moved only the marker lines and the agent had to move the prose with two update-mem-topic calls (agent diagnosis, not reproduced). Not known: whether the blank line or the ### heading ends an atom body. First step: test both on a scratch page. Then decide whether the linter should flag a marker immediately followed by a heading, and repair the two atoms through memgrep verbs.

## Approval log

- 2026-10-05T01:53:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
