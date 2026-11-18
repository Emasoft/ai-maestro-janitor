---
trdd-id: LJSST2WL
title: secrets-shield-scan Rust accelerator behind a flag with on and off parity
column: todo
status: tasked
created: 2026-11-18T09:55:36+0100
updated: 2026-11-18T19:05:24+0100
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

## Progress 2026-11-18

2026-11-18 profile of the TypeScript scanner (private report reports_dev/sonnet-worker/20261118_185301+0100-scan-profile.md; machine under load average 6 to 94, so every time below is an upper bound): the secrets pass is at least 94% of wall time; reading, decoding, JSON.parse and the cards pass together are under 10%. The CPU profile puts 84% in native regex, but per-rule scans explain only about 15% of the loop, so most of the cost is unattributed (call volume: 2.1 million calls of 4 rules in 30 MiB of transcripts).
A literal prefilter on 4 rules (jwt, jwtWide, google refresh token, private key), measured on the in-process transcript match loop only (30 MiB sample): median 12.94 s against 19.46 s, about 1.5x. The baseline median over the fastest and slowest prefilter run gives 1.26x to 1.80x; the raw spread across runs is 1.06x to 1.97x. Hit counts were equal (21 = 21) on that one sample, but value equivalence and the case sensitivity of the 4 rules were not tested, so the prefilter needs a parity test before it ships. Lower bound: only String.prototype.replace was patched.
Rust portability, compile test only: of the 96 regexes used by the 52 source rule entries (a few of them scan infrastructure), the regex crate compiles 77 as written and fancy-regex 91; JSON_ESCAPED needs a hand-written scanner. Compiling is not match parity, and no Rust speed was measured.
2 TB estimate: a scan-rate extrapolation of about 1.8 days (repo-text rate) to 4.5 days (transcript rate), from loaded-machine samples, with the content mix of the 2 TB unknown. It excludes git object history and the time to write redacted files.
Next measurement: a Rust prototype with 5 to 10 representative rules plus one combined literal prefilter, over the same 50 MiB sample, on a quiet machine, with a match-parity test against the TypeScript core.
