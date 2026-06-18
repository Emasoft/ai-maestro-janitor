---
trdd-id: 9e4851fc-cb3b-4435-8022-d05e6dbb5d1a
title: Wikimem editor — commit-discipline rule + model commit/trdd provenance fields
column: todo
created: 2026-06-18T19:35:24+0200
updated: 2026-06-18T19:35:24+0200
current-owner: janitor-session
assignee: janitor-session
priority: 3
task-type: infra
release-via: publish
parent-trdd: TRDD-54b25d7e
relevant-rules: []
test-requirements: [unit]
---

# Wikimem editor — commit-discipline rule + model commit/trdd provenance fields

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-18

- **Current state:** authored, not started. This is TRDD-C (P1), parallelizable
  with TRDD-B. TRDD-G depends on it (the WHY-resolution chain).
- **NEXT ACTION:** author `rules/commit-discipline.md` (auto-installed user-scope):
  commit often, after each memory write, WHY in BOTH the commit message AND code
  comments, `TRDD-<8hex>` in the subject.
- **Load-bearing facts (CRITICAL corrections from the plan):**
  - Fact-verify repo resolution MUST come from **provenance, not a guess** — a USER
    memory references code in *some* repo; scanning every repo mis-attributes (same
    filename in two repos → wrong delete). The repo is resolved from the memory's
    `commit:`/`trdd:` provenance; **no provenance ⇒ ineligible for deletion** (TRDD-G
    demotes/skips only).
  - **WHY is sourced, never inferred** — resolution chain is
    `memory.commit → memory.trdd → TRDD.implementation-commits → git show`.
  - The commit-discipline rule is about PROJECT-CODE discipline; LOCAL/USER memory
    STORES persist via atomic-write, NEVER git.
- **SUPERSEDED — do NOT carry forward:** none yet.
- **Durable artifacts to read before acting:** the plan
  `glittery-hatching-shell.md` (TRDD-C
  sub-section + the provenance-resolution correction) and TRDD-54b25d7e.

## Scope

The provenance substrate that lets TRDD-G resolve a memory's repo (and its WHY)
from sourced commit/TRDD links instead of a filename guess, plus the
commit-discipline rule that makes those links reliably present.

## Key mechanisms

- `rules/commit-discipline.md` (auto-installed user-scope): commit often, after each
  memory write, WHY in BOTH the commit message AND code comments, `TRDD-<8hex>` in
  the subject. Explicit: this is PROJECT-CODE discipline; LOCAL/USER memory stores
  persist via atomic-write, never git.
- `wikimem-model.md` + memory-write skill: optional `commit:`/`commits:` + `trdd:`
  frontmatter; bidirectional memory↔TRDD link (TRDD STATE/body points back at the
  memory slug). WHY-resolution chain documented (consumed by TRDD-G), never inferred.

## Acceptance

- The rule installs (auto-installed user-scope).
- A memory with `commit:`/`trdd:` round-trips.
- The WHY-resolution chain is documented (for TRDD-G to consume).

## Dependencies

None of its own. TRDD-G depends on it (provenance resolution + WHY chain). See the
plan ship order: NPT → A → (B ∥ C) → D → E → F → G.
