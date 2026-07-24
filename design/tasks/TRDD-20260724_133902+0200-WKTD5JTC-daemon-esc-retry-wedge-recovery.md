---
trdd-id: WKTD5JTC
title: Daemon detects the CC 429-retry-watchdog wedge and injects ESC to break it
column: todo
created: 2026-07-24T13:39:02+0200
updated: 2026-07-24T13:58:24+0200
current-owner: main
task-type: feature
scope: project
approval-tier: 0
relevant-rules: []
external-refs: [dccb0b8a, 324223a6, 32acd15f]
---

# Daemon detects the CC 429-retry-watchdog wedge and injects ESC to break it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-24

- **Origin:** owner hit `429 Rate limited · Retrying in 0s · attempt 5/300` in an interactive
  session; the UI wedged and did NOT resolve until an unrelated auto-compact happened to interrupt
  it. Owner directive: *"it should have been the janitor to do it, injecting esc."*
- **Root cause — VERIFIED in code (not assumed):** the daemon's ESC-injection recovery is reachable
  ONLY through the `frozen` diagnosis, and `frozen` requires `rate_limited=True`, which is the
  `rate-limited.flag`. That flag is written ONLY by `on-stop-failure`, which fires ONLY when a turn
  ENDS with an API error. The CC retry-watchdog (2.1.199, up to 300×) keeps the turn ALIVE and
  spinning, so the turn never ends → no flag → never `frozen` → **the ESC rung never fires.**
  Proof: `session_liveness.is_session_frozen` (returns False without `flag_present`),
  `session_liveness.diagnose_instance` (`frozen` only `if rate_limited:`), and the module docstring
  (lines 20-27) which explicitly DEFERS the retry-wedge to CC's own watchdog — that deferral is the
  bug, because CC's watchdog retries but never surrenders the interactive UI.
- **TWO BACKENDS (owner directive 2026-07-24) — split on `harness_backend.backend(env)`:**
  - **Standalone `#N` (iTerm/tmux):** the JANITOR daemon detects AND injects, **via Python** — it
    reads the iTerm session `contents` / `tmux capture-pane` from Python (osascript-from-Python, the
    `fleet_inject`/`fleet_scan` pattern) and injects a raw ESC from Python
    (`write text (character id 27)` / `tmux send-keys Escape`). This is the implementable janitor code.
  - **Harness `#J` (ai-maestro dashboard):** the ai-maestro SERVER owns the agent PTY and Family-A
    continuity, so the SERVER detects AND injects; the janitor **HANDS OFF** (the §1/§3 `server_owned`
    exclusion — two owners actuating one pane is the corruption the split prevents) and contributes
    ONLY the spec. That spec is written into `design/ARCHITECTURE.md` §8 this session — the sanctioned
    channel to the server (the TS port is built from that doc).
- **NEXT ACTION:** implement the STANDALONE (`#N`) Python path (Phase 1 below); consult
  `fable-advisor:advisor` first (>3-file daemon change: detection + diagnosis + actuation + tests).
  The harness (`#J`) path is the SERVER's to build from the ARCHITECTURE.md §8 contract — NOT janitor
  code. Do NOT start implementation on a rate-limited window; it is pure Python (zero model tokens at
  runtime) but authoring still costs session tokens.
- **Load-bearing facts:** the wedged session CANNOT self-recover (no hook fires mid-turn, no cron
  fires — the REPL is busy, not idle). An EXTERNAL actor is the ONLY one that can break it — the
  janitor daemon (standalone) or the ai-maestro server (harness). The janitor already resolves pane
  identity (`fleet_scan.parse_iterm_sessions`, `capture_terminal_identity`, `resolve_terminal_for_tty`)
  and already injects keystrokes (`fleet_inject`, the `esc_nudge` rung). What is MISSING is a detection
  signal that does not depend on the flag: **reading pane CONTENT**.
- **ALT-SCREEN CONSTRAINT (owner, 2026-07-24) — load-bearing for detection:** CC is a full-screen TUI
  on the ALTERNATE screen buffer (`\e[?1049h`) → **no scrollback history**. Detection can read only the
  CURRENT RENDERED FRAME, and only through a terminal EMULATOR. Standalone gets the emulator for free —
  tmux `capture-pane` / iTerm `contents` render the alt-screen frame. The server owns the RAW PTY and
  reads the grid from the dashboard's own xterm.js — a SERVER-SIDE `@xterm/headless` over the same PTY
  (`term.buffer.active`, the alt buffer), NOT the browser `Terminal` (closed for unattended agents);
  grepping raw PTY bytes FAILS (the retry line is redraw noise, rewritten in place as `attempt N`
  increments). The `attempt` counter advancing across polls while nothing else changes is itself the
  positive wedge signal. Injection is ESC-only per `[[claude-code-esc-input-semantics]]`: 1–2 ESC, no
  text, **NEVER Enter** (a stray Enter on the rewind overlay is the real danger), **NEVER Ctrl+C** (2nd
  press exits CC).
- **SUPERSEDED — do NOT carry forward:** the "daemon-only, single-backend" framing of the first
  revision — this is now explicitly two backends (standalone janitor Python vs ai-maestro server),
  per the 2026-07-24 owner directive.
- **Durable artifacts to read before acting:** `scripts/lib/session_liveness.py`,
  `scripts/lib/fleet_scan.py` (`gather_fleet`, `diagnose_root`), `scripts/lib/fleet_recovery.py`,
  `scripts/lib/fleet_inject.py`, `scripts/daemon.py::task_session_liveness`.

## Problem

An interactive (or unattended) session that hits a usage/throttle limit enters CC's retry-watchdog
loop: `429 Rate limited · Retrying in 0s · attempt N/300`. The turn is not dead — it is spinning
inside the watchdog, so:

1. `on-stop-failure` does not fire (fires on turn END) → **no `rate-limited.flag`**.
2. The heartbeat cron does not fire (crons fire when the REPL is IDLE; it is busy retrying).
3. Therefore nothing INSIDE the session can act, and the daemon's existing freeze-ladder — gated on
   the flag via `frozen` — never engages.

The session sits wedged until either the 300 retries exhaust (a long time) or a human presses ESC.
The whole point of the janitor's fleet-guardian is to remove exactly this "a human had to intervene"
failure mode; today it does not cover the most common trigger (a rate limit) because the trigger no
longer ends the turn.

## Design

Add a flag-independent wedge detector to the daemon's fleet-guardian and route it to the existing
ESC rung.

**1. Detect (new signal — pane CONTENT, not identity).** In `fleet_scan` (the daemon-side, runs
outside every session), for each live claude pane, capture the CURRENT RENDERED FRAME — CC runs on the
ALTERNATE screen buffer, so there is no scrollback; the terminal emulator renders the visible frame:
- tmux: `tmux capture-pane -p -t <pane>` — tmux IS the emulator; renders the current alt-screen frame.
- iTerm: osascript `contents of session id "<sid>"` — iTerm IS the emulator; returns the visible frame.
Match a retry-wedge signature — `Retrying in` on the same view as `attempt <n>/<m>` (and/or the
`429`/`Rate limited` token) via the pure `is_retry_wedge(text)`. Poll the frame each tick (no output
log exists to scan). FP guard: require `transcript_stale` (the on-disk transcript is independent of the
TUI and has not advanced), and treat the `attempt` counter ADVANCING across polls while nothing else
changes as the positive wedge signal (the frame redraws, but only the retry counter moves = not real
progress).

**2. Diagnose.** Add a `retry_wedged` diagnosis to `session_liveness.DIAGNOSES`, ranked just above
`frozen`. `diagnose_instance` gains a `retry_wedged: bool` fact and returns `retry_wedged` when the
pane shows the signature AND the transcript is stale AND the pane is alive AND it is not
server-owned/unarmed. Map `retry_wedged` → the ESC ladder (same actuation as `frozen`, rung 1 =
`esc_nudge`).

**3. Actuate (reuse existing).** `fleet_recovery` / `fleet_inject` already send ESC to a `frozen`
target; `retry_wedged` uses the identical gentle path (ESC only — never a hard/kill rung for a
merely-rate-limited session). ESC aborts the wedged turn → `on-stop-failure` fires → writes
`rate-limited.flag` → the EXISTING frozen-ladder + `[janitor-resume]` + OAuth-rotator recovery all
proceed as designed. So this change is purely "get the turn to END"; everything downstream already
works.

**4. Corroborate with the rotator (optional, Phase 2).** The OAuth rotator already knows an
account's live 5h/7d utilization (`rotator_usage`, `token_burn`). When the live account is at/near
100% AND a pane is wedged, that is a high-confidence wedge even before pane-text match — and the
right follow-up is rotate-then-resume, not just ESC. Wire the wedge detector to prefer a rotation
when a safe alternate account exists.

## Two-backend actuation (owner directive 2026-07-24) — WHO detects + injects

The wedged session cannot act on itself; an EXTERNAL actor must. WHO that actor is branches on
`harness_backend.backend(env)`, exactly like every other actuation in the plugin:

### Standalone `#N` (iTerm / tmux) — the JANITOR daemon, via Python

Pure Python, reusing the existing osascript/tmux plumbing:
- **Detect:** read pane CONTENT from Python —
  - iTerm: `osascript … contents of session id "<sid>"` (subprocess from Python; the `sid` already
    resolves via `fleet_scan.parse_iterm_sessions` / `ITERM_SESSION_ID`),
  - tmux: `tmux capture-pane -p -t <pane>`.
  Both read the RENDERED alt-screen frame via the terminal emulator (no scrollback exists); poll the
  frame each tick. Match `is_retry_wedge(text)` AND require `transcript_stale`.
- **Inject:** ESC key(s) from Python — 1 to abort the retrying turn; a 2nd only if the wedge persists
  (per `[[claude-code-esc-input-semantics]]`: ESC-only, no text, **NEVER Enter**, **NEVER Ctrl+C** —
  2nd Ctrl+C exits CC; a 2nd ESC on empty input may surface the rewind overlay, harmless unless Enter) —
  - iTerm: `osascript … tell session id "<sid>" to write text (character id 27) newline no`,
  - tmux: `tmux send-keys -t <pane> Escape`.
  This is ladder rung 1 (`esc_nudge`), reused verbatim.

### Harness `#J` (ai-maestro dashboard) — the ai-maestro SERVER

Inside a harness agent the janitor runs THIN and MUST NOT actuate a server-owned pane (§1/§3
`server_owned` exclusion — "unknown ⇒ HANDS OFF"; two owners typing into one PTY is the corruption
this split exists to prevent). The server owns the agent PTY and Family-A continuity, so the SERVER
detects and injects. The janitor's whole contribution here is the **spec** — written into
`design/ARCHITECTURE.md` §8 this session (the sanctioned janitor↔server contract channel; the TS
port is built from that doc). See §8 for the exact detect-string and inject-byte the server must
implement; the summary is: match the retry-wedge signature on the RENDERED xterm.js grid (the
dashboard already renders each agent with xterm.js — read a SERVER-SIDE `@xterm/headless` buffer, since
the alt-screen has no scrollback and raw PTY bytes are redraw noise), and on a genuinely-wedged agent
write 1–2 raw `ESC` (`0x1B`) to the PTY — never a command, never Enter, never Ctrl-C.
Everything downstream (turn aborts → `on-stop-failure` → `rate-limited.flag` → `ensure-resume`) is
already wired on both sides.

## Guardrails (must hold)

- **Never ESC a healthy/working session.** Gate on `transcript_stale` + live-pane + the pane-text
  signature together; a single false ESC on a working session discards real work. This is the same
  conservative bar `is_session_frozen` sets (its "load-bearing safety clause").
- **Never touch an `unarmed` or `server_owned` instance** — the existing precedence table already
  refuses these; `retry_wedged` is checked AFTER them.
- **ESC only** — `retry_wedged` never escalates to a hard/kill rung. A rate-limited session is not a
  crashed process; killing it is never the answer.
- **Cooldown / no injection storm** — reuse `recovery_cooldown_ok` + the attempt counter so at most
  one ESC per cooldown window per session.
- **Fail-open** — a pane whose content cannot be captured (no tmux/iTerm, TCC-denied osascript) is
  simply not wedge-detected; it degrades to today's behavior, never to a wrong action.

## Files (advisor consult first — >3 files)

- `scripts/lib/session_liveness.py` — `DIAGNOSES` += `retry_wedged`; `_DIAGNOSIS_RECOVERY`;
  `diagnose_instance(retry_wedged=...)`; new pure `is_retry_wedge(text) -> bool`.
- `scripts/lib/fleet_scan.py` — capture pane content per instance; feed `retry_wedged` into
  `diagnose_root`.
- `scripts/lib/fleet_recovery.py` / `fleet_inject.py` — route `retry_wedged` to the ESC rung
  (mostly reuse).
- `scripts/daemon.py::task_session_liveness` — pass the new fact through.
- `tests/` — `is_retry_wedge` truth table (matches the real `429 · Retrying · attempt N/300` line;
  rejects scrollback-only / progressed sessions); `diagnose_instance` precedence with the new state.
- **Harness `#J`: NO janitor files.** The ai-maestro server implements detection + injection from
  `design/ARCHITECTURE.md` §8; the janitor ships only the §8 contract and this TRDD. The pure
  `is_retry_wedge` matcher SHOULD be shared verbatim (same regex both sides) so the standalone Python
  and the server TS agree byte-for-byte on what counts as wedged.

## Verification

1. `is_retry_wedge` matches the exact wedge line and rejects a session that merely shows it in
   scrollback but has a fresh transcript. `cargo`/`pytest` green.
2. Seed a fake fleet: one pane showing the retry signature + stale transcript → daemon injects
   exactly one ESC (cooldown-bounded); a healthy pane → no injection; an `unarmed` pane → no
   injection.
3. End-to-end (manual, on a real rate limit): the daemon breaks the wedge with ESC; `on-stop-failure`
   then writes `rate-limited.flag`; the next heartbeat emits `[janitor-resume]` (and, if the rotator
   is opted-in and a safe alternate exists, rotates first).

## Approval log

- 2026-07-24T13:39:02+0200 — Authored as `todo` (Tier 0: in-scope janitor feature, explicitly
  requested by the owner). Advisor consult required before implementation (>3-file daemon change).
