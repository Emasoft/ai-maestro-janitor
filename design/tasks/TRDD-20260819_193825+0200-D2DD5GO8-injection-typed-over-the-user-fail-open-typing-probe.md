---
trdd-id: D2DD5GO8
title: Terminal injection typed over the USER mid-sentence — the typing probe fails OPEN exactly when osascript is blind
column: testing
created: 2026-08-19T19:38:25+0200
updated: 2026-08-21T07:58:01+0200
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

- [ ] both gates' fail-directions audited and named in the detector docstring
- [ ] sustained-unknown ⇒ defer (with backoff + log), single-unknown ⇒ proceed; both pinned by tests
- [ ] `uv run pytest -q`, ruff, mypy clean
- [ ] USER-visible behavior: injection never lands while keys are being pressed, even at loadavg 200

## Approval log
