---
trdd-id: 570f47ff-b15d-4fa6-a86a-911e735a1d50
title: Janitor wedged-session detector + multi-channel command-injection remediation
status: completed
created: 2026-05-28T18:59:02+0200
updated: 2026-05-30T22:40:41+0200
---

# TRDD-570f47ff — Janitor wedged-session detector + multi-channel command-injection remediation

**Filename:** `design/tasks/TRDD-20260528_185902+0200-570f47ff-wedged-session-remediation.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)

> Scope note: this is ONE cohesive system (detector → injection channels →
> remediation orchestration → heartbeat auto-pause → opt-in auto-clear). It is
> specified as a single phased TRDD rather than fragmented per-component TRDDs,
> because the pieces are tightly coupled and share one threat model and one
> test harness.

---

## 0. RESOLUTION (2026-05-30) — closed per R10: fixed upstream, injector deferred

This TRDD is **completed as a research conclusion, NOT as a built system** — the
correct engineering outcome the doc's own §9 R10 prescribed.

**Verified facts (2026-05-30):**
- Running Claude Code is **2.1.158** (`claude --version`), well past the R10
  gate of 2.1.154. All **three** upstream fixes to this exact thinking-block
  flood root cause (stale-thinking-signature stripping + retry safety-net in
  2.1.152; the two background-session/`/command` classifier fixes in 2.1.154)
  are present in the running harness.
- The **heartbeat-pause infrastructure (§6.D) already exists** independently:
  `scripts/dispatch.py::_phase_paused()` honors `.janitor/state/paused` at
  Phase 0 of every heartbeat (epoch expiry; 0 = indefinite); `/janitor-pause`
  writes it, `/janitor-resume` lifts it. So the "stop the amplifier" capability
  the incident actually needed is already shipped — a flood can be converted to
  a single failure today with `/janitor-pause`.

**Decision (faithful to R10 + the project's don't-over-engineer / no-speculation
rules):**
1. **The multi-channel keystroke injector (§6.B/§6.C/§6.E, phases P2–P5) is
   DEFERRED INDEFINITELY.** It is a sharp capability (writing keystrokes into
   another session's REPL) whose entire justification was a bug the harness now
   handles. Building it for a fixed bug is exactly the speculative
   over-engineering the directives forbid.
2. **No detector is built either.** R1 (where the `400` surfaces in the
   transcript jsonl) is unresolved and CANNOT be settled without reproducing a
   flood — which no longer reproduces on 2.1.158. Writing a detector against a
   guessed signature, with a test fixture I fabricated rather than captured from
   a real flood, would violate the "no fake/conceptual tests" rule. A detector
   we cannot validate against a real signal is worse than none.
3. **No upstream issue filed** (§15) — R10 already confirmed it is fixed; filing
   a fixed bug pollutes the tracker.
4. **If this regresses** on a future CC version: reopen by authoring a NEW TRDD,
   start at R6 (capture a REAL flood + its real jsonl signature), and build only
   §6.A (detector) + §6.D (reuse the existing `paused` sentinel) — the
   non-destructive half. The injector stays deferred until a concrete need
   survives the don't-over-engineer test.

Everything below is the original (pre-resolution) design, retained as the
historical record of the threat model and the options considered.

## 1. Problem statement & live incident

A sibling Claude Code session (publishing CPV `v2.108.0`) was observed **flooding
the Anthropic API with repeated `400` errors**:

```
API Error: 400 messages.51.content.9: `thinking` or `redacted_thinking` blocks
in the latest assistant message cannot be modified. These blocks must remain as
they were in the original response.
```

The session was wedged: each turn died instantly (`Cooked for 0s` / `Baked for
0s`) and the heartbeat kept re-poking it, producing a flood rather than a single
failure. The actual publish subprocess had already returned `exit code 0`, so
only the **foreground session's reporting was wedged**, not the work.

This is squarely in the janitor's mandate ("a Claude session is in a degraded
state → detect and recover"), yet:

1. The janitor had **no detector** for an API-error flood.
2. The janitor's own **5-minute heartbeat was the amplifier** turning one 400
   into a flood.
3. The janitor had **no remediation channel** into a wedged REPL's stdin.

This TRDD specifies the capability the janitor needs to detect, stop amplifying,
and (within hard limits) remediate this class of failure autonomously — with no
human present, and without depending on AI Maestro.

## 2. Root-cause analysis

- **API invariant:** when extended thinking is enabled AND the assistant is in a
  tool-use loop, the `thinking` / `redacted_thinking` blocks of the **latest
  assistant message** must be replayed **verbatim** on every follow-up request
  in that loop. They are immutable.
- **Trigger:** an out-of-band injection (a scheduled task / cron firing, and/or a
  background-command-completion notification) lands while that latest assistant
  message has live thinking blocks. The harness re-serializes the message with
  the thinking blocks altered / re-ordered / stripped → the API rejects it with
  the `400 … cannot be modified`.
- **Flood mechanism:** the corrupted message is now permanent in the in-memory
  history. Every subsequent poke (especially the 5-min heartbeat) starts a turn
  that re-sends the bad message → another `400`. Harness auto-retry on the error
  compounds it into a flood.
- **Responsibility split:** the *root* bug is upstream (Claude Code should not
  corrupt thinking blocks on a mid-turn injection, nor infinitely retry a
  client-side `400`). The janitor cannot fix the harness; it can **detect, stop
  amplifying, and inject a recovery command**. The janitor's injector is a
  workaround for a harness bug — file the upstream issue in parallel (§15).

## 3. Verified environment facts (captured this session, 2026-05-28)

- **Global daemon** runs out-of-band (PID-tracked, polls every ~10–60s, survives
  any wedged session). It is the correct actor for autonomous remediation.
- **Mixed terminal topology**: the agent fleet runs **inside tmux** (`alexandre`,
  `genny-bot`, `jack-bot`, `ecos-chief-of-staff-one` — claude `2.1.148` in panes,
  `pane_current_command` shows the version string). This janitor session and
  (almost certainly) the CPV session are **raw iTerm2 tabs** (`TERM_PROGRAM=iTerm.app`,
  not in the tmux pane list).
- **Three candidate injection channels**, in descending power:
  1. **AI Maestro API** — most powerful (target any agent by id, structured
     inject), but currently **unstable / under heavy development** and NOT always
     running. MUST be optional.
  2. **tmux `send-keys`** — deterministic, cross-platform (Linux/macOS/WSL),
     no focus-steal, read-back via `capture-pane -p`. Requires the session to be
     in a tmux pane.
  3. **iTerm2 AppleScript `write text`** — macOS-only, requires TCC Automation
     permission, no focus-steal (unlike System Events `keystroke`). Covers raw
     iTerm2 tabs.

## 4. Goals / non-goals

**Goals**
- G1. Detect a session in an API-error flood (the `400 … thinking … cannot be
  modified` signature, and ideally generic API-error storms) **out-of-band**.
- G2. **Stop the amplifier**: auto-pause that session's janitor heartbeat so it
  stops re-poking the wedged history.
- G3. **Inject a recovery command** into the wedged REPL via a **pluggable
  channel chain** (AI Maestro › tmux › iTerm2 › future), picking the most
  powerful *available* channel per session.
- G4. **Gentle escalation**: pause → `Esc` (non-destructive) → reassess →
  `/clear` (destructive, **opt-in only**) → resume.
- G5. **Self-sufficiency**: fully functional standalone; AI Maestro is detected
  and used if present, never required.
- G6. **Cross-platform** path for at least Linux + macOS (+ WSL via tmux).

**Non-goals**
- N1. Fixing the upstream Claude Code harness bug (file it; do not patch the CLI).
- N2. Preserving-and-resuming a thinking-corrupted conversation with context
  intact — **impossible** from outside the process (see §6.E caveat).
- N3. Stabilizing AI Maestro itself.
- N4. Driving non-Claude REPLs.

## 5. Architecture overview

```
        ┌──────────────────────── global daemon (out-of-band) ────────────────────────┐
        │                                                                              │
        │  A. wedged-session DETECTOR  ──flood?──►  C. remediation ORCHESTRATOR        │
        │     (transcript / pane scan)                  │                              │
        │                                               ├─ D. heartbeat AUTO-PAUSE     │
        │                                               │     (write pause-flag)       │
        │                                               │                              │
        │                                               ├─ B. injection CHANNEL CHAIN  │
        │                                               │     AiMaestro › tmux › iTerm2│
        │                                               │     • Esc  (always)          │
        │                                               │     • /clear (E: opt-in)     │
        │                                               │                              │
        │                                               └─ E. policy + GUARDRAILS      │
        └──────────────────────────────────────────────────────────────────────────────┘
                                  │ pause-flag honored by
                                  ▼
                       dispatcher-stub (per-session heartbeat)  ── no-ops while paused
```

## 6. Components

### 6.A — Wedged-session detector (daemon task)
- New daemon task `task_detect_wedged_sessions()` (sibling of
  `task_marketplace_refresh` / `task_version_update`), short cadence (e.g. 60s).
- For every live Claude session, obtain a **recent error signal** and decide
  "flooding" if ≥`N` matching errors occur within `M` seconds (defaults TBD by
  research, e.g. N=3, M=120s).
- **Detection source is the #1 research unknown** (§9.R1): the `400` may appear
  in the session transcript `~/.claude/projects/<proj>/<id>.jsonl`, OR only in
  the rendered UI. If transcript-visible → daemon reads files (clean). If
  UI-only → detection must come from `tmux capture-pane` / iTerm2 contents.
- Emits a `WedgedSession` record: `{session_id, project_dir, tty, terminal_kind,
  error_signature, count, window_s}`.

### 6.B — Pluggable injection-channel library (`scripts/lib/inject/`)
- Abstract `InjectionChannel`:
  - `name: str`
  - `is_available_for(session) -> bool` — runtime capability probe.
  - `inject(session, key_sequence) -> InjectResult`
  - `read_back(session) -> str | None` — to confirm flood / verify recovery.
- Concrete channels (priority high→low), each in its own module:
  1. `AiMaestroChannel` — available iff the AI Maestro API is reachable AND the
     session is a registered agent. Probe is cheap + cached; absent/unstable →
     `is_available_for` returns False silently.
  2. `TmuxChannel` — available iff the session maps to a tmux pane (match by
     cwd/tty — research R2). Inject via `tmux send-keys`; read via `capture-pane -p`.
  3. `ITerm2Channel` — available iff macOS + iTerm2 + session maps to an iTerm2
     session (match by tty/cwd — research R3). Inject via `osascript … write text`.
  4. (future) `GnomeTerminalChannel`, `KonsoleChannel`, `WindowsTerminalChannel`.
- `select_channel(session)` returns the first channel whose `is_available_for`
  is True; **None → cannot remediate → alert-only** (never crash).

### 6.C — Remediation orchestrator (daemon)
Ordered, idempotent, rate-limited:
1. Receive a `WedgedSession` from 6.A.
2. **D: pause the heartbeat** for that project (stop the amplifier) — always
   first, non-destructive.
3. **Select channel** (6.B). None → go to alert-only.
4. **Inject `Esc`** (and/or Ctrl-C) — non-destructive interrupt of the retry loop.
5. **Reassess** via `read_back` after a short settle. Recovered (prompt
   returned, no fresh 400s) → leave paused + alert "cleared the loop; verify".
6. Still wedged → **E: opt-in `/clear`**. If the opt-in flag is OFF → alert-only.
7. After a successful `/clear` (or human clear) → **remove the pause-flag**
   (resume) on a later cycle once the session is confirmed healthy.

### 6.D — Heartbeat auto-pause (pause-flag protocol)
- The orchestrator writes `<project>/.janitor/state/heartbeat-paused.flag`
  (with reason + timestamp + the session id that triggered it).
- The **dispatcher-stub** checks this flag at the very top of each fire and
  **no-ops** (emits nothing, does no injection-prone work) while present.
- A healthy-confirmation cycle removes the flag (auto-resume). Manual override:
  `/janitor-resume-heartbeat` (or delete the flag).
- This is independently useful even with NO injection channel available — it
  alone converts a flood into a single failure.

### 6.E — Opt-in auto-clear + guardrails
- **`/clear` is destructive** — it wipes the wedged session's context. Therefore
  auto-clear is gated behind an explicit opt-in plugin option (§7) and is the
  **last** step, only after `Esc` failed, only on a confirmed flood.
- **The honest ceiling:** even with the most powerful channel, the janitor
  CANNOT un-corrupt thinking blocks and resume with context intact. "Solve while
  away" realistically = *heartbeat paused + loop interrupted + (if opted-in)
  auto-cleared, losing that conversation + alert waiting*. This limit is
  channel-independent (N2).
- **Guardrails (mandatory):**
  - Inject only into a **positively-confirmed** flooding session — never a healthy one.
  - Inject only a **fixed safe vocabulary**: `Esc`, Ctrl-C, `/clear`. Never
    arbitrary or transcript-derived text (prevents injection-of-attacker-content).
  - **Rate-limit**: ≤1 remediation attempt per session per cooldown window.
  - **Target certainty**: if the pane/tab can't be identified unambiguously →
    **do nothing** (never guess-and-inject into the wrong session).
  - **Audit log** every injection: channel, target, key sequence, reason, result
    → `$MAIN_ROOT/reports/wedged-session-remediation/<ts>-<session>.md`.

## 7. Config / plugin options (all default to the SAFE setting)
- `CLAUDE_PLUGIN_OPTION_WEDGED_DETECT_ENABLED` (default `true`) — detection + pause + Esc + alert.
- `CLAUDE_PLUGIN_OPTION_WEDGED_AUTO_CLEAR` (default `false`) — allow the destructive `/clear` step.
- `CLAUDE_PLUGIN_OPTION_WEDGED_FLOOD_COUNT` (default TBD, e.g. `3`).
- `CLAUDE_PLUGIN_OPTION_WEDGED_FLOOD_WINDOW_S` (default TBD, e.g. `120`).
- `CLAUDE_PLUGIN_OPTION_WEDGED_COOLDOWN_S` (default e.g. `300`).
- `CLAUDE_PLUGIN_OPTION_WEDGED_CHANNELS` (default `auto` = AiMaestro,tmux,iterm2) — allow restricting/ordering.

## 8. Security & threat model
- **T1 — wrong-target injection**: a bug injects `/clear` into a healthy session
  → data loss. Mitigation: positive flood-confirmation + unambiguous target +
  rate-limit + audit log + dry-run mode in tests.
- **T2 — malicious transcript content** tricks the detector into injecting:
  mitigation: fixed key vocabulary only (never echo transcript text), and the
  detector matches a fixed error signature, not free text.
- **T3 — command injection via the key sequence** itself (shell-escaping in the
  tmux/osascript call): mitigation: pass fixed constant sequences, never string
  interpolation of session-derived data into the inject command.
- **T4 — TCC / permission escalation** (iTerm2 channel needs Automation
  permission): document the grant; fail closed if not granted.
- **T5 — AI Maestro channel auth**: probe must not leak tokens; treat the API as
  untrusted/unstable; never block on it.

## 9. HEAVY research plan (resolve before / during implementation)

Each item: the question, why it blocks, and how to investigate (real
experiments, no speculation). Findings get appended to this TRDD.

- **R1 (CRITICAL — gates 6.A) — Where does the `400` surface?**
  Reproduce a flood (R6) and inspect `~/.claude/projects/<proj>/<id>.jsonl` in
  real time: does the API error get written as an entry, with what shape/field?
  If yes → transcript-based detection. If no (UI-only) → must scrape via
  `tmux capture-pane` / iTerm2 contents. Decides the whole detector design.
- **R2 — tmux session↔pane mapping.** Determine the reliable key linking a
  flooding Claude session to its `session:win.pane`. Candidates: `pane_tty`,
  `pane_current_path` (cwd), pane title. Verify uniqueness when multiple panes
  share a cwd. Output: a deterministic resolver.
- **R3 — iTerm2 AppleScript surface.** Enumerate windows→tabs→sessions; read each
  session's `tty` and cwd; confirm `write text` delivers to a *non-frontmost*
  session without stealing focus; document the exact TCC Automation grant and
  the failure mode when it's not granted.
- **R4 — AI Maestro inject API.** Document the actual endpoint(s) to (a) probe
  availability/health, (b) enumerate agents, (c) inject a command; auth model;
  how to map a Claude session to an AI Maestro agent id. Define the cheap cached
  availability probe.
- **R5 — Does `Esc` break the loop? Does `/clear` resolve it?** Empirically: in a
  reproduced flood, inject `Esc` — does the retry loop stop? Then inject
  `/clear` — does a fresh turn succeed (history no longer contains the corrupted
  latest-assistant message)? Confirm `/compact` does NOT resolve it (it re-sends
  history). Pin the exact recovery recipe.
- **R6 — Minimal reproduction harness.** Build a deterministic repro of the
  thinking-block flood: a session with extended thinking on + a tool-use loop +
  a mid-turn cron/scheduled injection. This harness is reused by every test in
  §10. Document the exact ingredients that trigger it.
- **R7 — Mid-turn detection (prevention, not just cure).** Can the daemon /
  dispatcher tell a session is *currently mid-turn with thinking active* (from
  the transcript tail or pane state) so the heartbeat can **defer** rather than
  inject into the danger window? Quantify detection lag. If feasible, prevention
  beats remediation.
  - **SIGNAL FOUND (CC 2.1.145):** `Stop` and `SubagentStop` hook input now
    include `background_tasks` and `session_crons` fields → a hook CAN see
    whether subagents/crons are active. Plus `CLAUDE_CODE_SESSION_ID` is in the
    Bash subprocess env (2.1.132) and MCP subprocess env (2.1.154) → session-
    identity mapping for the detector no longer needs pane-scraping. Re-scope R7
    around these instead of transcript-tail heuristics.
- **R8 — Cross-platform channels.** Inject mechanisms for GNOME Terminal,
  Konsole, Windows Terminal (and whether tmux-under-each suffices, making the
  native channel unnecessary). Confirm tmux covers Linux + WSL.
- **R9 — Generic API-error storms.** Beyond the thinking-400: should the detector
  also catch rate-limit storms, 401/403 auth-failure loops, 5xx loops? Define the
  signature taxonomy and which warrant which remediation (rate-limit → defer to
  the rotator, not `/clear`).
- **R10 — Upstream status — LARGELY RESOLVED (do NOT file; re-test first).**
  Claude Code shipped THREE fixes to this exact root-cause class in the
  2.1.152→154 cluster (all dated ~2026-05-27/28):
  - 2.1.152: *"sessions getting stuck after a model or login switch left stale
    thinking-block signatures in history; now stripped proactively with a
    retry safety-net"*
  - 2.1.154: *"background-session classifier losing the user's goal when a
    scheduled `/command` fires"*
  - 2.1.154: *"background-agent completion notifications triggering premature
    'out of context' behavior on some 1M-context models"*
  **Action change:** before building ANY of §6's detect+remediate machinery,
  re-run the R6 repro on **CC ≥ 2.1.154**. If it no longer reproduces (likely),
  this TRDD collapses to: (a) keep the cheap heartbeat-defer prevention (R7), and
  (b) record the upstream fix as the resolution. The multi-channel injector
  (tmux/iTerm2/AiMaestro) is then **deferred indefinitely** as over-engineering
  for a bug the harness now handles. Do NOT file an upstream issue — it's fixed.

## 10. HEAVY testing plan (exhaustive, REAL — no mocks)

Per project rules: **no mocked behavior** — use real tmux servers, real
terminals, and the real repro harness (R6). iTerm2 / AI Maestro tests are
macOS-/service-bound and CANNOT run in headless CI → mark them slow 🐌 and
gate them behind availability probes (skip, never fail, when the surface is
absent). Every test function carries a one-line docstring; the runner prints a
**Unicode-bordered result table** (heavy header row, light data rows; `PASS`/
`FAIL`/`SKIP`/`ERROR` 6-char status column; 🐌 marks slow tests; trailing count
line).

### Test groups
1. **Detector (6.A)** — feed REAL transcript fixtures captured from the repro
   harness (R6) and from healthy sessions. Assert: flood signature fires at the
   threshold; **zero false positives** on healthy/normal-error sessions; window
   logic correct at boundaries (N-1 = no fire, N = fire).
2. **Channel availability probes (6.B)** — real tmux server up/down; real iTerm2
   present/absent; AI Maestro reachable/unreachable. Assert `is_available_for`
   is correct and **never throws** when a surface is missing.
3. **tmux injection (6.B.2)** — spawn a REAL tmux pane running a stub REPL,
   inject `Esc` / `/clear`, assert via `capture-pane` the keys landed and focus
   was not stolen. (CI-able on Linux + macOS.)
4. **iTerm2 injection (6.B.3)** 🐌 — macOS-local: open a REAL iTerm2 session,
   `write text`, assert delivery to a non-frontmost session, no focus-steal.
   Skip when not macOS / TCC not granted.
5. **AI Maestro injection (6.B.1)** 🐌 — only when the API is reachable; assert
   probe + inject; otherwise SKIP.
6. **Target resolution (R2/R3)** — multiple panes/tabs incl. shared-cwd
   collisions; assert correct target OR **safe no-op** on ambiguity (never wrong
   target).
7. **Heartbeat auto-pause (6.D)** — write the pause-flag, run a real dispatcher
   fire, assert it no-ops; remove flag, assert normal fire resumes.
8. **Orchestrator escalation (6.C)** — drive the full state machine against the
   repro harness: pause → Esc → reassess → (opt-in) /clear → resume. Assert
   ordering, idempotency, and rate-limit cooldown.
9. **Guardrails (6.E / §8)** — never inject into a healthy session; only fixed
   vocabulary; cooldown enforced; ambiguous target = no-op; audit-log written to
   the correct `reports/` path; shell-escaping safe (T3).
10. **Opt-in gate** — `WEDGED_AUTO_CLEAR=false` → never injects `/clear` (alert
    only); `true` → injects only as the last step.
11. **End-to-end gold test** 🐌 — reproduce a real flood in a real tmux pane, run
    the real daemon task, assert the session is recovered (or safely paused +
    alerted) with the heartbeat paused and an audit report on disk. This is the
    proof the system actually works.
12. **Cross-platform matrix (R8)** — tmux channel on Linux + macOS (+ WSL if
    available); native channels where feasible.

### Test hygiene (hard requirements)
- Every external resource (tmux server/pane, iTerm2 session, subprocess) opened
  by a test is **closed in `try/finally`**; the runner snapshots process/pane
  counts before & after and fails on any leak.
- Parallelize where independent; close in parallel.
- Runner exits 0 on all-pass, non-zero on any-fail (so CPV `publish.py::_gate_tests`
  can gate on it).

## 11. Phasing (≤5 files per phase; verify between phases)
- **P0 — Research spike** (R1, R5, R6): build the repro harness, settle the
  detection source, pin the recovery recipe. **Blocks everything.**
- **P1 — Detector (6.A) + heartbeat auto-pause (6.D)** + their tests. Ship this
  first: detection + pause + alert is independently valuable and non-destructive.
- **P2 — Injection-channel lib (6.B) skeleton + tmux channel** + tests.
- **P3 — iTerm2 channel + AI Maestro channel** (capability-gated) + tests.
- **P4 — Remediation orchestrator (6.C) + guardrails (6.E)** + escalation/guardrail
  tests + the E2E gold test.
- **P5 — Cross-platform channels (R8) + docs + plugin options** wiring.
- Commit per phase. **Do NOT push / publish** without explicit approval (consistent
  with the standing hold behind CPV #40).

## 12. Acceptance criteria
- AC1. A reproduced thinking-400 flood is detected within `M` seconds with zero
  false positives on healthy sessions.
- AC2. On detection, the offending session's heartbeat is auto-paused and stops
  re-poking (verified: no further heartbeat-driven 400s).
- AC3. With a channel available, `Esc` is injected and the retry loop stops; with
  `WEDGED_AUTO_CLEAR=true` and Esc insufficient, `/clear` recovers the session.
- AC4. With NO channel available, the system alerts and pauses — never crashes,
  never injects blindly.
- AC5. AI Maestro absent/unstable changes nothing — the chain falls through to
  tmux/iTerm2. The janitor works fully standalone.
- AC6. All guardrails hold under test (no wrong-target inject, fixed vocabulary,
  cooldown, audit log).
- AC7. Full test suite green; runner gate-compatible; zero leaked panes/processes.

## 13. Open questions / risks
- OQ1 (R1): transcript-visible vs UI-only error — biggest design fork.
- OQ2 (R7): is mid-turn prevention feasible, or is cure the only option?
- OQ3: does the harness auto-retry the 400, and can the janitor suppress that?
- OQ4: AI Maestro API shape is a moving target (heavy dev) — keep the channel
  thin + behind a probe so churn doesn't break the janitor.
- Risk: keystroke injection is a sharp capability; the guardrails + dry-run test
  mode are load-bearing, not optional.

## 14. Out of scope
- Patching the Claude Code harness (N1) — file upstream only (§15).
- Resume-with-context of a corrupted conversation (N2) — physically impossible
  from outside the process.
- Stabilizing AI Maestro (N3); driving non-Claude REPLs (N4).

## 15. Upstream filing (parallel track)
File a Claude Code issue: scheduled-task / background-completion injection during
an extended-thinking tool-use turn corrupts the latest assistant message's
thinking blocks → `400 … cannot be modified`, and the harness then auto-retries
the same corrupted request → flood. Request: (a) don't mutate committed thinking
blocks on mid-turn injection, (b) don't infinitely retry a client-side 400.
Link this TRDD's repro harness (R6) once built.
