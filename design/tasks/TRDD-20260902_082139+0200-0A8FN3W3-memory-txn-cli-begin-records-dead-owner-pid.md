---
trdd-id: 0A8FN3W3
title: memory_txn CLI begin records its own dead pid as owner so any concurrent resume reaps a live staging txn
column: testing
created: 2026-09-02T08:21:39+0200
updated: 2026-09-02T08:40:27+0200
current-owner: janitor-memory-subconscious-agent
task-type: bugfix
min-approval-requirement: user
scope: project
labels: [memory-txn, janitor-machinery, concurrency, data-loss-adjacent]
severity: high
---

# memory_txn CLI `begin` records its own dead pid as owner, so any concurrent `resume` reaps a live staging txn

## Symptom (measured 2026-09-02, PROJECT scope of this repo)

A `[janitor-memory-split]` pass began a transaction through the CLI contract
(`memory_txn_cli.py begin` → agent edits staging → `commit` in a later turn). While it was still
editing, a second, independently dispatched split pass on the same scope started up and — as every
editorial pass does by contract — ran `memory_txn_cli.py resume` first. The first pass's journal
and its four staged sub-pages vanished. At commit time it saw only
`error: no transaction b03d42e2… under …/.claude/project/memory`, and had to rebuild everything.

No corpus content was lost (commit is fail-closed and the reaped txn had applied nothing), but the
whole staged editorial pass was destroyed silently. Two overlapping passes on one scope are normal
(the USER scope is dispatched against by every project's heartbeat), so this recurs.

## Root cause

`MemoryTxn.begin()` records `owner_pid=os.getpid()` (`scripts/lib/memory_txn.py:307`). Under the
CLI contract that pid is the `begin` subprocess itself, which exits the moment it prints
`txn_id=`. Every CLI-begun transaction therefore carries a dead `owner_pid` from birth.

`resume_pending` (line 706) then treats it as an orphan of a stopped pass and reclaims it on
sight, bypassing the 6 h `stale_seconds` window:

```python
owner_dead = txn.owner_pid > 0 and not _pid_is_alive(txn.owner_pid)
if is_stale or owner_dead:
    ...  # rmtree's the staging dir + journal
```

The issue #158 fix that introduced `owner_dead` is correct for the in-process API (`begin` and
`commit` in one long-lived process) and regresses the cross-process CLI contract. The comment at
lines 709-716 already describes the overlap and guards it with the scope lock — but the lock only
protects an in-flight `_apply`, not a staging-phase txn whose "owner" is by construction gone.
The line 703-705 contract ("`owner_pid == 0` … keep the staleness-only behavior … never a new
reclaim path") is the escape hatch the CLI should be using.

## Proposed fix

In `memory_txn_cli.py cmd_begin` (or a `begin(..., owner_pid=...)` parameter), record an owner
that is actually alive for the life of the edit: the PARENT process (`os.getppid()` — the agent's
shell) is unreliable across tool calls, so the safe choice is **`owner_pid=0`** for CLI-begun
transactions, falling back to the staleness-only reclaim exactly as the line 703-705 contract
specifies. The in-process API keeps `os.getpid()`.

Add a regression test: `begin` via the CLI in a subprocess, then `resume_pending` from the test
process → the journal MUST survive (it is fresh and owner-unknown); only after `stale_seconds`
may it be reclaimed.

## Acceptance

- [x] CLI `begin` writes `owner_pid: 0` (or an owner provably alive across turns) — `MemoryTxn.begin`
      gained `owner_pid: int | None = None`; `cmd_begin` passes `owner_pid=0` (2026-09-02).
- [x] Test: CLI-begun fresh txn survives a concurrent `resume_pending`.
- [x] Test: in-process `begin` from a process that then dies is still reclaimed on sight (#158 preserved).
- [x] `uv run pytest tests/ -k memory_txn` green; `ruff` + `mypy` clean — 66 passed, ruff clean,
      mypy clean on 497 files, verified first-hand by janitor-main-session 2026-09-02 08:46.

## Evidence

`reports/janitor-memory-subconscious-agent/20260902_081649+0200-split-project-janitor-compaction-floor-gate.md`
(gitignored, local) — the pass that hit it, with the settling commands.

## Approval log

- 2026-09-02T08:40:27+0200 — APPROVED by USER ("0A8FN3W3: yes"). Promoted `proposal` → `dev`
  (moved to `design/tasks/`); implemented by a lean-worker under janitor-main-session rather than
  routed through `ticket_cli.py`, because the USER's reply is the approval and the fix is one
  keyword plus three tests. Lands in the next patch publish.
