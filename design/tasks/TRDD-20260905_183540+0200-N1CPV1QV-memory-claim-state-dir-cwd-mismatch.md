---
trdd-id: N1CPV1QV
title: Memory agent claim step must be handed the scheduler's absolute state dir instead of resolving it from cwd
column: todo
created: 2026-09-05T18:35:40+0200
updated: 2026-09-05T18:35:40+0200
current-owner: main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
parent-trdd: LDSCQ0NU
npt: []
eht: []
external-refs: [github:Emasoft/ai-maestro-janitor#300]
---

# Memory agent claim step must be handed the scheduler's absolute state dir instead of resolving it from cwd

## Symptom

Every `janitor-memory-*` SKILL.md runs the claim step with no `--state-dir`
override, e.g.:

```
uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" --chore split
```

(`skills/janitor-memory-split/SKILL.md:73` and the equivalent line in the
other 7 memory skills.) `memory_dispatch_claim.py:191` accepts `--state-dir`
but falls back at line 200 to `state.state_dir()`, which
`scripts/lib/state.py:117-136` resolves from `$CLAUDE_PROJECT_DIR`, else
`git rev-parse --show-toplevel` from the process's own cwd, else cwd. An
agent spawned by the heartbeat protocol runs with a cwd that is NOT
guaranteed to be the project root (the heartbeat protocol itself documents
"a spawned agent's cwd is not the project root"). Such an agent resolves a
DIFFERENT `.janitor/state` directory than the scheduler that wrote the
pending record, finds an empty pool there, and reports "nothing claimable"
even while the scheduler's real pool holds unclaimed work.

Measured on this host 2026-09-05: `.janitor/state` held 14 unclaimed
`memory-maint-pending-<id>.json` records (6 of them `split`, 10-46h old)
alongside 20 claimed records — i.e. the pool was NOT empty, contradicting
the "empty claim pool" premise TRDD-LDSCQ0NU's fix addressed. A state-dir
mismatch on the agent side is the surviving, unverified hypothesis for why
those 14 records went unclaimed.

## Fix requirement

- (a) `scripts/detectors/memory-maintenance.py` prints, immediately after
  the bare `[janitor-memory-*]` marker, a PAYLOAD line
  `state-dir=<absolute state_dir>` — payload lines are surfaced, never
  executed, per `~/.claude/rules/janitor-heartbeat-protocol.md`.
- (b) `~/.claude/rules/janitor-heartbeat-protocol.md`'s memory row and the
  `janitor-memory-subconscious-agent` spawn prompt pass that path through
  to the spawned agent.
- (c) All 8 `janitor-memory-*` SKILL.md files run the claim step with
  `--state-dir "<that path>"` instead of relying on cwd resolution.
- (d) `memory_dispatch_claim.py` REFUSES (non-zero exit, one clear
  stderr line) when `--state-dir` is absent AND the resolved fallback
  directory holds no pool at all — instead of silently reporting "nothing
  claimable" indistinguishable from a genuinely empty pool.
- (e) Tests: one per (a) — marker emission includes `state-dir=`; one per
  (c) — grep over all 8 skill files for `--state-dir`; one per (d) —
  `memory_dispatch_claim.py` invoked with no `--state-dir` and an
  unresolvable/no-pool fallback dir exits non-zero with the refusal
  message.

Note: the TRDD-LDSCQ0NU write-time/relay-time claim-pool gates stay — they
correctly cover the peer-claimed-first race. This TRDD covers a distinct
failure: the claiming agent looking in the wrong directory entirely.

## Acceptance criteria

- [ ] `memory-maintenance.py` marker emission is followed by a
      `state-dir=<absolute path>` payload line (verified by a new test in
      `tests/test_memory_maintenance.py`).
- [ ] All 8 `janitor-memory-*` SKILL.md files invoke
      `memory_dispatch_claim.py` with an explicit `--state-dir` argument
      (verified by `grep -L -- '--state-dir' skills/janitor-memory-*/SKILL.md`
      returning nothing, wired into a test).
- [ ] `memory_dispatch_claim.py` exits non-zero with a distinct refusal
      message when no `--state-dir` is given and the resolved directory has
      no pool at all (verified by a new test in
      `tests/test_memory_dispatch_claim.py`, e.g.
      `test_refuses_when_state_dir_unresolved_and_no_pool`).
