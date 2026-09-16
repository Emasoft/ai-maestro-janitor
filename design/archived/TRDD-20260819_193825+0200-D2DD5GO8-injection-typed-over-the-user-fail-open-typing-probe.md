---
trdd-id: D2DD5GO8
title: Terminal injection typed over the USER mid-sentence — the typing probe fails OPEN exactly when osascript is blind
column: complete
created: 2026-08-19T19:38:25+0200
updated: 2026-08-22T10:43:50+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [janitor#92, janitor#257]
npt: []
eht: []
implementation-commits: [5515108a]
---

# Injection typed over the user — fail-open typing probe under a blinded osascript

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-20 00:17

**SHIPPED (`todo → testing`).** The audit sharpened the diagnosis beyond the card's sketch:
the failure was never surfaced as "unknown" — under load `ioreg` times out, `hid_idle_seconds`
returns None, and `user_presence` fell through to the SUBMIT-stamped breadcrumb (stale by
construction while a user is mid-sentence), laundering blindness into a confident "not
typing". The design direction below is SUPERSEDED in one respect: **"single unknown ⇒
proceed" is wrong** — the dangerous moment is the FIRST blind read meeting an empty field,
so a tolerate-one-blip rule re-opens the incident hole. Shipped semantics:

- `user_intent.typing_now()` (new): hid readable ⇒ answers BOTH ways alone; hid blinded ON
  darwin ⇒ None (unless a fresh breadcrumb proves True); off darwin ⇒ collapses to bool
  (the 22-min Linux-CI hang class stays fixed — no headless box can block).
- Both `terminal_trigger` default probes: **None ALWAYS defers** (bounded by giveup_s + the
  iteration cap, exiting through the loud give-up, never a silent cancel); the
  `_BLIND_PROBE_STREAK=3` threshold gates only the one diagnostic log line, which is itself
  exception-guarded (a diagnostic must never break the gate).
- `JANITOR_HID_IDLE_OVERRIDE_S` (new env seam): subprocess tests can pin rung 0; the real
  probe reads the HOST keyboard, which made every real-subprocess test hostage to live human
  presence (measured: hid=0.6 s mid-suite ⇒ truthful deferral ⇒ 30 s timeout flake in
  test_clear_trigger).

Tests: `tests/test_blind_probe_streak.py` (10 — typing_now semantics both platforms,
sustained-blind never types + loud give-up, blip-then-recovered proceeds, streak log once,
pane-free hold/free); legacy default-probe + clear-trigger tests made hermetic. Full suite
15605 passed; ruff + mypy + pyright clean.

**NEXT ACTION (the gate to `complete`):** observe one real loaded-host episode (loadavg
spikes recur on this box) with the SHIPPED plugin: the terminal_trigger log shows the
"typing probe blinded Nx" line and no injection lands while keys are pressed. Ships with
the next publish; the running cache still has the old semantics until then.

> **⚠ THE GATE ABOVE IS CURRENTLY UNREACHABLE — checked 2026-08-21, do not sit waiting on it.**
> The shipped code is installed (3.3.26, well past the version this was written against) and
> the host HAS produced the required load episodes — full-suite runs at loadavg 80+, measured
> this session while diagnosing TRDD-7NSRD8OV. Yet `grep -r blinded .janitor/logs/` returns
> NOTHING, and the newest `terminal_trigger.log` entry is still 2026-08-20T08:21:30.
>
> The reason is structural, not a bug: **the typing probe only runs when an INJECTION IS
> ATTEMPTED.** None is attempted in this session — the USER's standing NO-INJECTIONS directive
> bars every `reload_trigger` / `resume_trigger` / `compact_trigger` path — so the probe never
> executes and cannot log "blinded". Load alone is not sufficient. The gate needs load AND an
> injection attempt AND a human at the keyboard, and the session that reliably produces the
> first is forbidden the second.
>
> Two honest ways forward, both needing the USER: (1) re-scope the gate to what a fixture can
> prove — drive the probe with a blinded (`None`) presence reading under a simulated
> sustained-unknown and assert the DEFER path, which is what acceptance box 2 already asks for;
> or (2) a deliberate, USER-authorised injection under load into a pane they are typing in.
> **Option 1 is the recommendation** — option 2 re-runs the exact incident that opened this
> card against a live human, in order to observe something a fixture can show.

## What happened (USER report, 2026-08-19 ~19:30, this host)

`reload_trigger.py --shrink never` (fired at the USER's request to type `/reload-plugins
--force` for them) injected INTO the pane WHILE the USER was typing, interleaving with their
keystrokes. The USER's own words: "what the hell happened to the detector of keystrokes? why
you injected while i was typing?"

## Mechanism (read from 3.3.16 source, not guessed)

- `reload_trigger.py:229` — NO presence cancel by design (owner directive 2026-08-02,
  janitor#257): presence DEFERS inside `terminal_trigger.inject_until_sent` (empty-field wait,
  stop on keypress, +8s per keystroke), and `send_self_command(..., respect_user_presence=False)`
  is intentional. The deferral machinery is the only guard.
- `terminal_trigger.py:574-580` — the typing probe is TRI-STATE and **"unknown → NOT typing"**
  ("this probe only defers/loops — the empty-field ..."). The probes are osascript/HID queries.
- Context that turns this into a live failure: osascript was TRANSIENTLY HANGING all day on this
  loaded host (three `[janitor]` zero-iTerm-sessions advisories, janitor#92 thread; loadavg
  peaked >200). A blinded probe returns unknown; unknown counts as not-typing; the injector
  typed over the human. The empty-field check must also have been blinded or raced — audit it
  the same way (what does a timed-out field read return, and which way does it fail?).

## Why the fail-open direction is wrong here

"Unknown → not typing" is the right bias when probes fail RARELY and independently. It is the
wrong bias when the probe's failure is SYSTEMATIC (host load blinds every osascript query in
the same window): the guard then disappears exactly when it is most needed, and the cost is
typing over the human — the single most trust-destroying action this plugin can take. Compare
UWBXNJ76's positive-control lesson: a guard disarmed by the event it guards.

## What (design direction, verify against the code before implementing)

1. Audit BOTH gates in `inject_until_sent` (empty-field read + typing probe) for their
   fail-direction on probe error/timeout. Name each probe's failure modes from the code.
2. Change the bias for CONSECUTIVE unknowns: one unknown may pass (transient), N consecutive
   unknowns (probe systematically blind) ⇒ DEFER with long backoff + one log line naming the
   blind probe — never inject on a sustained-unknown streak. Keep the owner's no-cancel model:
   defer, never refuse.
3. Consider a cheap non-osascript corroborator for "user typing" (HID idle via IOKit already
   exists — `user_intent.hid_idle_seconds`; check ITS failure mode under load too).
4. Tests: probe-returns-unknown streak ⇒ no injection (pinned); single unknown ⇒ injection
   proceeds (the owner's relieve-the-human property preserved); real fault injection, no
   mocking of the code under test.
5. Post-fix: measure on this host under load (the reproducing condition exists routinely).

## Acceptance

- [x] both gates' fail-directions audited and named in the detector docstring —
      `terminal_trigger.py:696-707` audits BOTH by name (the `typing_now` probe and rule 1's
      pane reader) and states each one's direction.
- [x] **AMENDED, and the amendment is the finding.** As written this box asked for
      *"sustained-unknown ⇒ defer, **single-unknown ⇒ proceed**"* — design direction §2, tolerate
      one blip. Implementation REJECTED that half deliberately, and the docstring says why:
      *"the dangerous moment is the FIRST iteration meeting an empty-looking field, so a
      tolerate-one-blip rule would re-open the exact incident hole."* The shipped rule is
      STRICTER than the card asked for — EVERY unknown defers, and the streak counter gates only
      the diagnostic line. Recorded rather than silently ticked, because a design direction
      overruled during implementation is a decision, not a detail. Both halves now pinned:
      `test_a_BLINDED_typing_probe_DEFERS_and_never_licenses_injection` (None defers) and
      `test_a_probe_that_confirms_NOT_typing_proceeds` (False proceeds — the contrast without
      which the first test would also pass against an injector that never injects).
- [x] `uv run pytest -q`, ruff, mypy clean.
- [x] USER-visible behavior: injection never lands while keys are being pressed — **proven by a
      staged drill, not by waiting.** Report:
      `reports/d2dd5go8-injection-drill/20260822_104228+0200-part-b-drill.md`.

## ⏵ STATE — 2026-08-22: closed on staged evidence, plus one defect the drill found

**The card's own title is now false and that is the good outcome.** "The typing probe fails OPEN
exactly when osascript is blind" describes the pre-fix code. `terminal_trigger.py:696-707` cites
this TRDD by name and does the opposite. The gate looked unreachable because the FIX WORKS and no
injection was pending — not because anything was broken.

**Part A — regression tests.** Three, in `test_terminal_trigger_readback.py`. Mutation-verified
independently of the worker that wrote them: reintroducing the `None → False` reading turns the
blinded test red with **17 keystrokes typed over the user**, and the file restores clean.

**Part B — the drill.** `inject_until_sent` runs its real loop and its real default probe; only
the ioreg READING is faulted, through the operator seam, exactly as host load faulted it on
2026-08-19. That seam previously accepted only floats, so the ONE state that caused the harm —
*the probe exists and cannot be read* — was the one state no drill could stage; a number is
always a confident answer. `JANITOR_HID_IDLE_OVERRIDE_S=blind` now expresses it.

| case | probe | typed | result |
|---|---|---|---|
| provably idle **MAY** type | `9999` | yes | PASS — the positive control |
| **blinded** must not type | `blind` | no | PASS |
| user typing must not type | `1` | no | PASS |

The positive control is load-bearing: without a case that DOES type, the two "did not type" rows
would look identical if the injector were simply broken.

**THE DRILL FOUND A REAL DEFECT, which is the argument for drills over waiting.** My first run
used `quiet_s=0.1` for speed and its *typing* case INJECTED. That was my harness, not the
product — but only because production passes 8.0. `typing_now(idle_s=...)` takes whole seconds,
so a bare `int(quiet_s)` sends **0** for any sub-second window, and "typed within 0 s" is
unsatisfiable: the gate answers "not typing" for a user who is actively typing. A safety gate
that disarms on a plausible argument, in the dangerous direction. Fixed to `max(1, int(quiet_s))`
at both call sites, pinned by
`test_a_subsecond_quiet_window_does_not_disarm_the_typing_gate`, and confirmed by re-running the
drill at the disarming value: now all three PASS.

**Passive observability (the standing gap this closes).** The probe used to be consulted only
when an injection was pending, so on a quiet host "is the probe healthy here?" had no answer and
this card's acceptance was unfalsifiable — a gate that works and a gate that never runs look
identical. `daemon._record_hid_probe_verdict` records the verdict on the daemon beat, which
ALREADY calls `hid_idle_seconds()` for the typing gate, so it costs one integer and no new
probe. Logged on a streak (and on recovery), never per beat: a 60 s loop writing a line a minute
is a log nobody reads. The two alternatives were rejected as unsound rather than as expensive —
lowering the streak threshold manufactures a firing instead of observing one, and waiting longer
is the unfalsifiable hold TRDD-UQW5IOAE already spent weeks inside.

## Approval log
