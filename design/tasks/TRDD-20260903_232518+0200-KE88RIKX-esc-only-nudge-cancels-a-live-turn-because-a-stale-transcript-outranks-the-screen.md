---
trdd-id: KE88RIKX
title: the ESC-only nudge cancels a live turn because a stale transcript outranks the screen
column: testing
created: 2026-09-03T23:25:18+0200
updated: 2026-09-03T23:36:12+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
severity: high
relevant-rules: []
npt: []
eht: []
related-trdds: [N954KWUC, L32WC0H7, 8DR0X08A]
min-approval-requirement: none
implementation-commits: [fc76c0ca]
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

## Considered and DECLINED — do not re-litigate without new evidence

**Applying the same `command is None` guard inside `_blind`.** `_blind` serves channels with NO
read-back BY CONSTRUCTION (the ai-maestro CLI, wtype, xdotool — `fleet_inject._readback_identity`
returns None for all three), and `pane_actuate.act` is the only caller allowed to assert
`blind_ok`. There, refusing the ESC-only rung would not trade a bad keystroke for a good one; it
would disable the `frozen` recovery outright on those channels, because no better signal exists
and none can be obtained. The observed defect was on a READABLE iTerm channel, where a correct
signal was available and ignored. Left as is, deliberately.

`_at_idle` and `_at_wedge` were checked and need no change: at an idle pane there is no live turn
for ESC to cancel, and at a wedge the ESC is the entire point.

**Residual risk, accepted — and it escalates rather than going silent.** "Refusing strands
nothing" is too strong as stated. What it strands is nothing we can still CLASSIFY as stuck: a
pane whose retry banner was already erased by an earlier ESC repaints as a spinner row and parses
`WORKING` via `_classify_status`'s `status_row is not None` fallback, so this law now withholds
the ESC that used to (blindly) fire again. That is the intended trade — it is the very loop
TRDD-L32WC0H7 documents — and it is the better failure of the two, because the old behaviour
destroyed real work silently while this one reports itself:

- per beat: `session-liveness: … REFUSED by the pane policy` in `daemon.log`;
- after `_STALL_ESCALATE_S` (`CLAUDE_PLUGIN_OPTION_DAEMON_DECLINE_STALL_ESCALATE`, default
  **3600 s**) of an UNCHANGED decline signature, `daemon._decline` records a HIGH
  `FLEET-DECLINE-STALL` finding carrying the `policy_refused` remedy text ("open the pane and
  look at it") and logs `session-liveness: ESCALATING … a human must clear it`.

So a pane refused with an UNCHANGED decline signature for an hour is REPORTED rather than watched
forever in silence — note "unchanged signature", not "hung pane": a pane alternating between
`policy_refused` and `deferred_presence` (a human intermittently at the keyboard) resets the
clock each time and may never reach the threshold. The steadily-refused case, which is the one
this fix creates, is covered.

**Where the report actually appears — corrected once, and the first answer was wrong.** The
`FLEET-DECLINE-STALL` row is written by the DAEMON process into the findings ledger. It surfaces
to a human in two places, and neither is the per-fire heartbeat stdout:

- **SessionStart**, via `findings_ledger.surface_block(...)` — called from
  `scripts/hooks/on-session-start.py`, the ONLY caller besides the CLI;
- **`/janitor-findings`** on demand (`scripts/findings_cli.py`).

The earlier draft of this section claimed the line was "promoted past quiet mode into the
heartbeat's own stdout" by `dispatch._URGENT_LINE_RE`. That was wrong, and wrong in an
instructive way: the regex is real and does match `HIGH`, but its INPUT is the lines
`dispatch.py` itself produces while running detectors during a fire — it never reads the ledger.
`grep -rn "surface_block\|unread_entries" scripts/` returns `findings_cli.py` and
`on-session-start.py` and nothing in `dispatch.py`. Verifying that a mechanism EXISTS is not
verifying that YOUR data reaches it.

Practical consequence, which is the honest form of the trade: a refused pane is reported to the
next session that starts, not to the session sitting in front of it. On this machine that is a
real delay — the SessionStart block at the top of this very session showed
`…14 older unread — /janitor-findings to browse`.

One honest limit: it fires **exactly once** per unchanged decline signature — `escalated = False
if changed else bool(_st.get("escalated"))`, where `changed` is `last_audit != sig`. So the flag
RESETS when the signature changes, which is the behaviour you want in both directions: a pane
that recovers and later stalls differently escalates again, and a pane stuck in one unchanged
state is reported once rather than every beat (TRDD-FB84YUGT).

`sig_since` resets the same way and for the same reason (`sig_since = now if changed else …` —
its comment names the trap: re-stamping it on an UNCHANGED decline would leave a permanent stall
permanently one beat old, defeating the escalation entirely).

Setting the knob to `0` does NOT disable the escalation — the natural assumption, and wrong here.
`coerce_int` returns a non-negative int and the guard is `now - sig_since >= _STALL_ESCALATE_S`,
so `0` makes it fire on the FIRST refused beat. (Contrast `rate_limit_flag_is_stale`, where
`max_age_s <= 0` genuinely disables the sweep — the two knobs read the same and behave
oppositely.)

All of the above VERIFIED by reading the code — `daemon.py::_decline` (the escalation block, the
`escalated` and `sig_since` assignments, the `_write_recovery_state` call), the constant at
`daemon.py:131-133` via `_env_interval` → `state.coerce_int(plugin_option(var), default)`, and
`dispatch.py`'s `_URGENT_LINE_RE` — not inferred from any docstring.

**`_decline` does not spend a recovery attempt — VERIFIED, not assumed.** Its
`_write_recovery_state` payload is `{**_st, "last_ts", "identity", "last_audit", "sig_since",
"escalated"}`: it stamps the cooldown and carries the prior state forward, and `attempts` is
never among the keys. This is the load-bearing safety property of the whole fix — had it
incremented, the change would have converted "ESC the pane" into "march to
`relaunch`/`force_restart`", which is strictly worse than the defect it repairs.

## Notes

Related to TRDD-N954KWUC: this is the law that migration should have tightened and did not. It is
filed separately rather than reopened on N954KWUC because that card is terminal-adjacent at
`testing` and this is a distinct defect with its own proof. It is `related-trdds:`, NOT
`parent-trdd:` — a defect in code another card shipped is neither that card's prerequisite (NPT)
nor its effect-handler (EHT), which is all `parent-trdd:` encodes.
