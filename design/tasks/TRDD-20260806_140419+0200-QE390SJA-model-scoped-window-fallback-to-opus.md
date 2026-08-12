---
trdd-id: QE390SJA
title: A model-scoped window limit stops the session while the account has headroom — fall back to another model instead of rotating or stalling
column: backburner
review-after: 2026-08-26
created: 2026-08-06T14:04:19+0200
updated: 2026-08-12T00:12:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
relevant-rules: []
implementation-commits: [d7d8e9c9, dd72291c, 70afff57, b08c2d64, 491a2c3a, 251056e8, ab00a40e, 674fe785]
---

# Model-scoped window ⇒ switch model, don't rotate (janitor#222; owner failure report item 8)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

**EVERY IMPLEMENTABLE BOX IS CLOSED. The card is parked in `backburner` with
`review-after: 2026-08-26` because the only residue is a FIELD OBSERVATION that arrives on
its own — there is no work here to pull, and leaving it in `testing` was a column asserting
active work nobody was doing.**

**SUPERSEDED — do NOT carry forward:** the two claims below, both written when the feature
shipped dark, are now FALSE and were self-contradictory even before that:
  - *"it ships dark, which is why this box is still open"* — it has been DEFAULT ON since
    2026-08-11 (`scripts/lib/model_fallback.py::enabled`). The observation box stayed open
    because the event has not happened yet, NOT because a human must enable anything.
  - *"exactly ONE acceptance box is open"* — FOUR were unchecked when that sentence was
    written. Three of them were already satisfied by code and tests that existed at the time;
    the sentence was measuring intent, not the file.

**Verified first-hand 2026-08-12 (file:line, per the claim-verification rule):**
  - **Gate truth table — CLOSED.** Eight named tests in `tests/test_window_burn_rate.py`,
    including the load-bearing NEGATIVE one: `test_model_fallback_silent_when_the_account_is_
    the_constraint` (account 7d=95% ⇒ verdict None, so account pressure can never trigger a
    model switch), plus `..._requires_PROVEN_account_headroom`, `..._refuses_a_STALE_snapshot`
    and `..._refuses_an_UNKNOWN_snapshot_age` — the fail-open discipline the design constraint
    below demands.
  - **Actuation on BOTH readable channels — CLOSED today.** The tmux order trace already
    existed (`test_send_verified_escs_then_types_then_submits_in_order`); iTerm was proven
    only at the BUILDER level, which cannot catch a channel wired up in the wrong order. Added
    `test_send_verified_escs_types_and_submits_on_ITERM_too` — same trace through the
    AppleScript spelling (ESC = `character id 27`, typing = `write text "…" without newline`,
    Enter = an EMPTY `write text ""`). `build_type_only_steps` / `build_submit_steps` /
    `build_esc_only_steps` each handle exactly `tmux` and `iterm`; every other channel is
    REFUSED with a reason rather than silently reported sent.
  - **Harness agents out of scope — CLOSED.** `scripts/dispatch.py:461` denies `model-fallback`
    to harness agents, guarded by `test_detector_is_on_the_roster_and_denied_to_harness_agents`.
  - **The detector RUNS** (the shipped-dark trap): it is on the roster at
    `scripts/dispatch.py:431` with a 60s interval, not merely present on disk.

**NEXT ACTION:** none that can be pulled. At the next real scoped-window wall the detector
switches the model unattended and writes the decision-log line + a findings-ledger entry;
tick the last box with that evidence. If `review-after` expires with no wall observed, decide
then whether an unobserved-but-fully-tested feature should just be closed.

**Do NOT "fix" the remaining box by forcing a synthetic wall** — the box exists to prove the
confirming keystroke dismissed a REAL dialog, and a synthetic one proves the mock.

- **The detector half** (switch model instead of stalling) landed dark: gate `d7d8e9c9` +
  freshness `b08c2d64`, injector fixes `dd72291c`/`70afff57`, 3-state confirm `491a2c3a`,
  planner `251056e8`, detector + roster `ab00a40e`. **UPDATE 2026-08-11:** flipped to
  DEFAULT ON — `CLAUDE_PLUGIN_OPTION_MODEL_FALLBACK_ENABLED` now defaults true (still
  disableable with a false spelling), because an idle session on a spent model window cannot
  self-heal any other way. See `scripts/lib/model_fallback.py::enabled`.
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

- [x] gate fires ONLY on scoped-exhausted + account-has-headroom (unit-tested truth table)
      — 8 tests in `tests/test_window_burn_rate.py`, incl. the negative account-pressure case
- [x] ESC + `/model <fallback>` lands on iTerm and tmux — via `terminal_trigger.send_verified`
      (the verified-typing entry point of the ratified chain, NOT `inject_until_sent`, which
      this line originally named; corrected to the function the code actually calls). Order
      traces for both channels in `tests/test_terminal_trigger_readback.py`
- [ ] one observed unattended switch at a real scoped-window wall, with the log line
      — the only open box; it is no longer owner-gated (default ON since 2026-08-11), it is
      simply waiting for the event. Parked with `review-after: 2026-08-26`
- [x] janitor's `is_safe_alternate` stops IGNORING scoped windows (our mirror gap — it
      must not rotate ONTO an account whose scoped window is spent); the over-strict
      disqualification is the SERVER's and is reported on janitor#222, not fixed here
      — DONE `674fe785`, as a DEMOTION (tier 1b) so it can never become that over-strict bug
- [x] harness agents explicitly out of scope (the server ships `model-opus`/`model-sonnet`
      on its own allowlist — janitor#222) — denied at `scripts/dispatch.py:461`, guarded by
      `test_detector_is_on_the_roster_and_denied_to_harness_agents`

## Pointers

- janitor#222 (the ask, with the owner's verbatim directive + the measured table).
- Detection: `lib/token_burn.py` (`model_windows_from_usage`, `evaluate_trips`),
  `detectors/window-burn-rate.py`.
- Injection: `lib/terminal_trigger.py` (`inject_until_sent`), plus `scripts/resume_trigger.py`
  and `compact_trigger.py` as the existing self-typing precedents.
- Siblings: TRDD-UA4FAX67 (post-rotation ESC unblock — same actuation layer),
  TRDD-32acd15f (rotator selection policy).
