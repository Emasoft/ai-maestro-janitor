---
trdd-id: TL6NL7MK
title: The janitor has no SessionEnd teardown hook — nothing runs when a session terminates
column: todo
created: 2026-08-02T07:50:55+0200
updated: 2026-08-02T07:50:55+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
severity: MEDIUM
scope: project
release-via: publish
parent-trdd: null
relevant-rules: []
implementation-commits: []
---

# `SessionEnd` teardown — the janitor registers no hook at session termination

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** NPT #1 of TRDD-9K0O5YBQ's Claude-Code compatibility audit, extracted 2026-08-02
so it is visible on the board (rule 9 — a derived task written as a bullet inside an audit is a
task nobody can see).

## The gap

The janitor registers 10 of Claude Code's 31 hook events, and `SessionEnd` — *"when a session
terminates"* — is not one of them. **There is no teardown path at all.** Everything the janitor
does at the end of a session is done by a `Stop` hook (per-TURN, not per-session) or not at all.

## Candidates for it — decide, do not assume

The audit named the USER-memory mirror sync and state cleanup. Both need checking against what
already exists before anything is written, because the janitor's habit is to already have the
thing:

- **USER-memory mirror sync** — today `memory_scopes.sync_user_memory_mirror()` runs at
  **SessionStart**. Moving or duplicating it to SessionEnd is only worth it if a session's own
  writes are currently mirrored a whole session late. Verify that before proposing it; the
  SessionStart placement may be deliberate (it also RESTORES from the mirror after a data-dir
  loss, which must happen at start).
- **State cleanup** — name the concrete files. `.janitor/state/` already has purge detectors
  (`reports-purge` line-caps the seen-files) and the daemon has `trashcan-purge`. A SessionEnd
  sweep that duplicates a detector is worse than none.

## The hard constraint

**Do NOT emit `additionalContext` from it.** TRDD-K1RJUYGK's injection-budget discipline applies
to any new hook: a strippable block is re-billed regardless of its content, and `hook: Stop` was
measured as the #2 cache-break offender on this machine. A teardown hook should work by SIDE
EFFECT only — the shape `on-stop-failure.py` already uses (flag + timestamp writes, stderr
diagnostics only).

Check the spec for whether `SessionEnd` output is even read before designing around it; if it is
ignored (as `StopFailure`'s is), that settles the question and the finding belongs in
`CLAUDE.md`'s compatibility section.

## Verification

- The hook fires on a real session termination (not just a unit test) and leaves the intended
  side effect on disk.
- Zero `additionalContext`; a cache-break report from a session that ended cleanly shows no new
  `hook: SessionEnd` offender.
- Fail-open: a raising teardown must never delay or break session exit.

## Notes and lessons learned
