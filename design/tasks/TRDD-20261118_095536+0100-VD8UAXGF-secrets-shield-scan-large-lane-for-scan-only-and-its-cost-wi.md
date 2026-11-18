---
trdd-id: VD8UAXGF
title: secrets-shield-scan large lane for scan-only and its cost, with a memory-based default cap
column: todo
status: tasked
created: 2026-11-18T09:55:36+0100
updated: 2026-11-18T10:07:14+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T09:55:36+0100
parent-trdd: BAQB9SYO
---

# secrets-shield-scan large lane for scan-only and its cost, with a memory-based default cap

Split out of TRDD-BAQB9SYO on 2026-11-18. Three parts. (1) Design change, not a bug: by spec R8, a scan without --redact keeps the over-size skip for text files over --max-file-mb (64 MiB), and only --redact has the large lane (scripts/shield_scan/scan.ts lines 327-328, fileset.ts line 145). Each such file is a recorded skip, but a plain scan therefore leaves large files unread. On the owner code folder an estimate counts about 684 files of 64 MiB to 1 GiB (91 GiB) with no known binary extension and 20 JSONL files of that size (2.4 GiB), outside dependency and build folders; it sorts by extension and folder name, not by the scanner NUL probe, and the walk hit 168 unreadable entries. Change R8 so scan-only has the large lane too. (2) The large lane runs one file at a time and its rate on plain text is not measured: measure it on copies of real large files (at most 4 GB in all) and fix the cost found. (3) Set the --max-large-mb default from os.totalmem(): a redact worker on a 199 MB transcript was sampled at about 5 GiB of resident memory.

## Approval log

- 2026-11-18T09:55:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Progress

- Correction of the estimate in part (1), 2026-11-18T10:05:00+0100, by main-agent: the 684 files (91 GiB) came from extension and folder names only. A find of the files of 64 MiB to 1 GiB outside dependency, build and VCS folders lists 936 files (149.23 GiB). For the 580 of them with a text-like extension or with none, file --mime-type (libmagic) reports 353 text files of 36.0 GiB: SVG 209 files 20.09 GiB, text/plain 115 files 12.60 GiB (txt 45, bak 30, json 19, py 10, ts 5, go 5, sql 1), JSONL 18 files 2.30 GiB, and 11 files of 1.01 GiB typed as Java, C or HTML (.ts, .rs, .bak and .html names). The other 227 are binaries or video of 26.0 GiB: every one of the 222 large files with no extension (Mach-O 205 files 22.24 GiB, PIE executables 16 files 1.17 GiB, one MP4), and 5 of the 13 .ts files (MPEG transport stream). So a scan-only large lane would read about 36 GiB of text on that folder, not 91 GiB. JSONL: the find counts 18 files, the lane estimate 20; the gap is not reconciled. One run, on this host; data in reports_dev/main-agent/lanes/ (gitignored).
- Follow-up to the correction above, 2026-11-18T10:20:00+0100, by main-agent: (a) the 36.0 GiB covers only the 580 probed files; the other 356 files of the find (87.2 GiB) have media, database, archive, document or library extensions (mp4, duckdb, zip, mkv, pdf, rlib, avi, mov, bin and smaller ones), except 2 .ndjson files (0.14 GiB), 1 .ndjsonl file (0.09 GiB) and 3 files of 0.23 GiB with the unknown extensions before, af and 11, none of them probed. The scanner reads .jsonl and .ndjson as JSONL (jsonl.ts line 37), so the 2 .ndjson files are most likely the gap between the 18 JSONL files of the find and the 20 of the lane estimate. (b) libmagic file --mime-type is not the scanner binary test (a NUL in the first 8192 bytes); the two can disagree on a file. (c) Correction of part (3) of the body: the 5 GiB is a ps sample of one long-lived redact worker during a run whose largest file was 199 MB; a worker handles several files, so the figure is the process high-water mark, not the memory of that one file.
