---
trdd-id: b92a9dd0-7ba2-434a-9b33-f0735ac69d5f
title: Wikimem editor — memory-edit safety core (txn + lock + verify)
column: complete
created: 2026-06-18T19:35:24+0200
updated: 2026-06-18T20:14:00+0200
current-owner: janitor-session
assignee: janitor-session
priority: 3
task-type: infra
release-via: publish
parent-trdd: TRDD-54b25d7e
relevant-rules: []
test-requirements: [unit]
---

# Wikimem editor — memory-edit safety core (txn + lock + verify)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-18

- **Current state:** BUILT + TESTED (41 tests green, ruff clean). `scripts/lib/memory_txn.py`
  (begin/stage/commit/abort/resume + per-scope commit flock + SHA-256 stale-snapshot
  guard + `editor_enabled` kill gate + `apply_atomic` convenience) and
  `scripts/lib/memory_edit_verify.py` (lesson-preservation strict check, legality
  predicates, ocd/lmd, dangling-link, dedup, split globs-partition/convergence) exist,
  with `tests/test_memory_txn.py` + `tests/test_memory_edit_verify.py`. Every executor
  (E/F/G) mutates pages ONLY through this transaction core, never directly.
- **NEXT ACTION:** ship via `publish.py`; then the executors (E/F) import
  `memory_txn.apply_atomic` + the `memory_edit_verify.*` checks. A thin `memory_txn`
  CLI (begin/commit/resume subcommands) for the agent-driven case lands with TRDD-D/E.
- **Load-bearing facts (CRITICAL corrections from the plan):**
  - A merge/split mutates MANY files (merged/overview page, deleted sources,
    MEMORY.md, **redirected backlinks in OTHER pages**) — a crash / rate-limit /
    compaction mid-pass loses data; verify-after-write CANNOT undo. The txn boundary
    is the whole point.
  - **mtime is NOT the truth** — use a SHA-256 stale-snapshot guard: hash sources at
    read, re-hash before swap, mismatch ⇒ abort+discard (a concurrent
    `janitor-memory-write` mid-pass must not be silently destroyed).
  - The per-scope flock clones `global_state.marketplace_lock` and lives under
    `global_state_dir()`.
  - Settings/USER-root path resolution is a SEPARATE concern (TRDD-B/C); the
    `${CLAUDE_PLUGIN_DATA}` trap is NOT this TRDD's, but the verify lib must mirror
    the librarian's hard-coded janitor plugin-DATA path when it touches the USER scope.
- **SUPERSEDED — do NOT carry forward:** none yet.
- **Durable artifacts to read before acting:** the plan
  `/Users/emanuelesabetta/.claude/plans/glittery-hatching-shell.md` (§"Decisive
  corrections" + the TRDD-A sub-section) and the parent TRDD-54b25d7e.

## Scope

Build the transaction + lock + verify primitives that make every wikimem edit
crash-resumable, lock-serialized, hash-guarded, and content-preserving. No
executor or scheduler is built here — only the safety substrate they all depend on.

## Key mechanisms

- `scripts/lib/memory_txn.py`: `memory/.maint-staging/<txn-id>/` (mutate copies
  there), `journal.json` (txn-id, op, source/target sets, phase), ordered atomic
  swap (write survivors via `state.atomic_write`/`os.replace` first, delete sources
  last), **resume-check** at heartbeat start (roll-forward a half-applied swap /
  discard an unstarted staging dir); completed-txn-id = idempotency key.
- Per-scope `memory-maint.lock` flock (clone `global_state.marketplace_lock`) under
  `global_state_dir()`, held read→stage→verify→swap; **SHA-256 stale-snapshot
  guard** (hash sources at read, re-hash before swap, mismatch → abort+discard).
- `scripts/lib/memory_edit_verify.py`: parser-independent content-union (result ⊇
  union(sources), no exact-dup lines, catch a *silently reworded* fact);
  link-redirect verify (zero refs to retired slugs via `memgrep links --broken`
  over the staged tree; no new orphans/one-sided); ocd/lmd (survivor
  `ocd==min(sources)`, `[^N]` stamps byte-identical, `lmd` advanced); legality
  assertions; split convergence (converged vs gave-up).
- `is_legal_merge(A,B)` / `is_legal_split(P)` predicates (shared by E/F).
- Global enable/kill gate `WIKIMEM_EDITOR_ENABLED` + honor the janitor
  pause/kill-switch.

## Acceptance

- A merge that DROPS or REWORDS a note → FAIL; a clean merge → PASS.
- A simulated crash mid-swap → resume restores consistency.
- Two concurrent writers → one proceeds (flock) and the stale-hash loser aborts.

## Dependencies

None. This is the foundation; TRDD-D depends on the lock, and TRDD-E/F/G run
through this transaction core. See the plan ship order: NPT → A → (B ∥ C) → D →
E → F → G.
