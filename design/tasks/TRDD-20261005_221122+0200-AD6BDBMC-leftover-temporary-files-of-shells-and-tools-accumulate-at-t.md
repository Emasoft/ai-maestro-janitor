---
trdd-id: AD6BDBMC
title: Leftover temporary files of shells and tools accumulate at the top of a home folder and nothing notices
column: todo
status: tasked
created: 2026-10-05T22:11:22+0200
updated: 2026-10-05T22:13:35+0200
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

## Corrections

2026-10-05 (review): a shell that died between write and rename is one mechanism; two shells racing on the dump would leave the same file. Why the dump is rewritten so often was not measured.
