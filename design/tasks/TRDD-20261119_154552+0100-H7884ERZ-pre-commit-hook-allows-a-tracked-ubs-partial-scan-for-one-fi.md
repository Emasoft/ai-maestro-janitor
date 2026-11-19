---
trdd-id: H7884ERZ
title: Pre-commit hook allows a tracked ubs partial scan for one file and one detector
column: todo
status: tasked
created: 2026-11-19T15:45:52+0100
updated: 2026-11-19T15:47:21+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-19T15:45:52+0100
---

# Pre-commit hook allows a tracked ubs partial scan for one file and one detector

## Approval log

- 2026-11-19T15:45:52+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Owner ruling

- 2026-11-19T15:47:20+0100 — the owner answered the question about the rotator commit block with: "Narrow tracked exemption (Recommended)". The option text it chose: "Add one tracked entry: the file rotator.py, the detector sql_injection, and the reason. The hook allows exit 2 only when the unfinished part matches that entry and the staged diff changes no line at or after the limit site. Any other partial scan still blocks. A worker implements it with tests, on its own card."

## Problem

- Since ubs 5.5.26 (the memory corpus records 5.4.17 earlier), the sql_injection detector ends partial on scripts/oauth_rotator/rotator.py: 'SQL list mutation capability escapes', raised for the bound method failure_cause.append passed as a callback at rotator.py:3050 (HEAD 3049) in a file holding one SQL sink, a constant SELECT at 3175. git-hooks/pre-commit has no case for ubs exit 2, so its *) branch blocks every commit that stages rotator.py; the HEAD blob fails the same way. The ubs version change is the likely cause; not proven.

## Requirement

- A tracked allow file (one entry per line: path, detector name, anchor text that locates the limit site, reason). In the hook, an explicit exit-2 case: re-run ubs per staged .py file (HEAD blob and staged blob in two sibling directories with the same relative path); a file whose run is partial passes only when (a) an entry matches its path and every partial detector message names that entry's detector, (b) the HEAD blob is partial with the same detector, and (c) git diff --cached -U0 of the file touches no line at or after the anchor line in HEAD numbering. Every other exit-2 case blocks as now, printing which file and detector were not scanned. A passing case prints that the file is unscanned by that detector after the anchor. Tests: an exempt file partial before and after with a diff above the anchor passes; a diff at or after the anchor blocks; a partial file with no entry blocks; a different detector blocks.

## Known consequence

- The B110 site at rotator.py:3600 (lane R4) lies after the anchor, so under this rule it stays blocked; the 6 batch 7 sites (lines 76 to 1669) and the B110 at 1273 and B105 at 127 lie before it.
