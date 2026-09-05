---
trdd-id: N1CPV1QV
title: Memory agent claim step must be handed the scheduler's absolute state dir instead of resolving it from cwd
column: todo
created: 2026-09-05T18:35:40+0200
updated: 2026-09-05T18:42:00+0200
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

Confirmed by a second, independent measurement: unclaimed `split` records
aged 34h and 46h exist right now, and a record only ever moves
pending→claimed (never the reverse), so both were already in the pool
23.5h ago at issue #300's second fire (2026-09-04 ~19:04, issue opened
~17:10). The pool was NOT empty at that fire either.

## Fix requirement

- (a) **No new stdout line.** A `state-dir=<path>` payload line after the
  marker was considered and rejected: the heartbeat output contract
  (`~/.claude/rules/janitor-heartbeat-protocol.md`, owner directive
  2026-08-12) says never print a path the human did not ask for, and
  `scripts/dispatch.py::_quiet_filter` may divert non-token prose to the
  findings ledger instead of surfacing it — untested, so a payload line
  is not a reliable delivery path anyway.
- (b) Instead, the path travels INSIDE THE AGENT PROMPT, not on stdout:
  `~/.claude/rules/janitor-heartbeat-protocol.md`'s memory row and the
  `janitor-memory-subconscious-agent` spawn instructions pass
  `<project-root>/.janitor/state` (or the resolved USER/LOCAL scope
  equivalent) directly in the text the spawning session hands the agent —
  the spawning session already knows its own project root, so no new
  channel is needed.
- (c) All 8 `janitor-memory-*` SKILL.md files run the claim step with
  `--state-dir "$STATE_DIR"`, where `$STATE_DIR` is the path from (b),
  never resolved from the agent's own cwd.
- (d) `memory_dispatch_claim.py` gets a DISTINCT exit code (not 0 or 2 —
  read `main()` for the codes already in use before picking one) for "no
  pool at all" — zero `memory-maint-*` files, pending OR claimed, in the
  resolved directory — but ONLY when `--state-dir` was NOT given (i.e. cwd
  resolution was used). The 8 skills treat that code as "report to the
  human, do not retry" rather than as an ordinary failure. A genuinely
  empty pending set with claimed files present in the directory stays the
  existing cheap-abstain exit 2.
- (e) Tests: one asserting every `janitor-memory-*` SKILL.md passes
  `--state-dir` to the claim step (grep-based, over `skills/`); one for
  the new exit code (`memory_dispatch_claim.py` invoked with no
  `--state-dir` against a directory with zero `memory-maint-*` files of
  either kind); one asserting the agent-prompt template (wherever
  `janitor-memory-subconscious-agent`'s spawn text is built) contains the
  state-dir placeholder.

Note: the TRDD-LDSCQ0NU write-time/relay-time claim-pool gates stay — they
correctly cover the peer-claimed-first race. This TRDD covers a distinct
failure: the claiming agent looking in the wrong directory entirely.

## Rejected alternatives

- **stdout payload line** (`state-dir=<path>` after the marker) — violates
  the heartbeat "no unsolicited paths" contract and risks silent diversion
  by `_quiet_filter`; see (a) above.
- **A machine-wide pointer file in the plugin DATA dir** naming "the
  current project's state dir" — rejected because it lets an agent spawned
  for project A claim project B's dispatch, which
  `[[janitor-per-project-channeling]]` forbids as cross-project leakage.

## Acceptance criteria

- [ ] The `janitor-memory-subconscious-agent` spawn prompt (and the
      heartbeat protocol row that documents it) carries the absolute
      `.janitor/state` path for the target scope, verified by a new test.
- [ ] All 8 `janitor-memory-*` SKILL.md files invoke
      `memory_dispatch_claim.py` with an explicit `--state-dir` argument
      sourced from that prompt (verified by
      `grep -L -- '--state-dir' skills/janitor-memory-*/SKILL.md`
      returning nothing, wired into a test).
- [ ] `memory_dispatch_claim.py` exits with a distinct new code (not 0 or
      2) and a clear stderr message when no `--state-dir` is given and the
      resolved directory holds no `memory-maint-*` files at all (verified
      by a new test in `tests/test_memory_dispatch_claim.py`, e.g.
      `test_refuses_when_state_dir_unresolved_and_no_pool`).
- [ ] `uv run pytest` full suite still green.
