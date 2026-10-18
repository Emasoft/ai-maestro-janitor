---
trdd-id: DQ4H847Z
title: memorize-nudge treats every same-named file as covered once any note names one
column: backburner
status: tasked
created: 2026-10-18T08:22:25+0200
updated: 2026-10-18T08:22:25+0200
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
approval-datetime: 2026-10-18T08:22:25+0200
---

# memorize-nudge treats every same-named file as covered once any note names one

scripts/detectors/memorize-nudge.py _changed_modules (about :242-259) keys modules by basename (Path(f).name), and the covered check matches a note text containing name.ext or stem.ident. So mod.rs, __init__.py, cli.py or main.rs count as covered for every file of that name once any LOCAL/PROJECT note names one of them, and same-named files merge into one entry. Found by the MEASURE pass on TRDD-XOSC5AI5 (2026-10-18), not fixed there. Fix sketch: key by repo-relative path and match in notes either that path or a suffix of it carrying at least one directory (a bare basename is the collision itself); measure how many modules covered today become uncovered before shipping, since stricter matching raises the nudge's volume; a test with two same-named files where only one is described must report the other uncovered. Impact unmeasured, judged low: the nudge is an advisory LOW finding, and the defect only drops modules from it (false negatives).

## Approval log

- 2026-10-18T08:22:25+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
