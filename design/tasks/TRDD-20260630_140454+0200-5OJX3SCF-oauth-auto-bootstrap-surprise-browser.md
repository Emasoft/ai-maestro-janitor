---
trdd-id: 5OJX3SCF
title: OAuth auto-bootstrap opens a surprise headful Chrome + uncapped relaunch
column: complete
created: 2026-06-30T14:04:54+0200
updated: 2026-06-30T14:20:40+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: M
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 1
implementation-commits: [b35121c]
---

# OAuth auto-bootstrap opens a surprise headful Chrome + uncapped relaunch

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-30

- **USER complaint (#oa):** "the rotation of oauth triggered without reason." Investigated
  read-only (report:
  `reports/oauth-investigation/20260630_135918+0200-rotation-without-reason.md`).
- **ROOT CAUSE (HIGH confidence):** NOT a spurious LIVE rotation — last real account switch
  was 6.7 days ago, legitimately (live `f***` hit 429×3 → rotate); the live account is
  "within limits" every tick now. What the user actually saw was the daemon's **post-login
  AUTO-BOOTSTRAP** opening a **HEADFUL Chrome** today 10:56 to mint a refresh token for the
  seeded alternate slot `<account-fmuaddib>` (a known DEAD-refresh account). The live
  credential was never touched. The daemon disarm + global-pause flags were set minutes
  AFTER 10:56 — the user reacting to the surprise window (this is THIS session's origin).
- **Path:** `daemon.task_oauth_rotator_tick` → `rotator.cmd_tick` → (DEAD LAST)
  `_bootstrap_seeded_slots` (rotator.py:1571) → for each `RENEW_COOKIE`-leg slot (no usable
  refresh + a live claude.ai session cookie, `cascade.classify`) → `_invoke_slot_capture`
  (rotator.py:1507) → detached headful Chrome.
- **Two real defects (pre-existing, NOT regressions, addressed by no commit ≤ a260bd4):**
  1. **Auto-launch is ON whenever the rotation opt-in is on** — `/janitor-auto-manage-oauth-on`
     silently authorized the daemon to pop a browser. Opening a VISIBLE window is a
     higher-surprise act than a background token rotation and deserves its OWN opt-in.
  2. **No failure cap on the RENEW_COOKIE bootstrap path** — only a PID lock (skip-if-running),
     no attempt counter. A capture that never mints a refresh-bearing slot leaves the slot
     eligible forever → the daemon re-opens a browser EVERY ~60s tick. (The RENEW_REFRESH path
     DOES cap, via `refresh_failures` → REAUTH_NUDGE after `MAX_REFRESH_FAILURES`,
     TRDD-HJGR4I5W; the cookie path never got the equivalent guard.)
  (The historical CF-1010 every-tick relaunch ROOT CAUSE is already fixed in 6fdbeaa; the
  headful-default + uncapped-relaunch defects are separate and unfixed.)
- **FIX (this TRDD), all in `scripts/oauth_rotator/rotator.py`:**
  - **A — default-OFF auto-launch opt-in** `CLAUDE_ROTATOR_AUTO_BOOTSTRAP` (env, `_env_truthy`,
    default OFF). Gate at the top of `_bootstrap_seeded_slots`: when OFF, NEVER launch a
    browser — leave eligible slots for the human (the `oauth-capture-stalled` detector nudge
    already points at `/janitor-refresh-claude-logins`). This makes the surprise impossible by
    default while keeping rotation+keepalive working. SEPARATE from the rotation opt-in.
  - **B — per-slot launch cap** `MAX_BOOTSTRAP_LAUNCHES` (env `ROTATOR_MAX_BOOTSTRAP_LAUNCHES`,
    default 3 — mirrors `MAX_REFRESH_FAILURES`). Count LAUNCHES in the slot's state-index meta
    (`bootstrap_attempts`); STOP auto-launching at the cap. A successful capture REPLACES the
    slot meta (counter gone); a slot that regains a refresh resets the counter to 0, so a
    recovered account gets a fresh cap. Bounds the every-tick-browser runaway even when opted in.
  - **C — announce** each launch + the cap-boundary via `_log` (rotator.log), so an opted-in
    user's visible window is never "without reason."
- **✅ DONE (2026-06-30, b35121c):** shipped A+B+C + a pure `_bootstrap_action` truth table
  (the loop is a thin dispatcher). 488 rotator/oauth/daemon tests green; ruff+pyright clean.
  DERIVED (EHT) handled in the same commit: `/janitor-refresh-claude-logins` sets
  `CLAUDE_ROTATOR_AUTO_BOOTSTRAP=1` on its user-initiated `rotator.py tick` so the manual
  capture still works, and the `/janitor-auto-manage-oauth-on` skill's auto-bootstrap section
  is corrected to the default-off reality. PUBLISH is USER-GATED (auto-rolls the daemon).
- **(original plan):** implement A+B+C in `_bootstrap_seeded_slots` (+ the `MAX_BOOTSTRAP_LAUNCHES`
  constant near `MAX_REFRESH_FAILURES` L302); add tests (gate-off no-launch, gate-on launch +
  increment + announce, cap reached → no launch, recovered slot resets counter); ruff+pyright;
  run rotator tests; commit. PUBLISH is USER-GATED (auto-rolls the daemon).
- **Load-bearing facts:** `_invoke_slot_capture` returns True=LAUNCHED / False=PID-skip — count
  ONLY True. The capture is fire-and-forget (success observed a LATER tick when the slot gains a
  refresh → no longer eligible). `_bootstrap_seeded_slots` is the POLICY layer (gate+cap here);
  `_invoke_slot_capture` stays the pure launch seam (the one monkeypatched in tests). The daemon
  inherits env at spawn, same as `CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS`.

## Why

A guardian daemon that opens a focus-stealing browser window unprompted — and, on a dead
account, re-opens it every minute forever — is indistinguishable from "OAuth fired for no
reason" and (per this incident) makes the user disarm the whole janitor. Opening an external
visible process from an unattended daemon must be (a) explicitly opted into, (b) attempt-capped,
and (c) announced. This is the exact structural analogue of TRDD-HJGR4I5W for the RENEW_COOKIE leg.

## Acceptance

- Default (no `CLAUDE_ROTATOR_AUTO_BOOTSTRAP`): an eligible seeded slot NEVER launches a browser;
  `_invoke_slot_capture` is not called.
- Opted-in: an eligible slot launches once per tick up to `MAX_BOOTSTRAP_LAUNCHES`, each launch
  increments `bootstrap_attempts` and emits a `_log` line; at the cap, no further launch + a
  single cap `_log` line.
- A slot that gains a refresh (no longer eligible) has its `bootstrap_attempts` reset to 0.
- Every path stays best-effort (a launch/log failure never aborts the loop or the tick).
- Existing rotator tests pass.

## Notes and lessons learned
