---
trdd-id: WKTD5JTC
title: Daemon detects the CC 429-retry-watchdog wedge and injects ESC to break it
column: complete
created: 2026-07-24T13:39:02+0200
updated: 2026-08-18T20:55:00+0200
implementation-commits: [3517836b]
current-owner: main
task-type: feature
scope: project
approval-tier: 0
relevant-rules: []
external-refs: [dccb0b8a, 324223a6, 32acd15f]
---

# Daemon detects the CC 429-retry-watchdog wedge and injects ESC to break it

## ⏵ 2026-08-15 (evening) — THE DARK RECEIVER IS NOW LIVE. The ai-maestro server session reports `AIM_FLEET_MODEL_FALLBACK=1` applied and verified on the live pm2 process (their commit 56047fa5; card ai-maestro TRDD-DPPYVLVH proposal→dev). The USER approved it FIRST-HAND in that session — not through this session's relay, which they correctly refused to treat as approval. So the `server_owned` exclusion no longer hands off to a backend that ships dark, and the ATOM-4GQU-0C9J failure shape recorded in the field observation below is closed ON THE HUB SIDE. Their FIRST switch stays human-watched (the watchdog must log `model-fallback SWITCHED … confirmed=true` AND the pane statusline must flip Fable→Opus); as of tonight that is still PENDING a live Fable agent, because their fleet is hibernated (`could not read 10 pane(s)` — only 3 tmux sessions, none an agent), and they are explicitly NOT recording it verified until both signals are observed. They have also mirrored the janitor's scoped-window rotation and the TRUE-ERROR switch ordering server-side (their TRDD-IZ6KU37Y), reading our shipped implementation read-only. **Phase 1's standalone (#N) acceptance evidence remains what THIS card waits on** — the hub's arming does not satisfy it.

## ⏵ 2026-08-15 — FIELD OBSERVATION (Fable-wall continuity failure): Phase 1 did not and COULD not act — every hung agent was `server_owned`, the exclusion working as designed. The ai-maestro server's own leg (its #J backend) ships DARK behind `AIM_FLEET_MODEL_FALLBACK=1` pending the USER's arm ruling (ai-maestro TRDD-DPPYVLVH), so the handoff landed on a dark receiver — the ATOM-4GQU-0C9J shape ("a claimed chore transfers the ACT but goes dark"). Escalated to the hub session + USER 2026-08-15; the janitor-side rotation half gained the scoped trigger the same day (`f185e521`, QE390SJA). Phase 1's standalone (#N) acceptance evidence is still what this card waits on.

## ⏵ 2026-08-13 — PHASE 1 SHIPPED (`3517836b`). Column `todo → testing`.

Implemented across `session_liveness.py` / `fleet_recovery.py` / `fleet_scan.py` / `daemon.py`
with 24 new tests. Full suite 15024 passed / 1 skipped; ruff clean. All six guards were proven
by BREAKING each and watching a named test go red — the mapping is in the commit body, and
each has a test named for the property rather than for the function.

**Verification item 3 below is now WRONG AS WRITTEN and must not be run as stated.** It says
*"the daemon breaks the wedge with ESC; `on-stop-failure` then writes `rate-limited.flag`"* —
measured today, `on-stop-failure` does NOT fire on an ESC-cancel (that is finding 1b). The
**daemon** writes the flag itself, before the ESC. Corrected item 3:

> End-to-end on a real wedge: the daemon writes `rate-limited.flag` and injects exactly one
> ESC; the turn ends via plain `Stop`; the next heartbeat sees the flag and emits
> `[janitor-resume]`. Assert the flag is written by the DAEMON (its own log line), not by the
> stop hook — asserting only "the flag exists" would pass even if the ordering were wrong.

**What actually remains, stated honestly:** one live observation of the actuation on a real
wedge. That is a genuinely different kind of gap from the 1a/1b questions, which were about
CC's behaviour and were answerable from accumulated logs — this one is about whether OUR ESC
reaches OUR pane, and no historical record contains it because the code did not exist until
today. Do not re-run the decomposition trick here expecting the same result.

The unit layer already covers everything a fake fleet can show (seeded panes, cooldowns,
precedence, the automation-blocked decline), so the remaining risk is exactly the seam the
tests cannot cross: osascript/tmux actually delivering the keystroke to a wedged pane.

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
## ⏵ 2026-08-13 — 1a AND 1b ARE ANSWERED. No real wedge was needed; the evidence was already on disk.

**The NEXT ACTION below said "verify on a REAL wedge", which reads as *wait for an event* and is why
this card sat 20 days untouched. It was decomposable** (the `acceptance-criteria-expire` lesson
`^decompose-a-blocked-manual-confirmation`): both questions are answerable from the transcripts and
the janitor's own `stop-failure.log`, which have been accumulating the whole time.

**Corpus:** 835 structural `isApiErrorMessage` records across this project's transcripts; 2139
StopFailure fires in `.janitor/logs/stop-failure.log` spanning 85.6 days (2026-04-23 → 2026-07-17);
53 `Request interrupted` (ESC) records inside that same window.

### ✔ (1a) ANSWERED — **NO**. CC appends NOTHING during the retry loop, so `transcript_stale` DOES trip.

The advisor's feared branch — *"if YES, the whole flag-independent detection is dead"* — **does not
apply**. The design's transcript-stale gate stands as written. Two INDEPENDENT proofs:

1. **CC's system-record vocabulary contains no retry subtype.** The only subtypes emitted are
   `stop_hook_summary`, `turn_duration`, `scheduled_task_fire`, `away_summary`, `compact_boundary`,
   `local_command`. There is no per-attempt record type at all. (The `/attempt N\/M/` matches that
   *do* exist live in `attachment` / `last-prompt` / `queue-operation` — echoes of this very TRDD's
   own prose, which is exactly the self-trigger hazard this card already warns about. A naive
   whole-file grep returns 4843 files and is worthless here; key on the STRUCTURAL field.)
2. **Every API-error record coincides with a turn END.** 832/832 (**100%**) have a StopFailure fire
   within 90s. A record written *mid*-retry would have no such fire. Zero do. Independently, no two
   API-error records are ever adjacent — every consecutive pair is ≥3 lines apart and always has a
   `user(HEARTBEAT)` between them, i.e. each is a separate cron-fired turn, never a burst inside one.

### ✔ (1b) ANSWERED — **plain `Stop`, NO flag.** The daemon MUST write `rate-limited.flag` itself.

The advisor's feared branch here **DOES apply**, so the fallback is mandatory, not optional:

| event in the shared window | n | StopFailure fire within ±90s |
|---|---|---|
| API-error record | 832 | **832 (100%)** |
| ESC / `Request interrupted` | 53 | **1 (2%)** |

The lone match is **below the chance rate**: 2139 fires over 85.6 days give a 5.1% probability that
any random ±90s window contains one, i.e. ~2.7 coincidental matches expected among 53 — we observed
1, and it has no API-error record beside it to explain it. So ESC-cancel does not fire StopFailure.

**Consequence for §3:** the ESC alone does NOT start the resume chain. The daemon writes
`rate-limited.flag` **before** injecting (precedent: `fleet_scan.sweep_stale_rate_limit` already
owns that flag's lifecycle). Without this the wedge breaks and the session then just sits idle —
strictly worse than today, because the wedge at least made the stall visible.

**The hook cannot help here:** `on-stop-failure.py` receives no distinguishing payload — it fires
and writes unconditionally. The Stop-vs-StopFailure choice is entirely CC's, so it can only be
measured from outside, as above.

### Remaining NEXT ACTION — implement Phase 1, with 1b's fallback wired in

Both empirical gates are green. Implement the corrected Phase 1 per Design §1-§3 + the four advisor
corrections, with the flag-before-ESC ordering now REQUIRED rather than conditional. Do NOT
implement on a rate-limited window.

- **SUPERSEDED — do NOT carry forward:** the "verify 1a/1b on a REAL wedge first" gate below, and
  the §3 note *"'everything downstream already works' is CONDITIONAL on §1b — verify first"*. It is
  no longer conditional: §1b is answered and the answer is the fallback branch.

---

- **NEXT ACTION (SUPERSEDED 2026-08-13 — see the block above; kept for provenance):** do NOT write code
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
- 2026-08-18T20:55:00+0200 — CLOSED (`testing → complete`) by janitor-main-session under the
  USER's explicit delegation of open decisions this session, on LIVE testing evidence measured
  first-hand today: (1) implementation verified in the tree — `fleet_recovery.injection_for`
  returns `esc_nudge` UNCONDITIONALLY for `retry_wedged` (advisor #1), and `daemon.py:1622-1630`
  writes `rate-limited.flag` BEFORE the ESC with the §1b measurement quoted in-code, exactly the
  mandatory fallback this card derived (832/832 vs 1/53); (2) the daemon has broken SIX genuine
  retry-watchdog wedges on this host — 2026-08-16 23:23 (attempt=2) and five today (18:54 ×2,
  19:07, 19:36, 19:53), every one logged `FIRED`, none escalated to crash-loop, and the
  recovered sessions are alive in the live agent roster. The "verify on a REAL wedge" gate is
  satisfied by real wedges, repeatedly. Harness-side (§8 server port) remains ai-maestro's own
  card per ARCHITECTURE §8.4 — not this card's scope.
