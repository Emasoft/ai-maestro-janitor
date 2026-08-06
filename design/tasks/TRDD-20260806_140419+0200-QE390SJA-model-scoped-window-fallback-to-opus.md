---
trdd-id: QE390SJA
title: A model-scoped window limit stops the session while the account has headroom — fall back to another model instead of rotating or stalling
column: todo
created: 2026-08-06T14:04:19+0200
updated: 2026-08-06T14:04:19+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# Model-scoped window ⇒ switch model, don't rotate (janitor#222; owner failure report item 8)

## WHY (measured today, twice)

The owner hit a wall at ~14:00 and typed `/model opus` BY HAND — the second manual
intervention of the day, after the manual account rotation. The wall was NOT an
exhausted account: `fmuaddib` had 5h=42% and 7d=60% free, and only the **Fable
model-scoped** window was spent (~98%). The correct remedy was one keystroke sequence
(`ESC`, `/model opus`); instead the rotator EVICTED the fleet off the healthiest account
at 12:33 (`5h=35% 7d=59% Fable=97% -> rotate`) and then could not return to it, because
`is_safe_alternate` disqualifies an account on ANY window — so a one-model limit
sidelined the best account for the ~123h until that window resets.

## The task

Wire the EXISTING detector to the EXISTING injector.

1. **Trigger (the gate must be exact):** model-scoped window near/at its limit **AND**
   the account's 5h + 7d still have headroom. Firing on ACCOUNT pressure would switch
   models when the remedy is rotate-or-wait — the mirror of the rotator's mistake.
   Detection already exists and fired verbatim today:
   `[window-burn-rate] ⚠ fmuaddib (live) 7d/Fable window 98% at 26% elapsed` —
   `token_burn.model_windows_from_usage` already parses the scoped `limits[]` entries
   separately from 5h/7d. Nothing new to measure.
2. **Actuation:** ESC first (the pane may be mid-render or in a menu), then
   `/model <fallback>` — via the RATIFIED `terminal_trigger.inject_until_sent` chain
   (empty-field check, 8s retry, stop-on-keystroke, verified submit). Do NOT hand-roll
   a presence gate. The field read must take the LAST `❯` line, not the first (a
   selection menu draws `❯` on its selected row — the server's `agent-block-state.ts`
   hit this today).
3. **Fallback target:** configurable, default the next-best available model (Opus 5
   today). Never a model whose own scoped window is also spent.
4. **Say what it did:** one decision-log line + a findings-ledger entry. A silent model
   switch is confusing when the owner later wonders why answers changed character.
5. **Ask vs act:** default ACT (`/model` is non-destructive and reversible; the failure
   mode without it is a hard stop) behind a knob, per the owner's call.
6. **DERIVED — the rotator half:** `is_safe_alternate` must stop disqualifying an
   account on a MODEL-scoped window alone; a scoped-only limit should mark the account
   "safe, but not for model X". Otherwise the fleet keeps evicting its healthiest
   account. Coordinate on janitor#222 / TRDD-32acd15f.

## Acceptance

- [ ] gate fires ONLY on scoped-exhausted + account-has-headroom (unit-tested truth table)
- [ ] ESC + `/model <fallback>` lands via inject_until_sent on iTerm and tmux
- [ ] one observed unattended switch at a real scoped-window wall, with the log line
- [ ] `is_safe_alternate` no longer sidelines an account for a scoped-only limit
- [ ] harness agents explicitly out of scope (the server ships `model-opus`/`model-sonnet`
      on its own allowlist — janitor#222)

## Pointers

- janitor#222 (the ask, with the owner's verbatim directive + the measured table).
- Detection: `lib/token_burn.py` (`model_windows_from_usage`, `evaluate_trips`),
  `detectors/window-burn-rate.py`.
- Injection: `lib/terminal_trigger.py` (`inject_until_sent`), `scripts/resume_trigger.py`
  + `compact_trigger.py` as the existing self-typing precedents.
- Siblings: TRDD-UA4FAX67 (post-rotation ESC unblock — same actuation layer),
  TRDD-32acd15f (rotator selection policy).
