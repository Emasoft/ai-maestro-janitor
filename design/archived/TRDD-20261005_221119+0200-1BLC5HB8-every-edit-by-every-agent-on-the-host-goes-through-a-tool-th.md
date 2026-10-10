---
trdd-id: 1BLC5HB8
title: Every edit by every agent on the host goes through a tool that may load a local model
column: complete
status: archived
created: 2026-10-05T22:11:19+0200
updated: 2026-10-10T18:21:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:19+0200
release-via: none
---

# Every edit by every agent on the host goes through a tool that may load a local model

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The standing rule sends all edits through fastedit. With twenty or more sessions and their workers, several model-sized processes run at once. Measure the real concurrency and memory, and report it to the owner of the rule.

## Approval log

- 2026-10-05T22:11:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T18:21:46+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Corrections

2026-10-10 18:21. MEASURED, no code (wave 14 card 4). (1) SAMPLE: ps every 20 s from 17:04:56 to 18:20:58 on 2026-10-10 (225 samples, reports/board/fastedit-concurrency-20261010.tsv): 0 samples held a fastedit process, with about 27 processes matching 'claude' on the host at the end. The pattern was proven afterwards on a real process (another project's agent running fastedit edit, resident 35 MB at that instant). (2) WATCH LOG: the daemon's process-size watch logged 8 fastedit processes above its 16 GB footprint ceiling between 2026-10-07 18:54 and 2026-10-10 11:32 (footprint 16.4 to 19.8 GB, resident 1.8 to 2.1 GB); the closest two are 99 s apart (2026-10-07 22:47:22 and 22:49:01) and whether they overlapped is not recorded. (3) From TRDD-DKID2PYP: one ordinary generating edit of a small file peaked at 4.8 GB footprint and 4.5 GB resident. READING: on this evidence fastedit processes are short and rarely coincide; the host has 64 GB, so three ordinary model-loading edits at once fit and thirteen would not; no sample shows more than one. LIMITS: a Saturday evening, 76 minutes, one host; a 20 s interval misses any run shorter than that, which is most anchor and insert edits and possibly many model edits; resident memory only (footprint, the figure the watch uses, was not sampled); concurrency on a working day with twenty sessions is NOT measured. DECISION: no change to the rule and no code; the figures are reported to the rule's owner as owner item 19 on TRDD-S6GX1DHN. A longer sample belongs to TRDD-DKID2PYP, which already owns the question of what the 16 GB detections are.

## Acceptance

- [x] Concurrency and memory measured and reported to the owner of the rule. NARROWED: one 76-minute evening sample at 20 s (0 processes seen) plus three days of the watch's over-ceiling lines (8, none shown to overlap); working-day concurrency is not measured.
