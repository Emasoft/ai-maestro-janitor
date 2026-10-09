---
trdd-id: 7YEVICVU
title: Janitor scripts may depend on BSD or GNU forms of date and stat that differ between hosts
column: complete
status: archived
created: 2026-10-05T22:08:51+0200
updated: 2026-10-09T23:14:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:51+0200
implementation-commits: [e15775d4]
---

# Janitor scripts may depend on BSD or GNU forms of date and stat that differ between hosts

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed in ad hoc shell checks on one host: 'date -r <epoch>' and 'stat -f <format>' failed because GNU coreutils come first on the PATH there, and 'stat -f' printed file-system information instead of failing loudly. To do: search the shipped shell snippets, skills and scripts for date and stat calls that assume one flavour, and replace them with a portable form or with Python.

## Approval log

- 2026-10-05T22:08:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:32+0200 — column → testing by main-agent@ai-maestro-janitor. batch B1-B3 merged on main, gated
2026-10-07: shipped in v3.8.4; release observation starts.
2026-10-09 CLOSED by the main session (board drain, wave 3) on three checks it ran itself: fix commits are ancestors of the v3.8.11 tag; the card's tests pass on a re-run today; field condition: the portable forms shipped in v3.8.11; a grep of skills, commands, scripts and hooks for stat -f or date -r finds 0 hits; tests/test_shipped_markdown_portable_shell.py passes. Assessment: reports/board/20261009_231333+0200-wave3-batchB.md.
- 2026-10-09T23:14:18+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11, tests re-run, field condition met.

## STATE

2026-10-07 merged on main (e15775d4): the snippet uses python3 one-liners for the newest .md mtime and the ISO date; the BSD stat format flag is BSD-only and on GNU coreutils it prints file-system info instead of failing, so the old fallback never ran. New test tests/test_shipped_markdown_portable_shell.py blocks the pattern. Not in a release yet.

## Acceptance

- [x] the portable forms shipped in v3.8.11; a grep of skills, commands, scripts and hooks for stat -f or date -r finds 0 hits; tests/test_shipped_markdown_portable_shell.py passes.
