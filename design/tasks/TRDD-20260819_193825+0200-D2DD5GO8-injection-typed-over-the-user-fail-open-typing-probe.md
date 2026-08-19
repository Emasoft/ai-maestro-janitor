---
trdd-id: D2DD5GO8
title: Terminal injection typed over the USER mid-sentence — the typing probe fails OPEN exactly when osascript is blind
column: todo
created: 2026-08-19T19:38:25+0200
updated: 2026-08-19T19:38:25+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
external-refs: [janitor#92, janitor#257]
npt: []
eht: []
---

# Injection typed over the user — fail-open typing probe under a blinded osascript

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
