---
trdd-id: RQ9FIFX6
title: Disarm/pause must STOP the heartbeat FIRE (delete cron), not just silence output
column: dev
created: 2026-06-30T15:33:39+0200
updated: 2026-06-30T15:33:39+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 0
severity: CRITICAL
effort: M
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: []
---

# Disarm/pause must STOP the heartbeat FIRE (delete cron), not just silence output

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-30

- **USER complaint:** "the janitors are still armed and the heartbeat is running in many
  claude code instances.. why can't you stop them?" + "find the culprit" of the token bleed.
- **CULPRIT (measured, token-meter.jsonl, 21 projects / 13,876 fires):** the heartbeat cron
  ITSELF. Each fire is a full Claude turn inside the live session → re-reads the entire
  accumulated transcript. Median `cache_read` **618k**/fire; fleet raw ~12B tokens processed,
  ~**2B input-equivalent BILLED** (cache_read is 70% of billed cost). Per-fire billed: median
  idle ~63k, average ~169k input-equiv, every 5 min × 21 instances.
- **CACHE MECHANICS (answered to USER):** the context IS cached (median `cache_creation` =
  285 tok/fire → no wasteful re-writes — the user was right). But cache_read is billed at
  **0.1×** input rate, NOT zero: Anthropic's prompt cache is a KV-cache (skips re-COMPUTING
  the prefix, the ~90% discount) but the model still ATTENDS over all 618k tokens every turn.
  "Cached" = 10× cheaper, not free. So a fired turn can't be made cheap — only NOT firing → 0.
  (Bonus: 5-10% of fires miss the cache — 5-min cadence sits at the 5-min TTL boundary — billed
  at the 1.25× write rate = 18% of cost. USER chose keep-5-min, so noted-not-acted.)
- **THREE VERIFIED BUGS behind "can't stop them":**
  1. `dispatch.py:347-366,795` (`_phase_globally_disarmed`/`_phase_global_paused`) — when the
     kill-switch / global-pause flag is set, dispatch exits SILENTLY but **the cron still
     fires** → still pays ~618k cache_read. Silence ≠ stop. Pause/disarm is NOT free.
  2. `on-session-start.py:177` — prints the "run /janitor-arm" nudge **unconditionally**, never
     checking the stop flags → a disarmed machine re-arms a fresh HB on every new/resumed session.
  3. `CronList`/`CronDelete` are **per-session in-memory** → no session can stop another's HB.
- **FIX (this TRDD) — "fix disarm only", keep 5-min cadence, keep the daemon (USER decisions):**
  - **A — dispatch self-disarm:** when a stop flag (kill-switch OR global-pause) is set, instead
    of a silent return, emit a bare `[janitor-self-disarm]` marker so the session DELETES its own
    heartbeat cron (CronDelete via /janitor-disarm) → it stops FIRING → truly free. Self-limiting
    (once deleted, no more fires). Forge-proof (bare/exact line only).
  - **B — re-arm guard:** `on-session-start` skips the /janitor-arm nudge when a stop flag is set
    (and prints a one-line "globally stopped; /janitor-global-arm to resume" note instead). Stops
    the fleet from re-growing + drains it as sessions cycle.
  - **C — arm-prompt clause:** add the `[janitor-self-disarm]` exception to the janitor-arm cron
    prompt ("silently run /janitor-disarm; do NOT echo"). Makes NEW crons self-stop deterministically.
  - **D — keep the daemon:** unchanged daemon lifecycle. For "stop HBs but keep daemon" the USER
    uses `/janitor-global-pause` (it already keeps the daemon alive); now pause TRULY stops the HBs.
    `/janitor-global-disarm` remains the also-stop-the-daemon variant.
- **DEPLOYMENT REALITY (honest):** the cron PROMPT is baked at arm-time (re-arm rollout lag) —
  `dispatch.py` auto-rolls but the prompt does not. So the `[janitor-self-disarm]` marker only
  makes crons armed AFTER this ships self-stop. The 20 EXISTING crons need a one-time manual
  `/janitor-disarm` (or a re-arm to pick up the new clause). Fix B (re-arm guard, a HOOK that
  loads fresh on session start/reload) drains the fleet going forward regardless.
- **NEXT ACTION:** implement A (dispatch.py) + B (on-session-start.py) + C (janitor-arm SKILL.md)
  + tests + docs (CLAUDE.md, README, disarm/pause skills). ruff + pyright + run tests. Commit,
  do NOT push. Then ASK USER to publish (publish.py auto-rolls the daemon back — wanted).

## Why

A guardian whose STOP control silences output but keeps firing a ~618k-token cached turn every
5 minutes — fleet-wide, ~2B input-equivalent tokens billed — is the token-bleed culprit AND is
indistinguishable from "I disarmed it and it won't stop." The flag must make the cron DELETE
itself (the only way a fired turn's cost goes to zero), and session-start must stop re-arming a
stopped machine.

## Acceptance

- kill-switch OR global-pause set → `dispatch.py` emits `[janitor-self-disarm]` (bare) and runs
  no detectors; neither set → normal.
- `on-session-start` set → no /janitor-arm nudge; clear → nudge present.
- janitor-arm cron prompt carries the `[janitor-self-disarm]` silent-execute clause.
- Daemon lifecycle unchanged. 5-min cadence unchanged.
- Every path best-effort; existing rotator/daemon/dispatch tests still pass.

## Notes and lessons learned
