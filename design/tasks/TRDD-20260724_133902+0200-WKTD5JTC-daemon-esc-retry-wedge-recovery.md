---
trdd-id: WKTD5JTC
title: Daemon detects the CC 429-retry-watchdog wedge and injects ESC to break it
column: todo
created: 2026-07-24T13:39:02+0200
updated: 2026-07-24T14:26:19+0200
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
- **NEXT ACTION (REVISED after advisor review — see `## Advisor review` below):** do NOT write code
  yet. FIRST empirically verify the two load-bearing assumptions on a REAL wedge (cheapest possible
  signal; if either fails, the design changes shape):
  - **(1a)** During the `Retrying … attempt N/300` loop, does CC append records to the session
    `.jsonl`? If YES, `transcript_stale` NEVER trips and the whole flag-independent detection is dead
    — the gate must switch to "signature present + attempt-number advanced", NOT transcript-stale.
    Check: tail the session `.jsonl` mtime/lines across the wedge.
  - **(1b)** Does injecting ESC end the turn via `on-stop-failure` (API-error path, writes
    `rate-limited.flag`) or via plain `Stop` (user-cancel path, NO flag)? If plain `Stop`, the
    `[janitor-resume]` chain never fires — so the DAEMON must write `rate-limited.flag` itself right
    before the ESC (precedent: `fleet_scan.sweep_stale_rate_limit` already writes/removes that flag).
  THEN implement the corrected Phase 1 (below). The harness (`#J`) path is the SERVER's to build from
  ARCHITECTURE.md §8. Advisor consult DONE (Fable 5, approve-with-changes). Do NOT implement on a
  rate-limited window.
- **ADVISOR CORRECTIONS (Fable 5, 2026-07-24) — MUST hold in the implementation:**
  - **`retry_wedged` gets its OWN esc-only recovery, NOT `"ladder"`.** `daemon.py` calls
    `action_for(..., include_hard=True)`, so `"ladder"` returns `force_restart` (a KILL) at attempts≥3
    when hard-restart is enabled — a retry-wedge must NEVER kill. Add a dedicated `_DIAGNOSIS_RECOVERY`
    value that is esc-only at every attempt; exhaustion → crash-loop human alert / rotate, never a kill.
  - **`injection_is_hard(retry_wedged)` must return True**, else the `trailing_enqueues` short-circuit
    in `daemon.py` declines the ESC and pages a human instead of injecting.
  - **The "nothing else on the frame changes" heuristic is impossible** — the countdown / spinner /
    statusline clock change every poll. EXTRACT the `attempt N` number via a capture group in
    `is_retry_wedge` and compare against PERSISTED episode state (first-seen attempt): advance = wedged,
    a DECREASE = new episode, clear state when the signature vanishes. Backoffs (2m50s) exceed the
    ~120s beat so adjacent polls can TIE on the same attempt — a tie is not progress, keep polling.
    The advance requirement stays: it is the ONLY guard against a pane STATICALLY displaying the string
    (this very TRDD contains it verbatim → a naive substring match self-triggers).
  - **iTerm capture AND inject both ride osascript** → the launchd daemon's TCC denial
    (TRDD-VQ4LX7ND, observed 0/254 beats) silently kills both, and `fire()` reports "spawned" as
    "delivered". DECLINE early when `iterm-automation-blocked.flag` is set instead of burning attempts.
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
- **CAUSE-AGNOSTIC signature (owner incident 2026-07-24):** the wedge fires for MORE than a 429 —
  observed live as `✻ Session limit reached · Retrying in 2m 50s (2:10pm) · attempt 1/300`. Same wedge,
  different cause. `is_retry_wedge` MUST key on the invariant `Retrying in … attempt N/M`
  (`/retrying\s+in\b.*\battempt\s+\d+\s*\/\s*\d+/i`), NOT on `429`/`rate limit` — a cause-specific
  regex misses the session-limit wedge. Cause words are optional context to log.
- **ESC BEFORE ROTATION (owner: "you failed to rotate again"):** a wedged turn holds the OLD credential
  inside its retry loop, so daemon/server rotation while it spins is a NO-OP — the turn never re-reads
  the credential. Order is ESC-first (end the turn) → rotated credential picked up on resume. So even
  when rotating, the actor MUST ESC to break the wedge; rotation alone cannot rescue a live wedge.
- **STATUSLINE % IS A LAGGING INDICATOR — never a detection gate (owner, 2026-07-24):** the meter
  read `5h 98%` while the session had ALREADY hit `Session limit reached` (true window = 100%). The
  statusline refreshes on its own slow cadence, so gating detection on a usage-% threshold would MISS
  real wedges. The wedge LINE on the rendered frame is authoritative; the % is decorative. (Rotation
  reads LIVE `/api/oauth/usage` via `rotator_usage`, not the statusline — unaffected.)
- **xterm.js detection (source-verified 2026-07-24):** event-driven via core `term.onWriteParsed`
  (`xterm.d.ts:1100`) or `onRender` — fire the buffer-read + regex per write; NOT the search addon's
  `searchResultsChanged`/`onDidChangeResults` (fires only for an active search with decorations = "match
  set changed", not "string appeared"; drags in the DOM path). `SearchResultTracker.ts` at the cited
  raw URL 404s on master (moved) — do not chase it.
- **SUPERSEDED — do NOT carry forward:** the "daemon-only, single-backend" framing of the first
  revision — this is now explicitly two backends (standalone janitor Python vs ai-maestro server),
  per the 2026-07-24 owner directive. Also SUPERSEDED: any `429`/`rate-limit`-KEYED signature — the
  regex is now the cause-agnostic `Retrying in … attempt N/M` (session-limit wedges proved it).
- **SERVER NOTIFIED (2026-07-24):** the `#J` half was explained to the ai-maestro Claude in
  **ai-maestro#90** (https://github.com/Emasoft/ai-maestro/issues/90) — a self-contained copy of the
  §8 contract. Caveat recorded there: the ARCHITECTURE.md §8 rev-7 content is in 55 unpushed janitor
  commits, so the GitHub design-doc link 404s until pushed; the issue body carries the full spec so the
  server can act regardless. Once pushed, ratify §8 rev 7 on janitor#100 as usual.
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
pane shows the signature AND (per §1a) the attempt-number has ADVANCED across polls AND the pane is
alive AND it is not server-owned/unarmed. **Map `retry_wedged` to its OWN esc-only recovery, NOT the
`"ladder"`** (advisor: `"ladder"` returns `force_restart`/kill at attempts≥3 under
`include_hard=True`). A retry-wedge is esc-only at EVERY attempt; sustained failure → crash-loop human
alert / rotate, never a kill.

**3. Actuate (reuse ESC injection, NOT the frozen recovery mapping).** `fleet_inject` already sends
ESC; `retry_wedged` reuses that gentle path (ESC only). **`injection_is_hard(retry_wedged)` MUST
return True** so the `trailing_enqueues` short-circuit in `daemon.py` does not decline the ESC and page
a human. **Decline early when `iterm-automation-blocked.flag` is set** (iTerm capture+inject both ride
osascript, TCC-denied on the launchd daemon; `fire()` falsely reports "delivered"). ESC ends the turn
→ **(per §1b) if that fires plain `Stop` not `on-stop-failure`, the daemon writes `rate-limited.flag`
itself BEFORE the ESC** → then the EXISTING `[janitor-resume]` + OAuth-rotator recovery proceed. NOTE:
"everything downstream already works" is CONDITIONAL on §1b — verify first.

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

## Advisor review (Fable 5, 2026-07-24) — APPROVE-WITH-CHANGES

Verdict: detection SURFACE is right, but two unverified empirical assumptions are load-bearing and the
`retry_wedged → "ladder"` mapping violates the never-kill guardrail. Ranked concerns (all folded into
the STATE block + Design above):
1. **Verify 1a/1b on a real wedge BEFORE writing code** — cheapest possible signal. (1a) if CC appends
   to the `.jsonl` during the retry loop, `transcript_stale` never trips → detection dead; switch the
   gate to signature+attempt-advance. (1b) ESC may fire plain `Stop` (user-cancel), not
   `on-stop-failure` (API-error) → no flag → no resume; fallback = daemon writes the flag before ESC.
2. **`retry_wedged` needs its own esc-only `_DIAGNOSIS_RECOVERY` + `injection_is_hard=True`** —
   `"ladder"` kills at attempts≥3 under `include_hard=True`; and without `injection_is_hard` the
   `trailing_enqueues` short-circuit declines the ESC.
3. **Extract the `attempt N` number (capture group) + persist episode state** — "nothing else changes"
   is impossible (countdown/spinner/clock move every poll); a static display of the string
   self-triggers (this TRDD contains it); ties on long backoffs are not progress.
4. **Stale-gate the capture** (≈0 captures/beat on a healthy host) and **decline on
   `iterm-automation-blocked.flag`** (osascript TCC denial silently no-ops capture AND inject).

## Approval log

- 2026-07-24T13:39:02+0200 — Authored as `todo` (Tier 0: in-scope janitor feature, explicitly
  requested by the owner). Advisor consult required before implementation (>3-file daemon change).
- 2026-07-24T14:22:35+0200 — Advisor (Fable 5) reviewed: APPROVE-WITH-CHANGES. Four corrections folded into
  STATE + Design; NEXT ACTION revised to "verify 1a/1b empirically first". Still `todo`, unimplemented.
