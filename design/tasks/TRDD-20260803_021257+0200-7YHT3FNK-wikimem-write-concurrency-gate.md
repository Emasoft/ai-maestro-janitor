---
trdd-id: 7YHT3FNK
title: Every wikimem edit path gains locks plus compare-and-swap staleness refusal
column: dev
created: 2026-08-03T02:12:57+0200
updated: 2026-08-03T02:12:57+0200
current-owner: janitor-session
task-type: feature
severity: high
scope: project
release-via: publish
npt: []
eht: []
implementation-commits: []
---

# Wikimem write-concurrency gate (USER directive 2026-08-03)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-03

**In dev — P1 LANDED (ea05bc5), P3 LANDED (70fd8a1: realpath lock parity pinned by a
symlink test; bridge append under the scope lock with OUTCOME_LOCK_HELD; CLAUDE.md
writers AUDITED already-compliant — flock at claudemd_slim.py:118 + stat-CAS +
narrative invariant, no redundant machinery added), P2 in flight (background worker:
the `memgrep edit` replace primitive), P4 after P2 (docs mandate — must document the
shipped `edit` surface, so it waits for P2).
P1 verified first-hand: 279 crate tests, clippy, both benches "no change", LIVE
Python↔Rust lock-file parity probe (same scope root → same memory-maint-<sha16>.lock
from both languages), live CAS refusal with the canonical message + byte-identical
page, correct-hash acceptance.** USER directive (2026-08-03, verbatim intent): corruption
risk is high with many agents editing the same LOCAL/PROJECT/USER wikimem files (and, in
future, symlinked published-globally pages) because there is no central lock system.
Every edit tool must integrate a transaction discipline: atomic changes, locks, write
queues, deterministic changes, diff/line-by-line replace-X-with-Y that applies ONLY when
the original text still matches — otherwise refuse with the canonical message:
**"The content of the wikimem file changed since your command was enqueued. Please
reread the file first."**

## Verified current state (2026-08-03, first-hand)

| Writer | Atomic | Lock | Staleness CAS |
|---|---|---|---|
| Python txn core (`memory_txn.py`, chore agents via `memory_txn_cli`) | ✓ journaled | ✓ per-scope flock (`global_state_dir()/memory-maint-<sha16(scope_root)>.lock`) | ✓ begin-hash → commit stale-snapshot guard (`MemoryTxnConflict`) |
| memgrep write verbs (`add-atom`, `add-lesson`, `new-page`, `migrate`, index writers) | ✓ `atomic_write_page` tmp+rename | ✗ NONE | ✗ NONE — read→modify→write, lost-update window between two concurrent verbs |
| `repomap_generate.py` (CLAUDE.md splice) | ✓ | ✗ | partial (`splice_with_verify` re-read+signature) |
| `claudemd_slim.py` (CLAUDE.md index splice) | ✓ | ✗ | partial |
| `memory_bridge.ensure_bridge_line` (MEMORY.md) | ? | ✗ | ✗ |
| Any agent editing a memory page via raw shell/heredoc | ✗ | ✗ | ✗ (the harness Edit tool has old-string+mtime guards; shell does not) |

## Design (decided; the phases below implement it)

1. **ONE lock protocol, two languages.** memgrep (Rust) reimplements the Python lock
   byte-identically: `flock(EX)` on `global_state_dir()/memory-maint-<sha16>.lock`
   where sha16 = first 16 hex of sha256 over the scope-root path string. Scope-root
   derivation in Rust: the nearest ancestor directory literally named `memory` that
   contains the target page (realpath-resolved) — which is exactly the three canonical
   scope roots (and keeps `wikimem/` subpages on their scope's lock). Realpath on BOTH
   sides so a symlinked page (the future published-globally mechanism, TRDD-AZ6QRK0D)
   maps to its canonical scope's lock, never a second lock. Python's `_scope_lock_path`
   gains the same realpath normalization.
2. **The write QUEUE = the kernel's flock wait.** memgrep write verbs acquire the lock
   BLOCKING with a bounded timeout (default 10s, `MEMGREP_LOCK_TIMEOUT_S` override):
   concurrent writers serialize deterministically instead of failing. Timeout → the
   canonical refusal (a held-forever lock must surface, not hang an agent). The Python
   txn core keeps its skip-if-held semantics (its callers are schedulers that re-fire).
3. **CAS everywhere.** Every memgrep write verb gains `--base-sha256 <hex>` (optional):
   when supplied and the live page's sha256 differs at lock-acquisition time, refuse
   with the canonical message, exit non-zero, mutate nothing. The verb's own
   read→modify→write then happens entirely UNDER the lock, so verbs without the flag
   are lost-update-safe too (their read is fresh by construction).
4. **The replace primitive** — `memgrep edit --page P` reading an old/new block pair
   (`--old-stdin`+`--new-file`, or two files): applies ONLY when the old text matches
   the live page exactly and uniquely (0 matches → the canonical message; >1 → an
   ambiguity refusal naming the count). Under the lock, atomic write, reindex. This is
   the sanctioned scriptable path for every agent edit that isn't a write-verb shape —
   raw shell edits of memory pages become a documented violation.
5. **CLAUDE.md/MEMORY.md writers** get a per-file flock (same formula, keyed on the
   file's realpath) + base-hash re-verify immediately before `os.replace`.
6. **Docs**: wikimem-model + the write/update/repair skills + the subconscious agent
   mandate the gated primitives and document the refusal → re-read → retry protocol.

## Phases (≤5 files each; tests in the same phase; commit per phase)

- **P1 (Rust, memgrep):** lock module (scope-root derivation, blocking flock+timeout) +
  wire into ALL write verbs + `--base-sha256` CAS + canonical message. Unit tests incl.
  a two-process contention test.
- **P2 (Rust, memgrep):** the `edit` replace-primitive verb + tests (match/0-match/
  multi-match/changed-since-enqueued).
- **P3 (Python):** realpath in `_scope_lock_path` (+ its tests), `ensure_bridge_line`
  atomic+CAS, `repomap_generate`/`claudemd_slim` file-flock + pre-replace re-verify.
- **P4 (docs/skills):** the mandate + protocol everywhere agents are told how to edit
  memory; lint/audit note for raw-edit violations.

## Verification

- Two concurrent `add-atom` on the same page: both land, neither lost (serialized).
- `--base-sha256` mismatch and `edit` with changed old-text: refuse with EXACTLY the
  canonical message, page byte-identical after.
- A symlinked page path takes the same lock as its realpath (probe via lock filename).
- Existing suites: memgrep crate tests, wikimem bench (accuracy unchanged), Python
  txn/bridge/repomap suites.

## Notes and lessons learned
