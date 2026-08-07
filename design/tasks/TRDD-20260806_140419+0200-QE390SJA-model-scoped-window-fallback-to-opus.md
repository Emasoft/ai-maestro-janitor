---
trdd-id: QE390SJA
title: A model-scoped window limit stops the session while the account has headroom — fall back to another model instead of rotating or stalling
column: testing
created: 2026-08-06T14:04:19+0200
updated: 2026-08-06T16:47:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
relevant-rules: []
implementation-commits: [d7d8e9c9, dd72291c, 70afff57, b08c2d64, 491a2c3a, 251056e8, ab00a40e, 674fe785]
---

# Model-scoped window ⇒ switch model, don't rotate (janitor#222; owner failure report item 8)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Both halves are now CODE-COMPLETE. Exactly ONE acceptance box is open, and it needs the
owner at the pane — nothing else on this card can progress unattended.**

- **The detector half** (switch model instead of stalling) landed dark: gate `d7d8e9c9` +
  freshness `b08c2d64`, injector fixes `dd72291c`/`70afff57`, 3-state confirm `491a2c3a`,
  planner `251056e8`, detector + roster `ab00a40e`. `CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED`
  defaults OFF.
- **The rotator half** (item 6, our MIRROR gap) landed 2026-08-06 in `674fe785`:
  `token_burn.models_in_use` + `scoped_rotation_veto`, wired into `cmd_auto` as a DEMOTION to a
  second-choice pool plus a new tier 1b, so a scoped-spent target is deprioritized but never
  dropped. Falsified (3 of the new tests fail with the veto neutered; the control still
  passes). Full suite 14517 passed, ruff + mypy clean.

**Design constraint that governs any future change here, and the reason for the odd shape:**
the rule must never become a blanket scoped disqualification. That is the SERVER's bug on
janitor#222 and it benched the fleet's healthiest account for ~123h. Hence: every input is
positive evidence, all unknowns fail OPEN, and availability is still decided by the account
windows alone — the scoped rule only ORDERS the survivors.

**NEXT ACTION (owner-gated):** one human-watched live switch with
`CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED=1`. No test can prove the confirming keystroke
dismissed a real dialog, which is why it ships dark and why this box is still open.

The live 7d/Fable burn alarm on 2026-08-06 (77% at 24% elapsed, 3.3x pace, while the account's
own 7d sat at 47%) is a real-world instance of the exact divergence both halves target.

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
6. **DERIVED — the rotator half. CORRECTED 2026-08-06 after reading the source: the
   eviction was NOT ours, and our gap is the MIRROR of theirs.**

   Verified first-hand across three copies (working tree, cached 2.3.0, cached 2.4.1):
   the janitor's `rotator.is_safe_alternate(bfh, bsd)` takes ONLY the 5h and 7d windows —
   there is no scoped term anywhere in the janitor's selection path, and the string
   `live fmuaddib@gmail.com 5h=35% 7d=59% Fable=97% -> rotate` sitting in `state.json`
   CANNOT have been produced by any janitor version (all three build `live_desc` as
   `"5h=%s 7d=%s%s"`, no scoped clause). The `oauth-rotator-tick` chore was yielded to the
   ai-maestro server that morning (daemon log, `chore-coordination`), and the server's
   TypeScript rotator writes the SAME `state.json`. So the over-strict
   `bfh < SAFE_5H && bsd < SAFE_7D && (scoped === null || scoped < SAFE_SCOPED)` that
   sidelined the healthiest account for ~123h is THEIRS to fix — reported on janitor#222,
   not patched here (cross-project rule).

   **The janitor's own gap is the opposite one and is still real:** because
   `is_safe_alternate` ignores scoped windows entirely, a janitor-run rotation (server
   down, or the chore unclaimed) can rotate ONTO an account whose scoped window is already
   spent — trading one exhausted model for the same exhausted model on a different
   account. The fix is the same rule from the other side: a scoped-only limit marks an
   account "safe, but not for model X" — so it is a valid target only when the CURRENT
   model is not the exhausted one, or paired with the model switch above.

## Acceptance

- [ ] gate fires ONLY on scoped-exhausted + account-has-headroom (unit-tested truth table)
- [ ] ESC + `/model <fallback>` lands via inject_until_sent on iTerm and tmux
- [ ] one observed unattended switch at a real scoped-window wall, with the log line
- [x] janitor's `is_safe_alternate` stops IGNORING scoped windows (our mirror gap — it
      must not rotate ONTO an account whose scoped window is spent); the over-strict
      disqualification is the SERVER's and is reported on janitor#222, not fixed here
      — DONE `674fe785`, as a DEMOTION (tier 1b) so it can never become that over-strict bug
- [ ] harness agents explicitly out of scope (the server ships `model-opus`/`model-sonnet`
      on its own allowlist — janitor#222)

## Pointers

- janitor#222 (the ask, with the owner's verbatim directive + the measured table).
- Detection: `lib/token_burn.py` (`model_windows_from_usage`, `evaluate_trips`),
  `detectors/window-burn-rate.py`.
- Injection: `lib/terminal_trigger.py` (`inject_until_sent`), plus `scripts/resume_trigger.py`
  and `compact_trigger.py` as the existing self-typing precedents.
- Siblings: TRDD-UA4FAX67 (post-rotation ESC unblock — same actuation layer),
  TRDD-32acd15f (rotator selection policy).
