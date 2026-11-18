---
trdd-id: LJSST2WL
title: secrets-shield-scan Rust accelerator behind a flag with on and off parity
column: todo
status: tasked
created: 2026-11-18T09:55:36+0100
updated: 2026-11-18T18:12:29+0100
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

# secrets-shield-scan Rust accelerator behind a flag with on and off parity

Increment 2 of TRDD-BAQB9SYO, split out on 2026-11-18. A Rust accelerator only for what the measurements show hot, behind an explicit flag, with the on/off parity test (identical findings on the fixture corpus and on a sample of at most 4 GB). Measured so far (TRDD-BAQB9SYO STATE): the JSONL planner is CPU-bound at about 350 ns of CPU per byte, 94% of it inside redactJsonLine; a plain scan ran at about 34 MB/s on one small sample. Fresh-machine build path as in the Design of TRDD-BAQB9SYO (reuse the memgrep build path); a missing build stops only a run that asks for the accelerator.

## Approval log

- 2026-11-18T09:55:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Owner orders

2026-11-18 (verbatim): "you forgot that i told you that the secrets-shield must not only scan and redact the context and the jsonl transcripts in realtime, preventing agents to ever read or send via api a secret (like the installed mod partially does, but it is incomplete) but also to prevent committing secrets with executing the secrets-scanner on the committed files at each commit? before that git cliff will create the changelog (otherwise there is the risk of publishing secrets in the very release logs of github, or metadata of npm, bun or pypi packages!)? What are you doing now? implement those immediately. secrets-shield must be blazing fast (with its performance critical core routines optimized in rust) and always on when the janitor is armed!"
