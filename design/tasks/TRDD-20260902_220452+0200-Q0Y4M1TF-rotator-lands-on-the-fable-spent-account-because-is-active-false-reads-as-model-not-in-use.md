---
trdd-id: Q0Y4M1TF
title: the rotator lands on the Fable-spent account because is_active false reads as model not in use, and a burn projection is allowed to do it
column: testing
created: 2026-09-02T22:04:52+0200
updated: 2026-09-02T22:36:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: critical
severity: critical
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [continuity, oauth-rotator, scoped-window, burn-gate, fable]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
---

# The rotator lands on the Fable-spent account because `is_active: false` reads as "model not in use", and a burn projection is allowed to do it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-02 22:05

- **Owner, 22:00:** "why the hell you rotate back to the account with the fable window
  exhausted??? i had to rotate again because of the janitor!"
- **Timeline (rotator.log):** 21:48:44 owner logged in by hand → emanuele (5h=80%, 7d=31%,
  7d/Fable=52% `is_active=false`). 21:53:38 `auto: switched emanuele -> fmuaddib (target
  5h=1% 7d=76%; … +BURN[5h wall projected in ~14 min])` — fmuaddib's 7d/Fable is **100%
  `is_active=true severity=critical`**. 21:54:45 onward: `SCOPED[7d/Fable=100%] … staying put
  (model fallback owns the recovery)`. 21:59:12 owner rotated by hand again. The projected
  wall never came: emanuele 85% at 21:53, 86% at 22:02.
- **Root cause 1 (verified on the live payloads, `token_burn.models_in_use`):** the veto that
  demotes a target spent on the live session's model requires the LIVE account to show that
  model "in use", and `models_in_use` treated `is_active: false` as withdrawing that
  evidence. On the API `is_active` means the LIMIT is binding — true only at 100%, false on
  every healthy account — so from a healthy live account in_use was `{}`, the veto was None
  for every target, and drain-first (highest utilization wins) then PREFERRED the 100%-Fable
  account. Measured 22:00: emanuele in_use `[]`, ipazia `[]`, fmuaddib `['fable']`; all six
  pairwise vetoes None.
- **Root cause 2 (`rotator.cmd_auto` tier 1b):** even with the veto working, tier 1b rotates
  onto a scoped-spent target "anyway" whenever `best` is None — designed for a REAL wall
  (threshold/429), where any credential beats none. The 21:53 trigger was a burn-gate
  PROJECTION only, which traded a working model for a hard wall on a guess.
- **Fix:** `models_in_use` ignores `is_active` (evidence is `util > 0`); `cmd_auto` carries
  `burn_only` and stays put when the trigger is a projection and every target is spent on
  the model in use. Tests: `test_is_active_false_does_not_withdraw_the_in_use_evidence`,
  `test_cmd_auto_burn_projection_alone_never_rotates_onto_a_target_spent_on_the_model_in_use`;
  202 green across the rotator, burn-rate and model-fallback suites.
- **Shipped in 3.4.13** (published 22:13, all 5 CI runs on bump sha ca398cf8 green). Daemon
  respawned 22:22:18 on the staged 3.4.13 (`os-keepalive: newer version staged`), so the
  21:53 move can no longer repeat on a burn projection. The C3 `certified last-good=3.4.13`
  re-pin is periodic and had not fired by 22:36 — not a tamper signal (see CLAUDE.md).
- **Review-fork finding (22:19), carry to N954KWUC:** "model in use" as read from
  `/api/oauth/usage` means *used this week* — the API only emits weekly scoped windows, so
  `util > 0` cannot distinguish "the live session is on Fable now" from "Fable was touched
  this week". The per-session, per-pane signal is the model badge on the status row; the
  one-screen-state reader in TRDD-N954KWUC is where that belongs.
- **NEXT ACTION:** the live box below (a day with no rotation onto a 7d/Fable ≥ 99% target).

## Acceptance

- [x] `models_in_use` reports Fable for a payload whose Fable window is 52% `is_active=false`.
- [x] A burn-projection trigger with every target Fable-spent rotates nowhere and logs why.
- [ ] Live: no rotation onto a target whose 7d/Fable is ≥ 99% while the live session runs
      Fable, across one full day of rotator.log.

## Approval log

## Notes and lessons learned
