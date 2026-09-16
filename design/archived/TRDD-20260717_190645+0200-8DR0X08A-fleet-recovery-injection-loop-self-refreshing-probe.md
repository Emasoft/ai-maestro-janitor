---
trdd-id: 8DR0X08A
title: Fleet-recovery injection loop — the injected keystroke refreshes its own liveness probe, so wedged sessions get typed at forever
column: published
created: 2026-07-17T19:06:45+0200
updated: 2026-07-17T20:05:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
related-trdd: [324223A6, 56D24C02, 4649ZLE0, ME8V2YJF, 0QQX9H0G]
implementation-commits: [db9c2f0, 7f279b2]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER REPORT (2026-07-17, verbatim):** *"the janitor continue printing multiple time
commands like /janitor-resume /janitor-arm /janitor-reload-plugins etc."* — the owner is
watching their panes fill up with janitor-typed slash-commands, repeatedly, all day.

**ROOT-CAUSED same evening (evidence in `global-state/daemon.log`, `recovery-audit.ndjson`,
and the target sessions' transcripts). Three interacting defects in the `session-liveness`
beat (TRDD-324223a6 A2):**

1. **The injection contaminates its own probe.** `fleet_scan.transcript_age` is the
   mtime of the project's newest `*.jsonl`. When the daemon types `/janitor-arm` into a
   pane, Claude Code appends a `{"type":"queue-operation","operation":"enqueue",...}`
   line to that transcript — mtime refreshes ⇒ the NEXT liveness beat diagnoses
   `healthy` ⇒ the daemon CLEARS the per-instance `attempts` counter (daemon.py, the
   "healthy → clear stale attempt counter" branch). ~15 min later the transcript is
   stale again ⇒ `cron_dead`, `attempt=0` ⇒ re-inject. **The MAX_ATTEMPTS=4 crash-loop
   guard can NEVER trip** — the actuator resets its own failure counter. Evidence: 40+
   `FIRED rearm` events on 2026-07-17 alone, every one `attempt=0`;
   perfect-skill-suggester and CLAUDE-PLUGIN-VALIDATION hit every ~16 min
   (COOLDOWN_S=900) for hours.

2. **`FIRED` measures keystroke DELIVERY, not command EXECUTION.** The wedged targets
   are mid-turn (permission dialog / awaiting input), so the typed command is queued,
   never run. Their transcripts' LAST LINES are literal enqueue records:
   `content":"/janitor-arm"` (PSS 16:55Z), `content":"/reload-plugins --force"` (CPV
   16:59Z). Each cooldown re-types the command ⇒ the queue GROWS — exactly the
   "printing multiple time commands" the owner sees.

3. **A session wedged awaiting human input needs a HUMAN, not keystrokes.** The right
   escalation for an enqueue-but-never-execute target is the TRDD-4649ZLE0 notify
   channel (name the project, ask the human to open it). Today the beat just types
   forever. Additionally the gentle rungs have no user-presence backoff (fleet-stop's
   `is_injectable` gates on user activity; the recovery path does not).

**FIX (three parts, all in the daemon/lib layer — no new state files beyond the existing
per-instance recovery-state):**

- **F1 — outcome-verified attempts.** After an injection, record `(injected_ts,
  injected_command)` in the instance's recovery state. On the next beat, "healthy" only
  clears `attempts` if the transcript advanced with a SUBSTANTIVE line (anything other
  than trailing `queue-operation` records) after `injected_ts` — i.e. compute a
  substantive-transcript-age that skips trailing enqueue lines (cheap: read the tail,
  walk back over `"type":"queue-operation"` lines). Otherwise the beat counts a FAILED
  attempt (attempts+1, no re-injection of the same rung), so the 4-attempt budget walks
  to the crash-loop human alert as designed.
- **F2 — wedged-target detection short-circuit.** If the target transcript's tail shows
  our previously-injected command still ENQUEUED (or ≥N trailing queue-operation
  lines), classify the instance `wedged_awaiting_input`: never type again, push ONE
  `notify.py` alert (sev HIGH, code `FLEET-WEDGED`, naming the project), stamp, done.
  Dedupe via notify's content-hash gates.
- **F3 — substantive age for the diagnosis itself.** `transcript_age` (or a sibling used
  by `diagnose_root`) should ignore a mtime refresh whose only new content is
  queue-operation lines, so the healthy/stale oscillation stops at the source.

**Immediate mitigation (until the fix ships):** `CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED=0`
(detection continues, injection becomes dry-run-log-only) or
`CLAUDE_PLUGIN_OPTION_SESSION_LIVENESS_ENABLED=0` (beat fully off). Requires a daemon
restart to take effect (the daemon reads env at spawn).

**Verification criteria:** a synthetic wedged target (transcript whose tail is enqueue
lines) must (a) never be re-injected after the first attempt, (b) produce exactly one
notify push, (c) walk its attempts budget without ever resetting on enqueue-only
freshness; a genuinely-recovered target (substantive lines after injection) must still
clear attempts. Regression: the 2026-07-17 daemon.log pattern (repeated `attempt=0` on
the same root) becomes structurally impossible.

**IMPLEMENTED (2026-07-17 evening, commit `db9c2f0` — same session as the report; the
owner was AFK on the mitigation-vs-fix question, and the env-knob mitigation was found
UNRELIABLE anyway: the L0 launchd keepalive respawns the daemon with launchd's own env,
so a knob set in a session/shell loses the respawn race — shipping the fixed daemon IS
the mitigation):**

- **F1/F3** — `fleet_scan.transcript_activity()` + pure `substantive_age_from_tail()`:
  liveness is now the age of the newest SUBSTANTIVE transcript line (queue-operation
  bookkeeping excluded; all-enqueue tails use their OLDEST timestamp — conservative);
  `transcript_age()` is a thin wrapper so every caller inherits it. The injection can
  no longer refresh its own probe.
- **F2** — daemon wedged short-circuit: `Instance.trailing_enqueues ≥ 1` on a SOFT
  rung ⇒ no injection, one `declined_wedged` audit (sig-deduped), attempts+1 (the
  budget walks to crash_loop), one `notify.push(code="FLEET-WEDGED")` naming the
  project. ESC-first rungs (frozen) exempt — the ESC is the unwedge, same policy as
  `_fire_fleet_stop`.
- **F4** (added during implementation) — `stale_threshold_for(armed_cron)`:
  `diagnose_root` scales the staleness window to 3× the target's ARMED cadence
  (`armed-cadence.cron`), floored at the */5 default — so sessions the dynamic
  cadence (TRDD-0QQX9H0G) legitimately demoted to */15–*/30 are no longer flagged
  cron_dead between their own healthy beats (the latent next instance of this bug).

**Verification:** 8 new tests (4 pure tail cases, end-to-end tmp-HOME transcript,
threshold table, slow-cadence diagnose, daemon wedged + ESC-exempt) — 59 green in the
touched files, 154 green across the daemon/fleet/notify neighborhood, ruff clean.

**NEXT ACTION:** ships in v0.51.1; then watch one real daemon generation (the
2026-07-17 pattern — repeated `attempt=0` on the same root in `daemon.log` — must not
recur; wedged targets must instead show ONE `declined_wedged` + a FLEET-WEDGED push).

## Notes and lessons learned

[^1]: [id:ATOM-PROBE-SELF1, status:valid, keywords:"injection refreshes its own probe liveness mtime queue-operation enqueue attempts reset crash loop guard never trips actuator contaminates sensor", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT let a recovery actuator's own side effect (a typed keystroke appending an
  enqueue record) refresh the liveness signal its diagnosis reads, BECAUSE the failure
  counter resets on every attempt and the crash-loop budget can never trip — an
  infinite, user-visible poke loop. DO verify OUTCOME (the command executed — a
  substantive transcript line), never mere delivery, before clearing attempts.
