---
name: claude-code-continuity-engineering
description: "claude stalled overnight / fleet stopped working in my absence / session stuck in a retry loop after a 429 / janitor kept injecting commands or compacting at random / how do we keep unattended Claude Code sessions ALWAYS working — the continuity-engineering topic HUB linking every layer of the never-stall stack / how does account rotation prevent 429 stalls / window-asymmetric rotation thresholds 7d vs 5h / how to unstick a frozen retrying session / why does typing text into a blocked session flood the input buffer / janitor backstop versus harness auto-compact competing / nudging an idle armed session to keep working / keep-going-off sentinel to mute nudges / stale-hook ghosts mimic an unfixed bug after a shipped fix / does a shipped fix apply without reloading hooks / per-project channeling so a burn alarm reaches only its own project / ai-maestro server chore must match janitor chore outcome parity / prevention versus recovery two-layer stall fix / TRDD-P7WU40G9 overnight stall incident record"
ocd: 2026-07-18
lmd: 2026-07-18
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: continuity
publish-globally: true
---

**Claude Code continuity engineering** — the discipline of keeping an UNATTENDED fleet of
Claude Code sessions working indefinitely (overnight, in the user's absence), distilled from
the 2026-07-17/18 overnight-stall incident (TRDD-P7WU40G9, shipped v0.53.0+v0.54.0) and the
CC docs verified 2026-07-18. The owner's standing directive: *"they must never stop."*

## The stack — six layers, each owned by its own page

1. **Settings substrate** — the harness must retry instead of stopping, and questions must
   auto-continue: [[claude-code-continuity-settings]] (watchdog + AFK chain, ensured by BOTH
   the janitor and the ai-maestro server in lockstep).
2. **Account rotation (PREVENTION — the load-bearing layer)** — a 429 only stalls a session
   for hours when every retry re-hits the same exhausted account. Window-ASYMMETRIC rotation
   thresholds (7d rejected only at 99, 5h at 97) guarantee a live rotation target:
   [[oauth-rotation-renew-reauth]]; record: TRDD-P7WU40G9 §BUG 1.
3. **Freeze recovery (UNSTICK)** — a session in the retry-watchdog "Retrying in Xm" wait is
   freed with ESC-ONLY injection (2 raw ESCs, zero text, zero Enter — anything typed BUFFERS
   and floods). Semantics: [[claude-code-esc-input-semantics]]; record: TRDD-P7WU40G9 §BUG 3.
4. **Compaction discipline** — the janitor only BACKSTOPS a failed harness auto-compact,
   never competes with it: fire only above `CLAUDE_CODE_AUTO_COMPACT_WINDOW − overhead +
   margin` (`cold_cache_compact.min_context_tokens()`); record: TRDD-P7WU40G9 §BUG 2. The
   exact-prediction formula lives in the USER-scope page
   `feedback-auto-compact-window-prediction-and-prepare-alert` (machine-global wikimem,
   recall by symptom — not wikilinked from this PUSHED page).
5. **Nudging** — an idle-but-armed session is told to continue its pending work on every
   heartbeat (default-ON via `_phase_keep_going_nudge`; muted only by an explicit per-project
   `keep-going-off` sentinel). USER-scope page:
   `feedback-agents-must-never-stop-maintenance-nudges-continue`.
6. **Rollout observability** — a shipped fix is not live in a session until that session
   reloads its hooks; stale-hook "ghosts" mimic unfixed bugs:
   [[claude-code-plugin-rollout-staleness]].

Fleet reachability (which pane can be injected, via which channel): USER-scope page
`janitor-fleet-guardian-reachability`.

## Design laws (cross-layer, all owner-ratified)

- **Prevention beats recovery**: fix rotation first; recovery (ESC) then only accelerates a
  retry that would already succeed. [^1]
- **Never type text+Enter into a blocked session** — ESC-only; the session's own
  `rate-limited.flag → [janitor-resume]` machinery does the continuation.
- **Per-project channeling**: every automatic surface (findings, alerts, token/burn warnings)
  reaches ONLY the project it concerns; the culprit project alone sees its burn alarm
  (TRDD-X92VBFNF, ARCHITECTURE.md §3).
- **Outcome parity**: any ai-maestro server function replicating a janitor chore must be
  identical in outcome (owner 2026-07-18); parity deltas are posted on janitor#100.

## Notes and lessons learned

[^1]: [id:ATOM-CONT-2LAYER, status:valid, keywords:"claude stuck retry loop 429 hours overnight stall two layer fix rotation prevents esc unsticks", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT treat "stuck in a retry loop" as one bug, BECAUSE it is two: the retry re-hitting a
  dead account (rotation failure — the hours-long part) and the session sleeping out the wait
  (recovery gap — the minutes part). DO fix rotation first, then unstick with ESC-only; either
  alone leaves stalls.
