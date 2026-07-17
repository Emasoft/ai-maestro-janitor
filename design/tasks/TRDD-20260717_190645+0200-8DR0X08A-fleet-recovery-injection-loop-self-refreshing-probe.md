---
trdd-id: 8DR0X08A
title: Fleet-recovery injection loop — the injected keystroke refreshes its own liveness probe, so wedged sessions get typed at forever
column: todo
created: 2026-07-17T19:06:45+0200
updated: 2026-07-17T19:06:45+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
related-trdd: [324223A6, 56D24C02, 4649ZLE0, ME8V2YJF]
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**USER REPORT (2026-07-17, verbatim):** *"the janitor continue printing multiple time
commands like /janitor-resume /janitor-arm /janitor-reload-plugins etc."* — the owner is
watching their panes fill up with janitor-typed slash-commands, repeatedly, all day.

**ROOT-CAUSED same evening (evidence in `global-state/daemon.log` + `recovery-audit.ndjson`
+ the target sessions' transcripts). Three interacting defects in the `session-liveness`
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

**NEXT ACTION:** await the owner's decision on immediate mitigation vs straight to the
fix; then implement F1–F3 with tests (`tests/test_session_liveness.py` /
`test_fleet_scan.py` additions).

## Notes and lessons learned

[^1]: [id:ATOM-PROBE-SELF1, status:valid, keywords:"injection refreshes its own probe liveness mtime queue-operation enqueue attempts reset crash loop guard never trips actuator contaminates sensor", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT let a recovery actuator's own side effect (a typed keystroke appending an
  enqueue record) refresh the liveness signal its diagnosis reads, BECAUSE the failure
  counter resets on every attempt and the crash-loop budget can never trip — an
  infinite, user-visible poke loop. DO verify OUTCOME (the command executed — a
  substantive transcript line), never mere delivery, before clearing attempts.
