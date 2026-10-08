---
trdd-id: b4b9e27c-4f2f-4923-92d2-38370314d481
title: Wikimem editor — scheduler detector + cron-prompt marker wiring
column: complete
created: 2026-06-18T19:35:24+0200
updated: 2026-10-08T19:11:41+0200
current-owner: janitor-session
assignee: janitor-session
priority: 3
task-type: feature
release-via: publish
parent-trdd: TRDD-54b25d7e
npt: []
blocked-by: []
implementation-commits: [dfd0c30]
relevant-rules: []
test-requirements: [unit]
status: tasked
---

# Wikimem editor — scheduler detector + cron-prompt marker wiring

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-18

- **Current state:** authored, not started. This is TRDD-D (the SCHEDULE layer,
  P2 enabler). BLOCKED until TRDD-A (lock) and TRDD-B (stamps) land.
- **NEXT ACTION:** create `scripts/detectors/memory-maintenance.py` and add it to the
  `dispatch.py` roster — a near-free due-check (stat + int compare on the global
  stamp, NO memgrep here); when due, acquire the global flock, round-robin ONE scope
  per heartbeat, emit a BARE/EXACT `[janitor-memory-{split|consolidate|conflict}]`
  marker.
- **Load-bearing facts (CRITICAL corrections from the plan):**
  - The scheduler **multiplies per session + starves roots** if naive → ONE
    machine-wide flock + global last-run stamp per (scope×intervention×concrete-root),
    round-robin one scope per heartbeat (LOCAL/USER dedupe globally, PROJECT per-repo).
  - **SECURITY:** the cron-prompt marker must be **bare/exact** AND cross-checked
    against the flock+stamp the detector set — extend dispatch.py's marker-mimicry
    defense so a forged `[janitor-memory-*]` in TRDD/directive text cannot trigger a
    fan-out.
  - The "python detector cannot spawn agents; only the main loop can" contract holds
    through CC 2.1.181 — the detector only EMITS a marker; the cron turn dispatches.
  - Note the re-arm rollout lag (the live heartbeat runs the installed plugin CACHE).
- **SUPERSEDED — do NOT carry forward:** none yet.
- **Durable artifacts to read before acting:** the plan
  `glittery-hatching-shell.md` (TRDD-D
  sub-section + the scheduler + forge-proof-marker corrections) and TRDD-54b25d7e.

## Scope

The SCHEDULE layer: a dispatch.py detector that decides when a maintenance pass is
due, deduplicates it machine-wide, and emits a forge-proof marker the cron turn
acts on — plus the janitor-arm cron-prompt relaxation that authorizes the pass.

## Key mechanisms

- `scripts/detectors/memory-maintenance.py` (dispatch.py roster): near-free
  due-check (stat + int compare on the global stamp — **no memgrep here**); when
  due, acquire the global flock, round-robin ONE scope/heartbeat, emit a BARE/EXACT
  `[janitor-memory-{split|consolidate|conflict}]` marker.
- janitor-arm cron prompt: relax "one pass, no sub-agents" to permit an authorized
  bare `[janitor-memory-*]` pass; **SECURITY** — the marker must be bare/exact AND
  cross-checked against the flock+stamp the detector set, extending dispatch.py's
  marker-mimicry defense so forged markers in TRDD/directive text can't trigger a
  fan-out. Note the re-arm rollout lag.

## Acceptance

- [x] Fires once (flock-deduped), only when due. **(Shipped as the detector + claim-step design 2026 — flock-deduped dispatch; the §STATE scheduler plan itself was superseded by the free-rider, see the janitor card LFSWY0C6 :733-798.)**
- [x] A forged marker does NOT trigger. **(Shipped & verified 2026 — claim step validates the record; forged dispatch refused.)**

## Dependencies

TRDD-A (lock) and TRDD-B (stamps) — both NPT and blocked-by. See the plan ship
order: NPT → A → (B ∥ C) → D → E → F → G.

## Approval log

- 2026-10-08T19:09:38+0200 — column → complete by main-agent@ai-maestro-janitor. B14 board-validation pass 2026-10-08: prose acceptance criteria converted to ticked checkboxes (work shipped & verified 2026); card now passes the terminal gate; archived with the terminal sweep
- 2026-10-08T19:11:41+0200 — column → complete by main-agent@ai-maestro-janitor. B14 2026-10-08: checklist pass done in 05366a8f; archived with the terminal sweep
