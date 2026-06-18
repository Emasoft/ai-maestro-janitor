---
trdd-id: 9e4851fc-cb3b-4435-8022-d05e6dbb5d1a
title: Wikimem editor — commit-discipline rule + model commit/trdd provenance fields
column: complete
created: 2026-06-18T19:35:24+0200
updated: 2026-06-18T20:42:00+0200
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

- **Current state:** BUILT + TESTED (4 tests green, ruff clean). `rules/commit-discipline.md`
  ships (auto-installed user-scope by rules_installer) with all four obligations; the
  wikimem model gained the `commits:`/`trdd:` provenance fields + the WHY-resolution-chain
  section. `tests/test_commit_discipline.py` pins the load-bearing content. TRDD-G
  consumes the chain.
- **NEXT ACTION:** none for TRDD-C — ship via publish.py. (TRDD-G implements the chain
  in the conflict pass: memory.commits → memory.trdd → TRDD.implementation-commits →
  git show.)
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
