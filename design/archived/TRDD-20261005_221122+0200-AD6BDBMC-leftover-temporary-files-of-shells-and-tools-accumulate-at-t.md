---
trdd-id: AD6BDBMC
title: Leftover temporary files of shells and tools accumulate at the top of a home folder and nothing notices
column: complete
status: archived
created: 2026-10-05T22:11:22+0200
updated: 2026-10-10T20:07:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:22+0200
---

# Leftover temporary files of shells and tools accumulate at the top of a home folder and nothing notices

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

On one host 38 leftover completion-dump temporary files and several zero-byte temporary copies of a tool's configuration file had accumulated over weeks. zsh writes its completion dump to a temporary name and renames it, so each leftover is a shell that died in between. Decide whether a janitor detector should report such leftovers; the files and the shell configuration are the owner's and are not touched without the owner's word.

## Approval log

- 2026-10-05T22:11:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T20:07:26+0200 — COMPLETE by main-agent@ai-maestro-janitor. decided not to build; measured growth on the card.

## Corrections

2026-10-05 (review): a shell that died between write and rename is one mechanism; two shells racing on the dump would leave the same file. Why the dump is rewritten so often was not measured.
2026-10-10 20:07. MEASURED on the same host: 49 leftover completion-dump files at the top of the home folder (38 on 2026-10-05), 12 of them written since 2026-10-05 23:00, so about 2 to 3 a day; 9 zero-byte dot files. Sizes were not read. DECIDED, no detector: the janitor's detectors report per project into that project's session, and a home-folder leftover belongs to no project; the growth is a few small files a day with no observed harm; removing them is the owner's act. INFERRED, not measured: the agents' tool shells start from the user's profile and so run the completion setup, and a shell killed by a timeout mid-write leaves a dump; the 2026-10-05 review's second mechanism (two shells racing) is equally unexcluded. NARROWING: the root cause is not established and nothing prevents the growth; closed as decided not to build (owner item 20 names the files).

## Acceptance

- [x] Whether a janitor detector should report home-folder leftovers is decided (no) on a measured growth of 2 to 3 files a day; NARROWED: root cause not established, nothing prevents the growth.
