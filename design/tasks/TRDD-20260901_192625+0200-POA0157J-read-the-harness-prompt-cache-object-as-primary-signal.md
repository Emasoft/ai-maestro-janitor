---
trdd-id: POA0157J
title: Read the harness's own prompt_cache status object as the primary cache-state signal
column: todo
created: 2026-09-01T19:26:25+0200
updated: 2026-09-01T19:26:25+0200
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-2F3I2P18, TRDD-1QJIZFFW]
---

# The harness now publishes warm/cold directly — prefer it over inference

## Why

Claude Code 2.1.251 added a per-session prompt-cache line to `/cost` and a matching
**`prompt_cache` object for status line scripts**: hit ratio, misses, tokens re-cached,
**warm/cold**. Everything `cache_certainly_expired` currently derives — via an agentlensPro
subprocess, TTL floors, and transcript-mtime arithmetic — the harness now states first-hand,
per session, on every status-line refresh. Also relevant: 2.1.243 added `promptCacheTtl` /
`subagentPromptCacheTtl` settings (API-key/cloud-provider users), and 2.1.248 fixed the
once-an-hour cache miss from tool re-render after OAuth refresh plus the ScheduleWakeup
definition flip on overage — two burn sources our heuristics may still be compensating for.

## The design

1. The janitor's status-line script (or a tiny dedicated one, if the user runs their own)
   persists the latest `prompt_cache` object + timestamp to
   `.janitor/state/prompt-cache-status.json` on each refresh — zero model cost.
2. `external_clear.cache_certainly_expired` prefers that file when FRESH (age under one
   status refresh interval + slack): `cold` ⇒ True, `warm` ⇒ False, stale/absent ⇒ fall
   through to the existing agentlens probe + age arithmetic unchanged. Same tri-state
   contract: an unreadable file is no signal, never `False`.
3. `/janitor-token-report` gains the real hit ratio / tokens-re-cached figures.

## Acceptance

- [ ] `prompt_cache` persisted from the status line on this machine (verify the field names
      against the live object, not the changelog prose)
- [ ] `cache_certainly_expired` prefers the fresh first-party signal; falls back cleanly
- [ ] tri-state preserved (unreadable ⇒ None) with tests
- [ ] pytest + ruff + mypy green

## Notes and lessons learned

*(none yet)*
