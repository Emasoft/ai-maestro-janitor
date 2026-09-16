---
trdd-id: KE88RIKX
title: the ESC-only nudge cancels a live turn because a stale transcript outranks the screen
column: testing
created: 2026-09-03T23:25:18+0200
updated: 2026-09-16T12:44:46+0200
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
review-after: 2026-09-23
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
- [ ] LIVE: after the release, `daemon.log` shows **BOTH** (a) ≥1 refusal at a working pane —
      the law observably firing on the situation it exists for — **and** (b) zero ESC-only
      rungs landing at one. Both halves, or the box does not pass. Run BOTH commands; do not
      retype the prose (the separator is an em-dash and the elisions are not literal):

      ```bash
      L=~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log
      grep -cE 'REFUSED by the pane policy .* would esc_nudge.*\(pane=working\)' "$L"  # (a) must be >=1
      grep -cE 'FIRED esc_nudge .*pane=working' "$L"                                   # (b) must be 0
      ```

      **If (a) returns 0 the box is NOT YET CHECKABLE — neither pass nor fail.** Re-run after
      **7 days** of post-release log; if it is still 0 then, record that on this card and
      reassess whether the state is reachable at all, rather than leaving the box open
      indefinitely. Without that expiry this box inherits the first version's defect in mirror
      form: never resolving instead of always passing. **7 days is a CHOSEN review interval,
      not derived from anything** — any value in the days range serves; what matters is that
      "not yet checkable" expires rather than persisting unexamined. Said plainly because this
      card's sibling atom needed three rewrites after two invented derivations were published
      for a number that never had one.
      (blocked on publishing — the daemon runs the installed plugin)

**Box 6 was UNMEASURABLE as originally written and was rewritten 2026-09-04, not measured.**
It said "no `FIRED esc_nudge` line names a working pane". The event class does occur — 5
`FIRED esc_nudge` lines in the live log — so it was not vacuous for lack of events. It was
unreadable for lack of a FIELD: the emitter logged
`FIRED {action} → {channel} for {LABEL} [{diagnosis}]`, and `[frozen]` is the SESSION
diagnosis, a different axis from the pane class the policy table actually branches on. No
`FIRED` line has ever named a pane class, so the criterion could be neither passed nor failed
from its own named evidence source — it would have read as "pass" forever.

`pane.status.kind` was in scope at the emit site and simply not logged, so the fix is a field,
not a rewrite of the test: `daemon.py` now appends `pane=<kind>` to both the FIRED/FIRE-FAILED
line and the `REFUSED by the pane policy` line (`unread` when the pane could not be read — a
distinct value, so an unreadable pane can never be mistaken for a working one). The box above
now names a string the log will actually contain.

**Half (a)'s MECHANISM is observed; its OCCURRENCE is what the box measures — do not conflate
them.** The mutation probe against the pre-fix `daemon.py` printed the real line for the
WORKING fixture:

```text
session-liveness: proj-a [frozen] attempt=0 REFUSED by the pane policy — would esc_nudge;
the screen does not allow it right now
```

That is half (a) minus the field the same commit added, so the emit path is real. **But that
line came from a test that CONSTRUCTS the precondition by fiat** — a synthetic
`working-spinner` frame, a synthetic `Instance`, `gather_fleet` patched. It establishes *if a
working pane reaches the rung, the field-bearing REFUSED line is emitted*. It does NOT
establish that a working pane reaches that rung in production, **which is exactly what half (a)
measures.**

The `AgentlensPro` refusals do not close that gap either: they came from the INSTALLED build,
which emits no `pane=` at all, and — this card's own finding — the line does not say which
guard refused. So whether that pane classified `working` is unknown.

**On day 7, therefore, a zero result is more likely an unmet precondition than a broken
field.** Check the field first with a grep for `pane=` on ANY line before concluding anything
about the law.

**Which test pins WHAT — they are different claims, and conflating them lets a refactor drop
the law with the new test still green:**

- **the LAW** (an ESC-only rung must not land at a working pane) is pinned in
  `test_pane_policy.py::test_working_refuses_an_esc_only_rung_because_esc_cancels_the_live_turn`,
  at the layer the law lives in.
- **its LOG OBSERVABILITY** (that the refusal is greppable as `pane=working`) is pinned by
  `test_daemon_session_liveness.py::test_a_working_pane_refuses_esc_nudge_and_the_refusal_names_pane_working`.
  That is what box 6 half (a) actually needs.

**Both were mutation-probed, at their own layers, and the second probe was run because
reasoning said it was unnecessary:** reverting `daemon.py` proved only FIELD sensitivity (the
token did not exist, so any assertion naming it fails). So `_at_working`'s ESC carve-out was
separately restored while keeping the field — and the daemon-layer test failed on
`an ESC-only rung must never reach a working pane`, with the injected
`['RUN','tmux','send-keys','-t','%5','Escape']` in the diff. It guards the law too, which the
field probe alone could not have shown. **Residual, stated rather than glossed:** it catches
THIS regression (the carve-out returning); a future `_at_working` that refuses for some
different reason would keep it green while the ESC law was gone. The policy-layer test is what
covers that.

**The box has TWO halves for a reason — a purely absence-shaped criterion cannot fail.** The
first rewrite said only "no `FIRED … pane=working` line appears", which passes vacuously if
`esc_nudge` never fires at all post-release, for reasons having nothing to do with this fix.
Adding the required-presence half (a) means the box asserts the law was EXERCISED, not merely
that a bad outcome was absent. Fixing the missing FIELD did not fix the missing FALSIFIER;
those are two defects and the first rewrite only addressed one.

**Do not tick this from the current log.** Every `FIRED esc_nudge` line in it predates the
field, and the 10 `REFUSED by the pane policy` lines that follow them were emitted by the
INSTALLED plugin — they do not establish that this card's `_at_working` law is what refused,
because the installed build predates it and the line does not say which guard fired. That
ambiguity is the same missing-field defect, one layer down.

**Verified before shipping the field, so nobody re-derives it:**

- **One parser DOES read a `FIRED` line, and the suffix is invariant to it.** An earlier
  version of this block claimed "nothing parses either changed line" — that was a
  literal-string grep presented as exhaustive, and it was wrong.
  `session_liveness.latest_iterm_rearm_epoch` is a real parser: it matches
  `"FIRED rearm → iterm"` as a **substring** and dates the line from its LEADING timestamp, so
  a field appended at the END changes neither test. Its own docstring warns that a wording
  change here would silently return None forever — which is exactly why this needed reading
  rather than a grep for `$`. (The `FIRE-FAILED` mentions in `fleet_inject.py` /
  `test_fleet_inject.py` really are only docstring prose.)
- **The `FLEET-DECLINE-STALL` escalation is NOT coupled to the log text.** `_decline` builds
  its signature as `f"{outcome}:{rung or '-'}"` from its own arguments (`daemon.py:1666`) — the
  log line is a separate `state.log_line` call. So changing the line reset no stall clock and
  broke no escalation. This mattered enough to check rather than infer: AgentlensPro has been
  steadily refused since 01:10, and a silently-restarted clock would have withheld exactly the
  escalation that surfaces it to a human.
- **No other card's criteria are invalidated.** Roughly ten cards cite `FIRED rearm → iterm`
  and similar lines, all narratively; the new field is a SUFFIX, so every substring grep still
  matches. A grep anchored to end-of-line would have broken — there is none anywhere in
  `design/`, `scripts/` or `tests/`.

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

## Approval log

- 2026-09-16T13:05:00+0200 — stays in testing: the last box is a 7-day daemon.log observation under 3.5.5 (REFUSED-by-pane-policy lines present, zero FIRED esc_nudge pane=working lines); review-after 2026-09-23 parks it from drift until then.
