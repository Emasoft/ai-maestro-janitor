---
trdd-id: N1CPV1QV
title: Memory agent claim step must be handed the scheduler's absolute state dir instead of resolving it from cwd
column: todo
created: 2026-09-05T18:35:40+0200
updated: 2026-09-05T21:15:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05T21:15

A dead worker left NO code for this card — only `scripts/memory_dispatch_claim.py` was
already committed at its PRE-this-TRDD baseline (parts (a)-(f) were all still to do). This
takeover session implemented ONLY the parts confined to the two in-scope scripts
(`scripts/memory_dispatch_claim.py`, `scripts/detectors/memory-maintenance.py`) plus their
test files — **NOT** the skills/heartbeat-protocol/agent-prompt-template wiring (parts
(a)/(b)/(c)/(f)-skill-grep/(f)-prompt-template), which touch 8 `SKILL.md` files and
`~/.claude/rules/janitor-heartbeat-protocol.md` outside this card's declared file scope
for this takeover and were not attempted.

**Implemented this session:**
- `scripts/detectors/memory-maintenance.py`: the scheduler's dispatch payload now carries
  `"state_dir": str(state.state_dir().resolve())` (part (e), write side).
- `scripts/memory_dispatch_claim.py`:
  - `--state-dir` default changed from `""` to `None` so an explicitly-empty value is
    distinguishable from "not given"; empty value → exit 4, distinct stderr message (part (c)).
  - New exit code 3 ("no memory-maint-* files at all", cwd-resolved only, `--state-dir` not
    given) — distinct from the pre-existing exit 2 "nothing claimable" (part (d)).
  - `claim_one()` gained `expected_state_dir` kwarg + `StateDirMismatch` exception: a
    candidate's payload `state_dir` differing from the resolved invocation directory
    raises (claim refused, record untouched, still pending); a MISSING `state_dir` field
    (older payload) is accepted with one `state.log_line` call, never refused; comparison
    is `Path(...).expanduser().resolve()` on both sides so a symlinked pool directory still
    claims successfully (part (e), all sub-requirements including the symlink + missing-field
    cases).
  - `main()` wires all of the above; existing callers that don't pass `--state-dir` at all
    keep working exactly as before except for the new (d) exit code when the pool is
    genuinely empty.
- New tests in `tests/test_memory_dispatch_claim.py`: `test_rejects_empty_state_dir_argument`,
  `test_refuses_when_state_dir_unresolved_and_no_pool`,
  `test_explicit_state_dir_with_no_pool_keeps_ordinary_exit_2`,
  `test_claim_one_refuses_a_foreign_state_dir`,
  `test_claim_one_accepts_state_dir_through_a_symlink`,
  `test_claim_one_accepts_a_record_with_no_state_dir_field`.

**NOT implemented (left for a follow-up NPT/session):** (a) spawn-prompt carrying the path,
(b) the model-turn composition + abort-if-unresolvable requirement, the 8 `SKILL.md`
`--state-dir` wiring + `: "${STATE_DIR:?…}"` guard, and the two grep-based tests for those
(skill invocation + prompt-template placeholder). These require editing files outside this
takeover's declared scope (`skills/janitor-memory-*/SKILL.md`,
`~/.claude/rules/janitor-heartbeat-protocol.md`) and were explicitly not touched.

**Verification (this session):**
```
uv run pytest tests/test_memory_dispatch_claim.py -q -p no:cacheprovider → 27 passed
uv run pytest tests/test_memory_maintenance.py tests/test_memory_dispatch_claim.py -q -p no:cacheprovider → 76 passed
uv run ruff check scripts/memory_dispatch_claim.py scripts/detectors/memory-maintenance.py \
  tests/test_memory_maintenance.py tests/test_memory_dispatch_claim.py → All checks passed!
uv run mypy scripts/ --ignore-missing-imports → Success: no issues found in 504 source files
uvx --with pyright pyright <same 4 files> → 0 errors, 0 warnings, 0 informations
```
Manual exit-code spot check:
```
uv run python3 scripts/memory_dispatch_claim.py --state-dir ""            → exit 4
uv run python3 scripts/memory_dispatch_claim.py --state-dir /tmp/empty    → exit 2
CLAUDE_PROJECT_DIR=/tmp/empty uv run python3 scripts/memory_dispatch_claim.py → exit 3
```

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
  equivalent) directly in the text the spawning session hands the agent.
  A MODEL TURN in the spawning session composes that path — it reads a
  Bash tool result (e.g. `$CLAUDE_PROJECT_DIR/.janitor/state` when
  `$CLAUDE_PROJECT_DIR` is set, else
  `$(git -C "$PWD" rev-parse --show-toplevel)/.janitor/state`) and types
  it into the agent prompt; there is no harness guarantee that turn reads
  the RIGHT project's result — do not rely on unverified assumptions
  about the spawning session's cwd: whether an ai-maestro-harness agent's
  Bash cwd equals its registered workdir is unverified
  (`$CLAUDE_PROJECT_DIR` is empty in at least one observed session). If
  that resolution fails (git rev-parse errors and `$CLAUDE_PROJECT_DIR`
  is unset), the spawning session MUST NOT spawn the memory agent — it
  reports one line instead and aborts the spawn. A correctly-typed path
  still leaves the cross-project harness case open (the model turn
  composes project A's path while the fire came from project B); item
  (e) below is the backstop that makes such a wrong composition harmless
  instead of silently reporting an empty pool.
- (c) All 8 `janitor-memory-*` SKILL.md files run the claim step with
  `--state-dir "$STATE_DIR"`, where `$STATE_DIR` is the path from (b),
  never resolved from the agent's own cwd. Each SKILL.md's command block
  fails loudly, before invoking the claim step, when `$STATE_DIR` is
  unset or empty: `: "${STATE_DIR:?janitor: STATE_DIR not provided by
  the spawn prompt}"`. `memory_dispatch_claim.py` itself also rejects an
  EMPTY `--state-dir` argument as an error distinct from "absent"
  (`scripts/memory_dispatch_claim.py:200` currently treats `args.state_dir`
  falsy — including `""` — the same as "not given", silently falling back
  to cwd resolution; that must become an explicit failure, not a silent
  fallback).
- (d) `memory_dispatch_claim.py` gets a DISTINCT exit code (not 0 or 2 —
  read `main()` for the codes already in use before picking one) for "no
  pool at all" — zero `memory-maint-*` files, pending OR claimed, in the
  resolved directory — but ONLY when `--state-dir` was NOT given (i.e. cwd
  resolution was used). The 8 skills treat that code as "report to the
  human, do not retry" rather than as an ordinary failure. A genuinely
  empty pending set with claimed files present in the directory stays the
  existing cheap-abstain exit 2.
- (e) Defense in depth for the case (b) cannot rule out: `_write_pending`
  (`scripts/detectors/memory-maintenance.py:256`) records the absolute
  `state_dir` it wrote into inside the dispatch payload;
  `memory_dispatch_claim.py` compares the payload's `state_dir` with the
  directory it was actually invoked on and REFUSES the claim (a distinct
  message, non-zero exit; the record is left untouched, still pending)
  when they differ. This closes V1 with no new stdout line and no
  pointer file, because the check travels INSIDE THE RECORD ITSELF — a
  spawning-session model turn that composes the wrong project's path
  writes an agent that looks in the wrong directory, but the claim
  attempt is caught and refused rather than silently reporting an empty
  pool. **Comparison is NORMALISED, never raw strings**: both sides
  resolve `Path(x).expanduser().resolve()` before comparing — the
  scheduler at write time (`memory-maintenance.py:256`) and the claim
  script at claim time (`memory_dispatch_claim.py:200`) — because
  `git rev-parse --show-toplevel` yields the physical path while a
  model-composed `--state-dir` may carry a trailing slash, `~`, a
  relative form, or `/tmp` vs `/private/tmp` on macOS; raw string
  equality would refuse EVERY claim and grow the pile one record per
  fire. The acceptance test for (e) includes a symlinked pool directory
  that still claims successfully. A record written by an OLDER cached
  plugin version with no `state_dir` field at all (live for up to the
  30-min TTL plus the keep-20 prune horizon after an update) is ACCEPTED
  with one log line, never refused — absence of the field is not
  evidence of a wrong directory, only of a version gap. This guard is
  DISTINCT from (d): (d)'s new exit code fires on "no pool at all" (zero
  `memory-maint-*` files anywhere) — a mistyped path; (e)'s refusal fires
  when a real pool exists but for the wrong project — a correctly-typed
  path to the wrong root. Each keeps its own exit code; neither
  subsumes the other.
- (f) Tests: one asserting every `janitor-memory-*` SKILL.md passes
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
- [x] `memory_dispatch_claim.py` exits with a distinct new code (not 0 or
      2) and a clear stderr message when no `--state-dir` is given and the
      resolved directory holds no `memory-maint-*` files at all (verified
      by a new test in `tests/test_memory_dispatch_claim.py`, e.g.
      `test_refuses_when_state_dir_unresolved_and_no_pool`).
- [x] `memory_dispatch_claim.py` rejects an EMPTY `--state-dir` argument
      with a distinct error message (never silently falls back to cwd
      resolution), verified by a new test, e.g.
      `test_rejects_empty_state_dir_argument`.
- [ ] Each `janitor-memory-*` SKILL.md's command block aborts before
      invoking the claim step when `$STATE_DIR` is unset or empty,
      verified by a test that sources the skill's command block with
      `STATE_DIR` unset and asserts non-zero exit (e.g.
      `tests/test_memory_skill_state_dir_guard.py`). (NOT done this
      session — requires editing 8 `SKILL.md` files outside this
      takeover's declared scope; see STATE block.)
- [x] `memory_dispatch_claim.py` refuses a claim (distinct message,
      non-zero exit, record left untouched/still pending) when a
      dispatch record's payload `state_dir` differs from the directory
      the claim step was actually invoked on, verified by a new test
      that writes a record with a foreign `state_dir` into a tmp pool
      and asserts the claim is refused and the file is still pending.
- [x] The comparison normalises both sides via
      `Path(x).expanduser().resolve()` before comparing, verified by a
      test that invokes the claim step through a SYMLINKED pool
      directory and asserts the claim still succeeds.
- [x] A record with no `state_dir` field at all (older-version payload)
      is accepted with one log line, never refused, verified by a test.
- [ ] `uv run pytest` full suite still green. (NOT run this session per
      orchestrator instruction; see the sibling card's STATE block for the
      flaky, unrelated `test_dispatch_defang.py` finding.)
