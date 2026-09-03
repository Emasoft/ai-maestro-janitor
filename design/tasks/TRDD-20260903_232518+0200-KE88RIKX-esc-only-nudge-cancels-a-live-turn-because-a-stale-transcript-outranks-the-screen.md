---
trdd-id: KE88RIKX
title: the ESC-only nudge cancels a live turn because a stale transcript outranks the screen
column: testing
created: 2026-09-03T23:25:18+0200
updated: 2026-09-03T23:25:18+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
severity: high
relevant-rules: []
npt: []
eht: []
parent-trdd: N954KWUC
min-approval-requirement: none
implementation-commits: []
external-refs: []
---

# the ESC-only nudge cancels a live turn because a stale transcript outranks the screen

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03

**Fix landed in the tree, tests green, NOT yet published.** One condition changed in
`pane_policy._at_working`, four tests added in `tests/test_pane_policy.py`.

**NEXT ACTION:** none until the release. After publishing, confirm from
`<plugin-data>/global-state/daemon.log` that no further `FIRED esc_nudge` line names a pane
that was working — the refusal logs `REFUSED by the pane policy` instead.

**Do NOT "restore" the old carve-out.** It reads as a deliberate exception ("an ESC-only nudge
is authorized by a 15-minute-stale transcript the SCREEN cannot see") and it was wrong for the
reason recorded below. The mutation probe in `## Proof` is how to re-confirm that in seconds.

## Symptom (owner report, 2026-09-03)

> "be sure to fix the improper use of esc that caused the blocking of the agents activities,
> interrupting the continuity. you must use scripts more conscious of what is on the terminal
> screen of claude code."

Measured in `<plugin-data>/global-state/daemon.log` the same evening:

```
[2026-09-03T22:44:27+0200] session-liveness: FIRED esc_nudge → iterm for CLAUDE-PLUGIN-VALIDATION [frozen] attempt=0
[2026-09-03T23:06:43+0200] session-liveness: FIRED esc_nudge → iterm for CLAUDE-PLUGIN-VALIDATION [frozen] attempt=0
```

Twice, 22 minutes apart, into one project, both at `attempt=0`.

## Root cause — two independent layers, and only the second is a code defect

**Layer 1 (already fixed, unpublished).** The daemon that fired those two ESCs is the INSTALLED
3.4.13, and `grep -c pane_actuate <cache>/3.4.13/scripts/daemon.py` returns **0** — that version
has no `pane_actuate.py` at all. It types on a DIAGNOSIS and never looks at the screen. The
screen-reading actuator is TRDD-N954KWUC Phase 3, complete in the tree and in no tag.

**Layer 2 (this card).** Publishing alone would NOT have fixed it, because the new policy table
also admitted the ESC. `pane_policy._at_working` read:

```python
if event in _CALLER_DRIVEN and not (esc_first and command):
```

`esc_nudge` reaches `plan()` as `Event.RECOVERY_RUNG` with **`command=None`** — one Event covers
the whole ladder (`rearm`, `reload`, `esc_nudge`), and `action_to_command("esc_nudge")` is None
by design (`fleet_inject._ESC_ONLY_ACTIONS`). So `esc_first and command` was falsy and the rung
was ADMITTED. The discriminator treated "ESC with no command" as the safe case when it is the
most destructive of the three at a live turn: ESC alone cancels the turn and leaves nothing
behind that says why the work stopped.

The module's own docstring granted this deliberately — *"an ESC-only `esc_nudge` is authorized
by a 15-minute-stale transcript the SCREEN cannot see"* — two sentences before condemning the
identical reasoning for hard-plus-command as *"a stale proxy overriding a screen that says work
is happening"*.

**Why the proxy is wrong here specifically:** a session inside ONE long tool call — a 13-minute
test suite, a build, a slow API poll — writes nothing to its transcript for the whole call. The
transcript goes stale precisely when the screen is most certainly right.

**Why refusing costs the `frozen` recovery nothing:** the panes that recovery exists for do not
present as `WORKING`. `RETRY_WEDGE`, `SESSION_LIMIT` and `API_ERROR` are separate `StatusKind`s;
`_at_wedge` owns the first and the others type nothing by design. The only pane this carve-out
could ever reach was one visibly doing work.

## Fix

`scripts/lib/pane_policy.py::_at_working` — admit a caller-driven rung only when it TYPES a
command and does NOT begin with ESC:

```python
if event in _CALLER_DRIVEN and command and not esc_first:
```

Differs from the old condition in exactly the two `command is None` rows, i.e. only the ESC-only
rungs. Soft enqueue still lands (the cron re-arm and the machine-wide stop keep working over a
live turn); hard-plus-command stays refused.

A refusal returns NOOP, which `daemon._decline`s **without spending a recovery attempt**, so the
rung retries on the next beat instead of marching the ladder toward its killing rungs.

## Proof

- `tests/test_pane_policy.py::test_working_refuses_an_esc_only_rung_because_esc_cancels_the_live_turn`
- `::test_working_still_accepts_a_soft_enqueue_that_types_a_command` — the half that must survive
- `::test_working_refuses_hard_plus_command_unchanged`
- `::test_a_rate_limited_pane_is_never_classified_working_so_the_fix_strands_nothing` — reads the
  real captured frames, so a parser change that broke the premise fails here
- **Mutation probe:** restoring the old condition makes the first test fail with
  `Left contains one more item: Step(keys='ESC', label='recovery_rung ESC')` — the bare ESC
  itself. Re-run it before ever relaxing this law.

**The 116 policy-adjacent tests passed BEFORE the fix as well** — no test had ever asserted that
an ESC-only rung lands at a working pane. The behaviour was undefended, which is how a carve-out
this consequential survived a Phase-3 migration whose whole purpose was to stop screen-blind
keystrokes.

## Acceptance

- [x] `_at_working` refuses every sequence that begins with ESC
- [x] the soft enqueue at a working pane still lands (no regression to the stop / re-arm path)
- [x] a refusal does not spend a recovery attempt
- [x] mutation probe demonstrates the new test fails against the old condition
- [x] ruff + mypy clean on the changed files; 128 policy-adjacent tests pass
- [ ] LIVE: after the release, no `FIRED esc_nudge` line in `daemon.log` names a working pane
      (blocked on publishing — the daemon runs the installed plugin)

## Notes

Parent is TRDD-N954KWUC: this is the law that migration should have tightened and did not. It is
filed separately rather than reopened on N954KWUC because that card is terminal-adjacent at
`testing` and this is a distinct defect with its own proof.
