---
trdd-id: dccb0b8a-242f-4e6a-a93f-f266ed3c8d08
title: Daemon session-liveness watchdog — out-of-session freeze recovery
column: complete
created: 2026-06-21T19:22:05+0200
updated: 2026-07-11T13:25:00+0200
current-owner: janitor-dev
assignee: janitor-dev
priority: 0
severity: CRITICAL
effort: L
labels: [reliability, daemon, oauth, rate-limit, watchdog, guardian]
task-type: feature
parent-trdd: null
npt: [TRDD-dccb0b8a-npt-pane-record]
eht: []
blocked-by: []
relevant-rules: [1]
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, integration]
audit-requirements: []
review-requirements: [human-review]
runtime-targets: [macos]
impacts: [config-schema]
attempts: 0
last-test-result: not-run
implementation-commits: []
---

# TRDD-dccb0b8a — Daemon session-liveness watchdog (out-of-session freeze recovery)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-21

**Current state:** DESIGN. The root cause is fully diagnosed with hard evidence
(below). No code written yet for the watchdog. Immediate mitigation already
applied: this session's heartbeat re-armed (job `0cc5ac56`, session-only) +
stale `rate-limited.flag` cleared.

**NEXT ACTION:** implement Phase 1 — the PURE detection logic in
`scripts/lib/session_liveness.py` (`is_session_frozen(...)`) + its tests
(TDD). No I/O, no injection yet. Then Phase 2 (daemon task that gathers facts
and calls it), Phase 3 (recovery injection via `terminal_trigger`), Phase 4
(escalation ladder).

**Load-bearing facts / the WHY (forensic evidence, 2026-06-20→21):**
- 23:19:10 — the API returned `Server is temporarily limiting requests (NOT your
  usage limit) · Rate limited` at the same second `/go-on-yourself` queued. The
  turn died. This was a **server-side transient throttle**, not OAuth/quota — so
  account rotation would NOT have helped; only a **retry** would.
- The session transcript then went **silent for 19h50m** (23:19:10 → 19:09:39),
  zero entries. `dispatch.log` froze at 19:44 Jun 20; `stop-failure.log` kept
  capturing rate-limits (20:16, 21:04, 23:19) each saying "dispatch will emit
  resume cue on next heartbeat fire" — **but the heartbeat never fired again.**
- `CronList` at recovery time: **"No scheduled jobs"** — the in-session cron was
  GONE. Re-arming just now returned **session-only** despite `durable:true`
  (the documented CC downgrade, reproduced live).
- ROOT CAUSE: the recovery trigger (the heartbeat `CronCreate`) lives INSIDE the
  session it must rescue and is session-only on this CC build. When a turn dies
  (throttle/rate-limit/error) and no live cron remains, **nothing outside the
  session can re-fire it** → indefinite freeze until a human intervenes.

**SUPERSEDED — do NOT carry forward:**
- ✗ "OAuth degraded-rotate (v0.15.0) fixes the overnight freeze." It does NOT —
  that fixes account-quota DEADLOCK; the freeze was a server throttle + a dead
  in-session cron. Different failure class.

**Durable artifacts to read before acting:**
- The forensic evidence is reconstructed from `.janitor/logs/{dispatch,stop-failure}.log`
  and the session transcript `~/.claude/projects/<slug>/4eb7bf5d-*.jsonl` (the
  23:19 death-burst + the 20h silent gap). Re-derivable via the same parse.
- `scripts/lib/terminal_trigger.py` — the EXISTING keystroke-injection mechanism
  (`send_self_command`, `build_tmux_steps`, `match_agent_tmux`). Today it injects
  into "this session's OWN pane" (env `$TMUX_PANE`/`$ITERM_SESSION_ID`). The
  watchdog needs the daemon to inject into ANOTHER (frozen) session's pane.
- `scripts/daemon.py` — `Task`/`Task.run`, `_build_tasks`; where the new
  `task_session_liveness_watchdog` registers.

## Problem (the disease, not the symptom)

The janitor's self-recovery loop is: heartbeat cron fires a fresh turn →
`dispatch.py` sees `rate-limited.flag` → emits `[janitor-resume]` → the agent
continues. Every link works EXCEPT the first: the cron is a `CronCreate` that
**lives inside the very session it is meant to rescue**, and on this Claude Code
build `durable:true` is silently downgraded to **session-only**. So the moment a
session freezes (a dead turn + no live cron + a queued command), the recovery
trigger is frozen with it. The global daemon — alive, outside every session —
has no mechanism to reach in and wake it. A guardian whose trigger lives inside
the patient cannot rescue the patient.

## The fix — move the watchdog OUT of the session (daemon-side)

The global daemon becomes a **session-liveness watchdog**: it DETECTS a frozen
session from the outside and INJECTS recovery into its terminal pane — the
capability the user explicitly authorized ("control iTerm/tmux to inject
commands, inject ESC before the oauth-exhaust menu, even exit and relaunch a
claude instance").

### NPT — TRDD-dccb0b8a-npt-pane-record: session records its own pane id
The daemon can only target a pane it can name. The `on-session-start` hook (and
a refresh on each heartbeat) writes this session's terminal identity to
`$PROJECT/.janitor/state/terminal-pane.json` — `{tmux_pane, iterm_session_id,
pid, recorded_at}` from `$TMUX_PANE` / `$ITERM_SESSION_ID`. The daemon reads it.
Without this, pane resolution falls back to `terminal_trigger.match_agent_tmux`
(workingDirectory via the ai-maestro agents API) — best-effort only.

### Phase 1 — DETECTION (pure, fully tested first; TDD)
`scripts/lib/session_liveness.py` — pure functions, no I/O:
- `is_session_frozen(*, transcript_mtime, rate_limited_since, now, flag_present,
  heartbeat_interval_s, freeze_factor) -> bool` — TRUE iff a STUCK signal is
  present (a `rate-limited.flag` whose age > `freeze_factor`×heartbeat AND no
  transcript progress since the flag) — distinguishing **stuck** (rate-limited,
  no progress) from **legitimately idle** (no pending work). A healthy session
  clears its flag within one heartbeat; a stale flag + silent transcript = stuck.
- `recovery_cooldown_ok(last_attempt, now, cooldown_s) -> bool` — don't re-poke
  within the cooldown (anti-spam).
- `escalation_tier(attempts) -> int` — 1 (ESC+nudge) → 2 (re-arm) → 3 (relaunch).
Acceptance: a fresh rate-limit (flag age < 1 heartbeat) → NOT frozen; a stale
flag + silent transcript → frozen; an active session (transcript progressing) →
NEVER frozen; cooldown blocks re-poke; tiers escalate on repeated failure.

### Phase 2 — daemon task (gather facts → call Phase 1)
`task_session_liveness_watchdog` in `daemon.py` (cadence ~120s): enumerate live
project state dirs, read each `rate-limited.flag` age + transcript mtime + the
recorded pane, call `is_session_frozen`, and for each frozen+cooldown-ok session
hand off to Phase 3. Opt-in/gated by `CLAUDE_PLUGIN_OPTION_SESSION_WATCHDOG_ENABLED`
(default ON for this user; the capability is powerful, so it is gated + logged).

### Phase 3 — RECOVERY injection (reuse terminal_trigger)
For a frozen session's resolved pane, inject the **Tier-1** recovery: `ESC`
(dismiss any rate-limit/oauth modal so the REPL returns to idle) + a minimal
nudge that fires a fresh turn (a typed `/janitor-arm` re-arms the in-session
cron AND kicks a turn, doubling as recovery + re-protection). Reuse
`terminal_trigger.build_tmux_steps` / the iTerm osascript path; the only new
work is targeting ANOTHER pane (from `terminal-pane.json`) instead of `self`.
Every injection is logged to `global_state_dir()/session-watchdog.log` (audit).

### Phase 4 — ESCALATION ladder (bounded, last-resort relaunch)
If Tier-1 doesn't un-stick within N cycles: Tier-2 re-arm (typed `/janitor-arm`);
Tier-3 (last resort, user-authorized) relaunch `claude --continue` in the pane
when the process is gone / pane unresponsive. Each tier is bounded + cooled-down;
Tier-3 is itself gated by a stricter opt-in flag and ALWAYS logged.

## Safety invariants (every phase)
- Act ONLY on a clear STUCK signal (stale flag + no transcript progress); NEVER
  poke a healthy/active/idle-but-not-stuck session (transcript progressing ⇒ no-op).
- Per-session cooldown + bounded attempts per tier (no injection storms).
- Master opt-in gate + kill-switch honored; Tier-3 (relaunch) double-gated.
- Every injection logged with the pane, tier, and trigger evidence.
- Pure detection (Phase 1) is the testable core; the I/O wrapper is thin.

## Verification
- Unit (real, no mocks): `session_liveness` truth table (fresh vs stale flag,
  active vs silent transcript, cooldown, tier escalation).
- Integration: a fixture project state dir with a stale `rate-limited.flag` + a
  silent transcript → the daemon task selects it; a fresh flag → it does not; an
  active transcript → it does not. Injection path tested against a throwaway tmux
  pane (real tmux, send-keys verified by reading the pane back) — not mocked.
- `uv run scripts/publish.py` green before ship (no push until USER approves —
  the standing `/go-on-yourself` constraint).

## Why this is the real fix
The in-session cron is structurally incapable of being the sole recovery trigger
on a build that downgrades it to session-only. The ONLY reliable rescuer is a
process that lives OUTSIDE every session and can act ON a session — which is
exactly what the global daemon already is, minus the hands. This TRDD gives it
hands, safely and gated.
