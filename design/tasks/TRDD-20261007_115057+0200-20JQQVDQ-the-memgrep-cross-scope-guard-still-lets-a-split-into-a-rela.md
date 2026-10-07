---
trdd-id: 20JQQVDQ
title: The memgrep cross-scope guard still lets a split into a relative not-yet-existing page through
column: todo
status: tasked
created: 2026-10-07T11:50:57+0200
updated: 2026-10-07T11:50:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T11:50:57+0200
---

# The memgrep cross-scope guard still lets a split into a relative not-yet-existing page through

## Symptom (VERIFIED by reading commit 2a600afb, scripts/memgrep/src/memory.rs guard_downward_cross_scope)

The guard classifies each path as p.canonicalize().unwrap_or_else(|_| p.to_path_buf()) and then scope_layer. A page that does not exist yet cannot be canonicalized, so its RAW spelling is classified; scope_layer's hardcoded-root tests need a leading slash, so a relative spelling such as .claude/project/memory/new.md classifies as None and the guard fails open. That is exactly split-mem-topic's --into (it must not exist yet) given as a relative path: a cross-scope split lands a downward link. Existing relative pages are fixed by 2a600afb.

## Task

Absolutize before the fallback: canonicalize the PARENT and join the file name, or std::path::absolute, then scope_layer. Failing test first: split-mem-topic with a relative --into under a LOCAL root and --page under a USER root (scope overrides pointed at scratch) is refused and writes nothing.

## Context

Public issue 330 and commits 31c2e3b0, b5e8ae5c, 2a600afb. Found by a read-only review on 2026-10-07 (reports/board/batches/20261007_113607+0200-b5e8ae5c-review.md, gitignored). Also from that review, smaller: the code comments cite a card id that exists only on one host (cite issue 330 instead); nobody checked whether the merge/split skill or help text still advertises cross-scope merges, which these verbs now refuse in both directions.

## Note

These commits were made in this checkout by a writer the main session could not identify. Do not start this card while that writer is still editing scripts/memgrep; coordinate through the owner.

## Approval log

- 2026-10-07T11:50:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
