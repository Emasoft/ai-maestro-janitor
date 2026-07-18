---
trdd-id: P7WU40G9
title: Overnight-stall triad — rotation deadlock + janitor over-compaction + rate-limit recovery flood
column: dev
created: 2026-07-18T06:03:23+0200
updated: 2026-07-18T06:03:23+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
related-trdd: [32acd15f, 8DR0X08A, 324223A6, EUWIHP0G, D3PROACT, TKNSTP82]
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-18

**INCIDENT (owner, 2026-07-18, verbatim across several messages):** overnight every Claude
stalled for hours after a 429; the owner had to rotate manually every time. The moment they
rotated + resumed, the janitor rotator ALSO rotated (redundant). ANIME2SVG got a FLOOD of
`/janitor-arm` commands buffered on its input line, blocking the session. And the janitor kept
typing `/compact` into a session at only ~49% context.

Three INDEPENDENT bugs, root-caused from live logs (rotator.log, daemon.log, the ANIME2SVG
iTerm pane, per-account `usage`), all confirmed with evidence — NOT the binary chore switch
(TRDD-LU0C5KAR: server-liveness probe ABSENT, rotator ticked every 60s the whole time).

### BUG 1 — rotation deadlock (the root cause of the stall). IMPLEMENTED.
`is_safe_alternate(bfh, bsd)` required an alternate be below `SAFE` on BOTH windows, with
`SAFE_5H = SAFE_7D = 90`. Overnight the two alternates had FRESH 5h (≈0%) but high 7d
(fmuaddib 90%, emanuele 94%), so `90 < 90` was False → both rejected → the rotator logged
`all paid accounts maxed; waiting for a window to reset` for HOURS while sitting on the
fully-exhausted live account (ipazia 5h=100%). A manual `/login` onto the "unsafe" fmuaddib
worked INSTANTLY (5h=3%) — proving the rejected account was fully usable.
**The windows are not equally precious (owner):** 7d 1% ≈ hours, 10% ≈ most of a day → reject
7d ONLY at the true wall (99); 5h is cheap (refills every 5h) → reject a little earlier (97).
**Fix:** `SAFE_5H 90→97`, `SAFE_7D 90→99`, `SWITCH_AT_7D 97→99` (SWITCH must sit ≥ SAFE per
window or we rotate away from an account we'd re-accept — thrash); `SWITCH_AT_5H` stays 97.
`scripts/oauth_rotator/rotator.py` constants + comment; `tests/test_oauth_rotator.py`
(`test_switch_and_safe_thresholds_are_window_asymmetric`,
`test_fresh_5h_high_7d_alternate_is_a_valid_target` — the 3am regression).

### BUG 2 — janitor over-compaction (the /compact-at-49% injection). IMPLEMENTED.
`cold_cache_compact.min_context_tokens()` was a FIXED `350_000` — floor-relative, not
window-relative — so on a 1M window it fired at 35%+, and `on-stop-proactive-compact.py`
compacted at 488k (49%). **Owner rule:** the janitor must NEVER compete with the harness
auto-compact — it only backstops a FAILED harness compaction, so it fires only ABOVE the
harness's own effective compact point (`CLAUDE_CODE_AUTO_COMPACT_WINDOW - overhead`, the
owner's 700000-34000 = 666000). **Fix:** `min_context_tokens()` is now HARNESS-RELATIVE:
override wins → else `effective_compact_point + margin(50k)` (user: 716k) → else
`window - overhead + margin` (unset: 1.016M, unreachable → harness owns it), floored at
`DEFAULT_MIN_CONTEXT_TOKENS` so a tiny auto-window can't compact a floor-sized context.
`scripts/lib/cold_cache_compact.py`; `tests/test_cold_cache_compact.py`
(`test_min_context_is_harness_relative`, `test_min_context_never_below_the_floor_...`).
LIVE MITIGATION already applied this session: wrote `.janitor/state/cold-compact-fired.ts`
= now+2h so the running 0.52.0 hook is suppressed until the release lands.

### BUG 3 — rate-limit recovery flood (the `/janitor-arm` pile-up). NOT YET IMPLEMENTED — NEXT.
A rate-limited session sits in Claude Code's retry-watchdog "Retrying in Xm" state (blocks
input). `session_liveness.diagnose_instance`: `transcript_stale AND rate_limited → "frozen"`
→ `fleet_recovery.action_for("frozen")` walks `_FROZEN_LADDER = (rearm, reload, update)` →
TYPES `/janitor-arm` (ESC-first). But the retry-wait BUFFERS keystrokes: the ESC doesn't
reliably break it, the `/janitor-arm` TEXT accumulates on the one input line
(`/janitor-arm/janitor-arm/janitor-arm…`), and when the owner finally double-ESCs the buffer
flushes → the flood executes, wasting tokens. TRDD-8DR0X08A's wedged short-circuit MISSES this:
a retry-blocked session has `trailing_enqueues=0` (the typed text is never SUBMITTED as
queue-operation records). **Proven recovery:** ONE ESC to the pane broke ANIME2SVG's retry AND
forced a credential re-read (jumped ipazia→fmuaddib, 5h 99%→3%); its own `rate-limited.flag`
→ `[janitor-resume]` then resumed the work.
**Planned fix (ESC-ONLY, no command typing):**
1. `session_liveness.diagnose_instance`: `rate_limited` → NEW diagnosis `"rate_limited"` (not
   `"frozen"`); add to `_DIAGNOSIS_RECOVERY` → `"esc"`.
2. `fleet_recovery.action_for`: `"rate_limited" → "esc"` (ESC-only; keep the `frozen` ladder for
   a genuine mid-turn wedge, which is now only reached via the daemon's `trailing_enqueues`
   path). `injection_is_hard`: `"esc"`/`"rate_limited"` is hard (ESC IS the unwedge).
3. `fleet_inject`: an `"esc"` action that sends ESC (TWICE — owner: "double ESC") and types NO
   command. The session's own `rate-limited.flag → [janitor-resume]` handles continuation.
   With BUG 1 fixed, rotation has already moved to a healthy account by the time ESC fires.
4. Tests: a rate-limited peer is diagnosed `rate_limited`; its recovery is `esc`; the injection
   plan carries ESC and ZERO slash-command text (regression against the flood).

## NEXT ACTION
Ship BUG 1 + BUG 2 in v0.53.0 NOW (owner wants relief ASAP — they are actively getting hit).
Then implement BUG 3 (the 4-step ESC-only fix above) with tests and ship v0.54.0.

## Notes and lessons learned

[^1]: [id:ATOM-ROTA-7DPX, status:valid, keywords:"rotation all accounts maxed deadlock 7d window precious safe threshold reject only at 99 fresh 5h high 7d usable", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT gate a rotation-target's 7-day window on the same conservative SAFE margin as the 5-hour
  window, BECAUSE 10% of the 7d window is ~a full day of usable tokens — rejecting a fresh-5h/90%-7d
  account as "unsafe" pinned the fleet to a dead live account for hours. DO reject the 7d only at the
  true wall (99) and the cheap 5h a little earlier (97).

[^2]: [id:ATOM-CMPT-HREL, status:valid, keywords:"janitor compacts at 49 percent too early min_context_tokens fixed 350k window relative auto compact window backstop", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT set the janitor's compact threshold as a FIXED token count, BECAUSE 350k is 35% of a 1M
  window and fired /compact at 49% — competing with the harness's own auto-compact. DO make it
  HARNESS-RELATIVE: fire only ABOVE `CLAUDE_CODE_AUTO_COMPACT_WINDOW - overhead`, so the janitor
  only ever backstops a harness compaction that actually failed.

[^3]: [id:ATOM-FLOOD-ESC, status:valid, keywords:"janitor-arm flood buffered input rate limited retrying frozen recovery esc only trailing_enqueues zero", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT type a slash-command into a rate-limited session (Claude Code's "Retrying in Xm" state),
  BECAUSE its retry-watchdog BUFFERS keystrokes: the command text accumulates on the input line and
  floods when the wait finally breaks — and `trailing_enqueues=0` (never submitted) so the wedged
  short-circuit misses it. DO send ESC-only (the unwedge) and let the session's own
  `rate-limited.flag → [janitor-resume]` resume it.
