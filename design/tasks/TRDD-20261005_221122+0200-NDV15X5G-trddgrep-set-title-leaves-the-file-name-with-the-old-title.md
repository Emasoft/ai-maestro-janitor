---
trdd-id: NDV15X5G
title: trddgrep set title leaves the file name with the old title
column: todo
status: tasked
created: 2026-10-05T22:11:22+0200
updated: 2026-10-06T15:11:29+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:22+0200
---

# trddgrep set title leaves the file name with the old title

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

After a title change the slug in the file name still carries the first title. Lookup by id still works. Decide whether the tool should rename.

## Approval log

- 2026-10-05T22:11:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 REPRODUCED on a scratch corpus: `trddgrep set <id> title <new>` rewrote title: and left the file name with the first title's slug (TRDD-…-XLPYKAWC-repro-b.md after retitling to 'repro renamed'). Filed upstream as Emasoft/ai-maestro#171 per the owner's instruction of 2026-10-06. NEXT ACTION: wait for #171; nothing to change in this repo.
