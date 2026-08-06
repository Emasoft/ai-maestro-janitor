---
trdd-id: 5C42VCUX
title: Idle session never auto handoff-and-clears — the cron beats a huge context for hours and only ever RECOMMENDS /clear to the user
column: testing
created: 2026-08-06T13:23:24+0200
updated: 2026-08-06T17:55:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: [71e65e91]
---

# Idle session never auto handoff-and-clears (owner failure report 2026-08-06, item 2)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**`testing` since 2026-08-06.** Root cause found, proven and FIXED (`71e65e91`); guards added.
The one open box is an OBSERVATION that cannot be manufactured (below).

### ROOT CAUSE — found, and it is not any of the four the body guessed

Not the knob, not the gates, not cooldown, not version skew. **`clear_enabled()` already defaults
to `True`** — the knob was never the blocker.

`dispatch._phase_idle_clear_nudge` fired the clear with
`terminal_trigger.send_self_command(respect_user_presence=True)` — the exact API
`terminal_trigger.send_verified`'s own docstring says to **never** use. On iTerm that returns the
`USE_ITERM_PATH` **sentinel** meaning *"caller, run your own osascript"*. All five sibling trigger
scripts (`compact_trigger`, `clear_trigger`, `reload_trigger`, `resume_trigger`,
`reload_skills_trigger`) have that branch. This caller never did — so
`sent.startswith("FIRED:")` was **False on every fire** and the lever was **structurally dead on
the owner's terminal**, not merely mistuned.

MEASURED 2026-08-06 on this host: `send_self_command(...)` → `'USE_ITERM_PATH'`,
`.startswith('FIRED:')` → `False`.

**Why no evidence existed:** the phase logged `not injected … will retry` and returned cleanly,
forever — and `.janitor/logs/` held **zero** `idle-clear` lines, because it never reached a send
worth logging. The 2026-08-04 change that added the `FIRED:` test cured the FALSE-POSITIVE half
(it used to stamp a 2 h cooldown and claim success while typing nothing) but not the blindness, so
the phase went from lying about success to correctly reporting that it does nothing.

### THE FIX (`71e65e91`)

`send_verified` against the resolved pane — it has no sentinel to forget: it builds steps for
whatever channel it is given, types, RE-READS the pane, then submits. The pane is resolved by
composing two already-tested functions rather than new logic:
`session_liveness.capture_terminal_identity(env)` → the FLEET shape, then
`external_clear.terminal_from_record` → the `terminal_trigger` shape. The bug class is now
**unrepresentable here**: `send_verified` returns a BOOLEAN, so no future added string status can
default to "assume it worked".

### NEXT ACTION (one step, runnable)

Nothing to code. Wait for the observation in the open box below, then close.

### The one open box, and why it cannot be forced

`one observed unattended handoff-and-clear` requires a session idle ≥1 h with the **user absent** —
presence is a hard veto (correctly). It cannot be staged while the owner is at the keyboard, and
faking it would mean disabling the very gate that protects their work. Same class as
TRDD-QE390SJA / TRDD-UA4FAX67's owner-gated observations: the wiring is proven by tests +
falsification instead.

### Verified (do not re-verify)

- Guards **fail on the pre-fix code and pass on the fixed code** — checked by AST-parsing
  `71e65e91^:scripts/dispatch.py`: the pre-fix file has the offending call at line 1677 and both
  guards flag it. A guard that never bites is decoration.
- After the fix, `respect_user_presence=True` survives **only** in comments and in
  `send_verified`'s own warning docstring — no live caller (AST-checked, not grepped).
- iTerm IS drivable by the ratified injector: `channel_is_readable` / `build_type_only_steps` /
  `build_submit_steps` / `read_pane_text` all succeed on this session's pane.

### Artifacts

`tests/test_idle_clear_injection.py` (7 guards) · `scripts/dispatch.py::_phase_idle_clear_nudge` ·
`scripts/lib/terminal_trigger.py::send_verified` · sibling card TRDD-PXP08ZQC (the external,
zero-model-turn path this one is the in-model stopgap for).

## WHY (measured today)

A ~500k-token session sat idle for ~4 hours doing NOTHING but heartbeat fires. At the
`*/15` cadence with >5-min gaps, EVERY fire re-paid a ~400–460k cache-miss WRITE (two
were hook-flagged this session). The auto-clear machinery exists in-tree
(`cold_cache_compact.should_clear_when_long_idle`, `clear_enabled`,
`on-stop-proactive-compact.py` — the TRDD-D3PROACT family) yet it never engaged; the
model spent the whole day RECOMMENDING `/janitor-handoff-and-clear` to the user instead
of the system doing it. The owner's verdict: a whole skill and script wasted.

## The task (one atomic fix: make the idle auto-clear ACTUALLY ENGAGE)

1. Root-cause why `should_clear_when_long_idle` / the D3PROACT Stop-hook path did not
   fire this session: knob default (`clear_enabled()` is gated by its OWN knob — is it
   default-off?), the `user_present`/`active_waiting` gates, cooldown state, or version
   skew (session ran 2.3.0 while the machinery shipped later).
2. Decide + set the default so an idle session past the clear threshold clears ITSELF
   (with the handoff written first — see TRDD-PXP08ZQC for the zero-model-turn writer;
   until that lands, the existing skill flow fired via the ratified
   `run_chained_inject` chain is acceptable).
3. Regression evidence: an idle session with a big context must be observed to
   handoff-and-clear UNATTENDED within one clear-threshold window.

## Acceptance

- [x] root cause named with the exact gate/knob that blocked today's engagement — **not a gate or
      knob at all**: the `USE_ITERM_PATH` sentinel from the retired one-shot injector (see STATE)
- [x] default-on decision recorded — `clear_enabled()` **already defaults to `True`**; the knob was
      never the blocker, so there is no default to change and no owner choice to solicit
- [ ] one observed unattended handoff-and-clear on an idle big-context session — **cannot be
      staged while the owner is present** (presence is a hard veto); see STATE
- [x] the "recommend to the user" path demoted to fallback-only — done 2026-08-04: the phase now
      FIRES and its `print` reports an action taken, not a recommendation

## Pointers

- Failure narrative: this session's transcript 2026-08-06 morning (burn alarm at 3.3x,
  repeated stand-down turns, two ~400k cache-miss hook warnings).
- Machinery: `scripts/lib/cold_cache_compact.py`, `scripts/hooks/on-stop-proactive-compact.py`.
- Sibling: TRDD-PXP08ZQC (cache-expiry-aware EXTERNAL clear, zero model turns).
- Version-skew amplifier: the session ran 2.3.0 all day with 2.4.1 cached-pending-restart.
