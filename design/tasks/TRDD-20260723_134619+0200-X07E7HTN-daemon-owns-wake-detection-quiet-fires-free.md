---
trdd-id: X07E7HTN
title: Daemon owns rate-limit wake so the FAST polling window costs zero model turns
column: complete
created: 2026-07-23T13:46:19+0200
updated: 2026-07-23T15:37:08+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
approval-tier: 2
relevant-rules: [1]
task-type-detail: architectural change to the heartbeat cost model; standalone-only; survival-critical paths in scope; v1 scoped to the rate-limit polling window only
impacts: [heartbeat-cost-model, survival-resume, fleet-daemon]
implementation-commits: [3c18208]
release-via: publish
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-23

- **✅ SHIPPED (v1) + COMPLETE — committed `3c18208`, verified.** Approved by the USER
  ("do all the improvements") — solo project, so USER is the Tier-2 authority. Let the
  machine-wide OS-keepalive daemon own the **rate-limit wake** so the FAST `*/5` polling
  window a rate-limited session sits in costs ZERO model turns. v1 = rate-limit wake ONLY;
  the general-detector-roster relocation is a later TRDD. Gate green at commit: pyright
  0/0/0, ruff clean, full suite 13508 passed, `~/.claude` isolation verified. Actuation
  confirmed by direct read: `fleet_inject` "resume" = the `/janitor-resume` SLASH command
  (never the defanged bare marker), frozen pane → `esc_nudge` only, single-consumer
  `rate-limited.flag` prevents double-resume, and `dispatch.py` still emits the bare
  `[janitor-resume]` cron fallback. Issue #105 (no resume-after-clear under USER_PRESENT) folded.
- **SCOPE (v1, deliberately narrow — the review's §1/§4 recommendation):** ONLY the
  rate-limit polling window. This is the biggest sink: while `rate-limited.flag` is set,
  `heartbeat_cadence.Signals.active_waiting` is True → `raw_tier` returns `FAST` → the cron
  fires `*/5` (`heartbeat_cadence._DEFAULT_CRON[FAST]`), and across a multi-hour limit that
  is dozens of ~$0.76 quiet paid turns. v1 does NOT relocate the general detector roster,
  does NOT build a drift-prose channel, and does NOT touch post-compact / renew wake (those
  stay cron-owned). Broadening to the full detector roster is a later TRDD that inherits
  v1's lock + closure discipline.
- **Core defect:** a rate-limited session polls at `*/5`; each fire is a full model TURN
  that re-reads the whole transcript at the 0.1x cache-read rate (~$0.76 on a 510k session)
  just to answer "still limited? / cleared → resume". The daemon ALREADY frees the frozen
  pane for free (`task_session_liveness` → `frozen` → `fleet_recovery.action_for` →
  `esc_nudge`), but nothing yet drives the RESUME off the model turn, so the cron must keep
  polling FAST.
- **Target mechanism (two existing primitives, one new inject action):**
  1. Pane is `frozen` (rate-limited, wedged in Claude Code's retry-watchdog): the daemon's
     EXISTING `esc_nudge` (ESC-only, `fleet_inject.build_esc_plan`) breaks the retry-wait and
     returns the REPL to idle. Typing a COMMAND into a frozen pane is forbidden — it buffers
     on the retry-blocked input line and floods (the 2026-07-18 disaster, TRDD-P7WU40G9).
  2. Pane is NO LONGER `frozen` (ESC freed it, or it was never frozen) AND `rate-limited.flag`
     is still present AND a reachability gate passes: the daemon injects the `/janitor-resume`
     **SLASH COMMAND** (soft enqueue) via `fleet_inject.build_command_plan`. This is the
     fleet analogue of `resume_trigger.py`'s self-send; both type the SAME `/janitor-resume`
     command, NEVER the bare `[janitor-resume]` marker (a typed marker is untrusted content —
     `_RESERVED_MARKER_RE` / `_defang_foreign_markers` neutralize it).
- **NEXT ACTION:** obtain MANAGER approval (Tier 2 — reshapes the heartbeat cost model and
  touches survival-critical paths). On approval → `git mv` to `design/tasks/`, set
  `column: planned`, implement per "The fix", primary file `scripts/daemon.py` +
  `scripts/lib/fleet_inject.py`.
- **Load-bearing facts / gotchas (do NOT lose):**
  - **NEVER type a command into a `frozen` pane** (MF1). ESC-only until diagnosis flips off
    `frozen`. The `resume` inject is gated on `diagnosis != "frozen"`.
  - **NEVER inject the bare `[janitor-resume]` marker** (MF2). A marker is honored only as a
    bare line in the cron stub's OWN stdout; typed into a pane it is content and is defanged.
    The daemon types the `/janitor-resume` slash command. Routing through the command also
    makes the reachability requirement self-verifying: the injected command IS a model turn
    that only completes when the API is reachable.
  - **Single-writer lock (MF3).** Daemon and the fallback cron both touch per-project
    `.janitor/state`. v1's daemon path writes ONLY a wake-dedupe stamp, under a per-project
    `detector.lock` flock, and touches NO detector `last-run-*.ts` / seen-file. The lock is
    specified now so the later full-roster scope is already safe.
  - **Arm-cadence ⇄ injectability handshake (MF4).** A session picks its arm cadence BEFORE
    the daemon has scanned it. Default = assume UN-injectable → keep FAST. The cadence
    demotes off FAST for the rate-limit window ONLY once the daemon has written a per-project
    `daemon-wake-covered.ts` proving this pane is injectable AND actively woken. Un-injectable
    panes (plain / VS Code integrated / ssh — no resolvable `terminal`) keep FAST and the cron
    remains their only trigger.
  - **The cron stays armed at FULL survival cadence as a fail-open FALLBACK.** `_phase_rate_limit_recovery`
    still emits the bare `[janitor-resume]` marker. The flag is single-consumer (whoever
    unlinks `rate-limited.flag` first wins; the other path no-ops) → the daemon inject and the
    cron fire can never double-resume.
  - **Standalone-only.** The wake loop gates on `backend(env)=="standalone"` and never injects
    into a `server_owned` instance (`harness_backend.instance_is_server_owned`, TRDD-X92VBFNF).
    In #J harness the server owns continuity.
  - **Closure must not balloon (MF5 / scoping).** v1's inject action reuses modules already in
    `keepalive_stage.daemon_closure` (fleet_inject, fleet_scan, session_liveness,
    fleet_recovery, global_state). It MUST NOT import the detector roster or any `*_patterns.py`
    into the daemon closure — a staging test asserts closure count stays bounded and contains
    ZERO `detectors/` or `*_patterns.py` files.
- **SUPERSEDED — do NOT carry forward:** the first revision's full-detector-roster relocation
  (old "The fix" items 3/6/8/9 and the general drift-prose wake). v1 is rate-limit-only; the
  broad relocation is a follow-up TRDD, not this one.
- **Durable artifacts to read before acting:** the review synthesis
  `reports/janitor-improvements/20260723_135211+0200-sequenced-implementation-plan.md` §3
  (D1 must-fixes) + §1/§4 (scoping); `design/ARCHITECTURE.md` §3/§7; CLAUDE.md "Control flow"
  + "Two runtime backends"; `~/.claude/rules/janitor-heartbeat-protocol.md` (marker contract).

## The problem

The janitor heartbeat's cost is the **model turn itself**, not the detector work inside it.
The single most expensive turn class is the **rate-limit polling window**. When a turn dies
on a usage 429, `on-stop-failure` writes `rate-limited.flag` (+ `rate-limited-since.ts`).
From then on `heartbeat_cadence.Signals.active_waiting` is True, so
`heartbeat_cadence.raw_tier` returns `FAST` and the cron fires `*/5`
(`_DEFAULT_CRON[FAST] = "*/5 * * * *"`). Each of those fires is a full Claude turn re-reading
the whole append-only transcript at the 0.1x cache-read rate — measured ~$0.76 on a
~510k-context session. Across a multi-hour rate limit that is dozens of paid turns whose only
job is "am I still limited? cleared → `[janitor-resume]`". The TTL cadence tiers
(TRDD-0QQX9H0G) only change how OFTEN that turn is paid; a quiet fire can never be free while
the cron IS the trigger.

The daemon already does half the job for free. `daemon.py::task_session_liveness` runs every
120s with NO model attached: `fleet_scan.gather_fleet` enumerates every live claude `Instance`
+ its resolved terminal-injection identity + `diagnosis`; a rate-limited pane is diagnosed
`frozen`; `fleet_recovery.action_for("frozen", …)` returns `esc_nudge`; and `fleet_inject.fire`
sends the ESC that breaks the retry-watchdog wait — zero model cost. What is missing is the
second half: after ESC frees the pane, the RESUME still rides a paid cron turn instead of a
free daemon inject, so the cron must keep polling FAST.

## The fix (this TRDD's v1 scope — rate-limit wake only)

Add the resume half of the rate-limit recovery to the daemon so an injectable, rate-limited
session's cadence can leave FAST, and keep the cron as the fail-open fallback. Concrete files
+ functions, grounded in the current code:

### 1. `scripts/lib/fleet_inject.py` — the one NEW actuation (PRIMARY change)
Add a command-typing action `resume`:
- `_ACTION_COMMAND` (currently `{rearm, reload, update}`, L63) gains `"resume": "/janitor-resume"`.
  `action_to_command("resume")` then returns `/janitor-resume`; `build_injection` /
  `build_command_plan` type it soft-enqueue (`esc_first=False`) into the resolved `terminal`.
- This is the fleet analogue of `resume_trigger.py` (the `/janitor-resume` self-trigger) —
  same slash command, different target (a scanned `Instance`'s pane, not `$ITERM_SESSION_ID`).
- It NEVER types the bare `[janitor-resume]` marker. (Confirmed sink: `dispatch._RESERVED_MARKER_RE`
  L451 + `_defang_foreign_markers` L461 defang a `[janitor-resume]` marker in any typed/detector
  content, so a typed marker is inert by design — a slash command is the only working channel.)

### 2. `scripts/daemon.py` — extend the existing liveness beat (no new detached fan-out)
Rather than a new detector-running task, EXTEND the free `task_session_liveness` decision with
the resume step (it already scans the fleet + injects ESC for `frozen`). For each `Instance`:
- If `diagnosis == "frozen"` → keep the EXISTING `esc_nudge` (unchanged). Never type a command.
- Else if `rate-limited.flag` is present in that project's `.janitor/state` AND the reachability
  gate passes AND this `(project, "resume")` wake was not already delivered this window
  (`global_state` wake-dedupe, below) → inject the `resume` action (`/janitor-resume`) via
  `fleet_inject.build_injection` / `fire`, and stamp `daemon-wake-covered.ts` for the arm
  handshake (item 5).
- All of this stays STRICTLY AFTER `main()`'s top-of-loop guards (kill-switch, `server_is_alive`,
  maintenance, global-pause) and behind `backend(env)=="standalone"` +
  `not instance_is_server_owned(...)` (TRDD-X92VBFNF hands-off).
- Reachability gate (belt-and-suspenders; MF2 makes it non-load-bearing): only inject when the
  pane is no longer `frozen`; optionally confirm the API window via the rotator's read-only
  usage probe (`rotator_usage.accounts_usage` — already imported by the daemon), fail-OPEN
  (inject anyway) so a probe outage never strands a resume. A wasted inject is one soft-enqueued
  command that re-sets the flag, NOT a flood — because it is only ever sent to a NON-frozen pane.

### 3. `scripts/lib/global_state.py` — per-project resume wake dedupe
Add wake state analogous to `record_fleet_injection` / `fleet_injections_seen` /
`clear_fleet_injections` (already the model for fleet-stop de-dupe): a `(project, reason="resume")`
key so the daemon injects `/janitor-resume` ONCE per rate-limit window, not on every 120s scan.
The key MUST clear when `rate-limited.flag` is cleared (a NEW limit is a NEW window, so a
legitimately-repeated resume is not swallowed). This dedupe write is a per-project state mutation
and so takes the `detector.lock` (item 4).

### 4. Per-project detector lock — single-writer discipline (MF3)
Introduce `<project>/.janitor/state/detector.lock` (a flock, mirroring the daemon singleton /
marketplace-lock pattern in `global_state`). ANY per-project `.janitor/state` mutation that the
cron and the daemon could both perform takes this lock non-blocking, skip-if-held. In v1 the
daemon writes ONLY the wake-dedupe stamp + `daemon-wake-covered.ts` under this lock, and reads
`rate-limited.flag`; it runs NO detector and touches NO `last-run-*.ts` / seen-file, so no
seen-file can be corrupted. The lock is specified now purely so the future full-roster scope
(daemon running detectors) is single-writer-safe from day one and never races the fallback cron.

### 5. Arm-cadence ⇄ daemon-injectability handshake (MF4)
`heartbeat_cadence` today returns `FAST` whenever `active_waiting` (which includes rate-limited).
Change the RATE-LIMIT branch of the cadence decision so it may demote below FAST ONLY when the
daemon has proven coverage:
- The daemon writes `<project>/.janitor/state/daemon-wake-covered.ts` each time it injects a
  resume into THIS pane (proving the pane is injectable AND being woken).
- `dispatch`'s cadence phase reads a fresh `daemon-wake-covered.ts` (younger than N× the
  liveness interval); when present it may run the rate-limit window at the normal survival floor
  instead of FAST. When ABSENT (never scanned, or the daemon found the pane un-injectable / off /
  #J harness) it keeps FAST — the safe default. So a session that arms slow is never
  under-covered: absence of proof ⇒ FAST ⇒ the cron is the trigger. `arm_prepare.resolve_cron` /
  the `[janitor-renew]` re-arm handshake (`should_emit_renew`, `tier_to_cron`) carry the
  demotion; `skills/janitor-arm/SKILL.md`'s baked prompt is unchanged (still full survival
  fallback), so no re-arm rollout churn.

### 6. `scripts/dispatch.py` — the cron stays the fail-open FALLBACK (bare-marker survival)
NO removal of survival phases. `_phase_rate_limit_recovery` (L840) keeps emitting the bare
`[janitor-resume]` marker and clearing the flag. The flag is single-consumer: whoever unlinks
`rate-limited.flag` first wins; the daemon's inject and a cron fire cannot both resume (the
second finds no flag and no-ops). `_defang_foreign_markers` / `_stamp_resume` semantics are
untouched. This is the unifying invariant's **bare-marker fallback**: even if the daemon path is
off, unavailable, or the pane un-injectable, the cron still resumes exactly as today.

### 7. OS-keepalive staging — closure must not balloon (MF5 / scoping)
`launchd_keepalive.opted_in()` (`CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE`) remains the fail-open
master switch: with the OS keepalive off/unavailable the daemon path is inert and the cron is the
trigger. v1's resume inject reuses ONLY modules already in `keepalive_stage.daemon_closure`
(fleet_inject, fleet_scan, session_liveness, fleet_recovery, global_state — verified: current
closure = 37 files, 0 detector/pattern files). A staging test (item V below) asserts the closure
stays bounded and imports NO `detectors/` or `*_patterns.py`, so the L0 daemon never crash-loops
on a bloated / torn stage precisely in the all-sessions-down scenario.

### New env knob (fail-open, default preserves current behavior)
`CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED` — master opt-in for the daemon-owned
rate-limit resume. Default must preserve today's cron-owned FAST-poll behavior until proven; when
off/unavailable the cron heartbeat is the only trigger. Reuses existing
`CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE`, `..._SESSION_LIVENESS_ENABLED`,
`..._FLEET_RECOVERY_ENABLED`, `..._DAEMON_SESSION_LIVENESS_INTERVAL` (→ wake latency),
`..._RATE_LIMIT_FLAG_MAX_AGE_HOURS`, the `heartbeat_cadence` tier knobs, `USER_PRESENT_IDLE_S` /
`user_intent.hid_idle_seconds` (typing gate — never inject into a pane the user is at), and
`JANITOR_AIMAESTRO_SERVER_CHORES` / `_STATE` (standalone-vs-harness gate).

## Must-fix resolution (review synthesis §3, D1)

| MF | Requirement | How v1 resolves it |
|---|---|---|
| MF1 | Reconcile with `esc_nudge` — never type a command into a rate-limited pane | The `resume` inject is gated on `diagnosis != "frozen"`; a `frozen` pane gets ONLY `esc_nudge` (ESC-only, `build_esc_plan`), exactly as `fleet_recovery.action_for` already prescribes. Item 2. |
| MF2 | Correct actuation primitive — inject the `/janitor-resume` slash command, not the bare marker | New `resume` action → `/janitor-resume` in `fleet_inject._ACTION_COMMAND`; the bare `[janitor-resume]` marker is provably inert when typed (`_RESERVED_MARKER_RE`/`_defang_foreign_markers`). The command turn is self-verifying for reachability. Items 1, 2. |
| MF3 | Single-writer detector state | Per-project `detector.lock` flock; v1 daemon writes only wake-dedupe + coverage stamps under it, runs NO detector, touches NO seen-file. Item 4. |
| MF4 | Demotion-vs-latency for un-injectable terminals | Arm-cadence ⇄ injectability handshake via `daemon-wake-covered.ts`; default assume un-injectable → FAST; demote only on fresh proof of coverage; un-injectable panes keep FAST + cron. Item 5. |
| MF5 | How non-marker findings reach the model | v1 RESTRICTS the daemon path to the survival slash-command wake (`/janitor-resume`) only — no arbitrary drift-prose channel is built or used. Scope + item 7. |

## Verification

- **Actuation (MF1/MF2):**
  - `tests/test_fleet_inject.py` — `action_to_command("resume") == "/janitor-resume"`;
    `build_injection` for `resume` types the slash command (soft, `esc_first=False`) and NEVER
    the bare `[janitor-resume]` marker; a `frozen` pane routes to `build_esc_plan` (ESC-only,
    no command).
  - A defang regression: assert `dispatch._defang_foreign_markers` neutralizes a typed
    `[janitor-resume]` so the "type the command, not the marker" rule is enforced, not merely
    documented.
- **Single-writer (MF3):** `tests/test_daemon.py` / a new `test_detector_lock` — the daemon's
  wake-dedupe + coverage writes take `detector.lock`; a held lock makes the daemon skip (no
  double-write); the daemon touches no `last-run-*.ts` / seen-file in v1.
- **Handshake (MF4):** `tests/test_heartbeat_cadence.py` / `tests/test_dispatch_cadence.py` —
  a rate-limited session with a FRESH `daemon-wake-covered.ts` may demote below FAST; with the
  stamp ABSENT or STALE it stays FAST; an un-injectable pane never demotes.
- **Guard ordering / gating:** `tests/test_daemon.py` — the resume inject is reached only AFTER
  kill-switch / server-alive / maintenance / global-pause guards, only for
  `backend=="standalone"`, and NEVER for a `server_owned` instance
  (`instance_is_server_owned`); `tests/test_fleet_scan.py` covers `gather_fleet` /
  `diagnose_root` (`frozen`) / stale-rate-limit sweep.
- **Closure does not balloon (MF5 / scoping — REQUIRED test):** `tests/test_keepalive_stage.py`
  — `keepalive_stage.daemon_closure(scripts)` returns a bounded set (assert a small cap, e.g.
  ≤ ~50) AND contains ZERO paths under `detectors/` and ZERO `*_patterns.py`. This FAILS the
  build if the wake work ever imports a detector or pattern lib into the L0 daemon closure.
- **Survival invariant — resume is NEVER lost, NEVER doubled (the unifying D1/D2/D5 gate):**
  - *Bare-marker fallback:* `tests/test_dispatch_phases.py` — with the daemon path OFF/absent,
    `_phase_rate_limit_recovery` still emits the bare `[janitor-resume]` and clears the flag.
  - *Combined resume + action (REQUIRED):* a single test where a session is BOTH rate-limited
    AND the daemon wake path is active — assert EXACTLY ONE resume reaches the model (single-
    consumer flag: daemon inject OR cron fire, never both), and it is NEVER lost. This is the
    combined resume+action test §4 mandates for every dispatch-touching change.
  - *Un-injectable / #J:* assert the daemon DECLINES the resume inject (un-injectable terminal
    or `backend != standalone`) and the cron remains the armed trigger — no silent lost resume.
- **Latency proof ("unchanged or better"):** `tests/test_daemon_session_liveness.py` — the
  daemon-injected resume lands within one liveness interval (120s default) of the pane leaving
  `frozen`, asserted ≤ the FAST cron's own next-fire interval for the same session, so the
  demotion never worsens time-to-resume.

## Interdependencies

- **Ordering:** D4 (harness discriminator) → **D1 (this TRDD)** → D2 (re-baseline) → D5
  (serialization). D2 and D5 both declare they must land AFTER D1's settled
  `_resolve_heartbeat_mode` / wake contract. v1's narrow scope keeps the `dispatch.py::main()`
  edit small (cadence-phase demotion read + the unchanged fallback phases), reducing the 3-way
  `main()` contention the synthesis §1 flags.
- **Shared actuation (D1/D5):** `fleet_inject.build_command_plan` / `fire` + `terminal_trigger`
  (`esc_first` soft/hard) is the single keystroke substrate. v1 sets the contract: survival
  wakes are SOFT-enqueue slash commands, gated by `user_intent.hid_idle_seconds` (never inject
  into a pane the user is at). D5's `/compact` inject inherits it.
- **Shared discriminator (all four):** the wake gate keys on `harness_backend.backend` /
  `instance_is_server_owned` — D4's exact predicate; do not fork a second copy.
- **Deferred to a follow-up TRDD:** relocating the GENERAL detector roster off the cron turn
  (the first revision's items 3/6/8/9). That inherits v1's `detector.lock` + closure test but is
  out of scope here.

## Approval log

- 2026-07-23T15:37:08+0200 — APPROVED by USER (tier 2). Solo project → the human owner is the
  Tier-2 authority; the standing directive "do all the improvements … production quality" covers
  this. v1 (rate-limit wake) implemented in `3c18208` and self-verified (pyright 0/ruff/13508
  suite pass/isolation). Promoted `proposal → complete`, `git mv` proposals/ → tasks/.

## Notes and lessons learned

(none yet)
