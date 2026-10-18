---
trdd-id: XOSC5AI5
title: Memory nudges reach no background memory chore
column: todo
status: tasked
created: 2026-10-10T04:55:24+0200
updated: 2026-10-18T03:18:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T04:55:24+0200
parent-trdd: 6ESS2MGE
derived: true
---

# Memory nudges reach no background memory chore

Route 2 of the owner's routing rule of 2026-09-27 (quoted on TRDD-6ESS2MGE): a finding a background agent can fix becomes background work the main agent never sees. Worker-read 2026-10-10 (reports/board/20261010_044453+0200-6ess2mge-detector-table.md): memorize-nudge prints a drift line only; memory-librarian prints a drift line and writes a proposal file in the LOCAL memory dir; scripts/detectors/memory-maintenance.py, the only emitter of the janitor-memory chore markers, reads neither (its docstring says it never reads the corpus). So both findings reach only the main agent, as LOW ledger lines at session start. Unverified: whether a chore skill reads the librarian's proposal file. To do: read the chore skills for a consumer of that file; if none, decide whether the harvest or consolidate chore should take the nudge and the proposal as input, measured on this corpus before building; no new ticket kind without that measurement.

## Approval log

- 2026-10-10T04:55:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Investigation 2026-10-18

MEASURED (worker-read, report docs_dev/20261018_023416+0200-trdd-xosc5ai5-librarian-nudge-readers.md; file:line evidence there): the librarian's proposal file memory-reorg-proposed.md (LOCAL memory dir) has ONE reader, the conflict precheck and chore (scripts/lib/memory_content_precheck.py:1239-1330; skills/janitor-memory-conflict/SKILL.md:68), which read only its Conflict section; its other six sections are display-only. memorize-nudge persists only to the findings ledger (ADVISORY-MEMORIZE-NUDGE, LOW) and no chore reads it: 29 findings in 7.4 days, at least one uncovered-module set recurring (not counted per finding). memory-maintenance.py reads no nudge; its content precheck reads only the proposal's Conflict section (its docstring lines 5-12 say it never reads the corpus, which is slightly inaccurate).
DECISION: no change for the proposal file (its actionable section is already wired). For memorize-nudge the natural consumer is a chore that writes NEW pages from commit messages (commit discipline puts the WHY there), a CANDIDATE being the janitor-memory-record-recent skill as a background chore (only its name was checked: read its input and whether it can run in the background before designing); consolidate and retro-lesson take existing pages and do not fit. NEXT: design that route (input = the nudge's uncovered modules plus their commits; the marker and claim like the other chores), measured on this corpus first, as the card requires; not built yet.
CANDIDATE READ (main session, skills/janitor-memory-record-recent/SKILL.md lines 1-40): record-recent calls itself 'the on-demand counterpart of the memorize-nudge heartbeat'. It finds what changed, recalls first, and hands authoring to janitor-memory-write and janitor-memory-update. It is written for a session that knows its own changes; it is not yet a heartbeat chore (no marker, no claim step). Run in the background it would have only git history and commit messages to work from, which commit discipline says carry the WHY. NEXT (design, not built): decide whether memory-maintenance should emit a record-recent marker when memorize-nudge has fired N times on the same module set, with the claim and close steps the other chores use; measure first how many of the 29 nudge findings name the same set.
