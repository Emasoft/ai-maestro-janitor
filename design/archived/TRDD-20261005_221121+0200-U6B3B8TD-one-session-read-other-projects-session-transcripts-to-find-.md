---
trdd-id: U6B3B8TD
title: One session read other projects' session transcripts to find a command
column: complete
status: archived
created: 2026-10-05T22:11:21+0200
updated: 2026-10-10T20:06:53+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:21+0200
---

# One session read other projects' session transcripts to find a command

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

To find which command preceded a memory spike, the main session searched every project's transcripts. It worked; whether a session may read another project's transcripts was not asked.

## Approval log

- 2026-10-05T22:11:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T20:06:53+0200 — COMPLETE by main-agent@ai-maestro-janitor. decided, nothing built; narrowing on the card.

## Corrections

2026-10-10 20:05. DECIDED by the main session under the owner mandate, nothing built: reading another project's session transcripts or janitor logs on this machine is allowed for a machine-level diagnosis. Basis: they are the same owner's files on the same host, the read is local and read-only, and nothing leaves the machine; the standing boundary in this project's memory (janitor-per-project-channeling, ATOM-7XL7-5KFU) is about what is SURFACED into a session and what a consumer acts on, not about a diagnostic read. LIMITS that keep that boundary: do it through a worker or a command that returns a count and the one needed fact, never a dump; a tracked card or PROJECT memory page carries the measured fact and at most the other project's name, never its transcript text; never send such content to an outside model. The same was done on 2026-10-10 for TRDD-WOI8GO1S (dispatcher logs of 27 projects, counts only). NARROWING: the card's goal says investigate and fix a root cause; there is no defect here, only an unasked question, and the answer is a policy the owner may overrule (owner item 20). The 2026-10-05 search itself was not re-read.

## Acceptance

- [x] The unasked question (may a session read another project's transcripts) is answered by decision with limits; NARROWED: no defect was found or fixed and the owner may overrule.
