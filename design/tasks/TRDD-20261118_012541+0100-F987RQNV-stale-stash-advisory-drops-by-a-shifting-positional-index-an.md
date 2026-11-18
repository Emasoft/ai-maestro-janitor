---
trdd-id: F987RQNV
title: stale-stash advisory drops by a shifting positional index and its dedupe key includes that index
column: todo
status: tasked
created: 2026-11-18T01:25:41+0100
updated: 2026-11-18T01:27:08+0100
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
approval-datetime: 2026-11-18T01:25:41+0100
---

# stale-stash advisory drops by a shifting positional index and its dedupe key includes that index

Source: GitHub issue #367 (https://github.com/Emasoft/ai-maestro-janitor/issues/367), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue: the stale-stash advisory names a stash by its position, which moves. A stash created 2026-05-07 was reported as stash@{44} on 2026-11-15 and stash@{48} on 2026-11-16 after newer stashes were pushed, and the advisory tells the reader to pop or drop it by that position, so following it after a push drops the wrong stash. The issue author saw the advisory text in a session reply, not in a janitor log.

## Suspected cause

By the issue: the suggested pop and drop commands are built from ref (the positional stash index at emit time); the docstring says the dedupe key survives reordering, but the key is a crc32 of the positional ref plus the timestamp, so one stash got two keys in the same weekly bucket and every push re-emits every older stash. Expected by the issue: key on the creation timestamp alone or on the stash commit hash; name the stash by commit hash in the suggested commands, or tell the reader to re-check git stash list before dropping.

## Files named by the issue

scripts/detectors/stale-stash.py (docstring lines 13-16, key at line 133, suggestion lines 135-139); per-project state/stale-stash-seen.txt.

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:41+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
