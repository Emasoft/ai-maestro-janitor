---
trdd-id: 7QGRK8RS
title: Memory passes, LOCAL note ownership conflict, missing conflict CLI option, trashcan candidates, atom template
column: todo
status: tasked
created: 2026-11-18T01:25:32+0100
updated: 2026-11-18T01:27:07+0100
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
approval-datetime: 2026-11-18T01:25:32+0100
---

# Memory passes, LOCAL note ownership conflict, missing conflict CLI option, trashcan candidates, atom template

Source: GitHub issue #363 (https://github.com/Emasoft/ai-maestro-janitor/issues/363), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue (five defects in memory passes of 2026-11-15 to 2026-11-17, janitor 3.9.8, memgrep 0.3.0). (1) LOCAL notes are treated both as harness-owned (harvest never modifies them and mirrors them into a new page) and as curator-editable (repair and atomize edit them in place), which produced a duplicate page next to an existing one (both named in the issue); a later comment corrects the count to 14 of 22 LOCAL pages listed in the harness MEMORY.md but the ownership conflict stands. (2) The conflict skill calls memory_candidates_cli.py with --intervention conflict, which the CLI rejects. (3) A same-subject compatible duplicate pair was dispatched as a conflict candidate twice in one evening instead of as a consolidate candidate. (4) The USER repair candidate scan picked up a safe-delete staging copy under .trashcan/ flagged no-frontmatter, and the refusal re-arms after 7 days so it returns. (5) The atomize marker template says type, ocd and lmd are optional, but memgrep lint reports WMATOM-011 and WMATOM-012 for every such atom (6 each today), and the keywords field format (how to separate several terms) is not stated, so a first write was refused until terms were joined with underscores.

## Suspected cause

By the issue, per defect: (1) no single ownership rule for LOCAL pages listed in MEMORY.md; (2) the skill and the CLI choices list disagree; (3) the reorg proposal lists a duplicate pair under conflict candidates; (4) the candidate scan has no .trashcan exclusion; (5) the atomize template disagrees with lint and with the write gate. Expected by the issue: one ownership rule (curator edits in place and harvest does not mirror a corpus page, or read-only to every pass); a working conflict candidate path; same-subject compatible pairs proposed as consolidate; candidate scans skip .trashcan; a template with the dates lint wants and the keyword format the gate accepts.

## Files named by the issue

skills/janitor-memory-conflict/SKILL.md (line 95); skills/janitor-memory-atomize/SKILL.md (lines 93 and 101); scripts/memory_candidates_cli.py; scripts/lib/memory_*.py (memory_migrate.py mentions .trashcan); memory-reorg-proposed.md in the LOCAL corpus; the harvest, repair and atomize passes.

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:32+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
