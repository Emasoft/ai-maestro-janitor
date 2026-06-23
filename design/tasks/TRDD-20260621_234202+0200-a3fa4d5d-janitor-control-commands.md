---
trdd-id: a3fa4d5d-d300-45d1-9613-be34ec2b677e
title: Janitor control commands (disarm/pause × local/global) + Wikimem record-recent + terminology
column: complete
created: 2026-06-21T23:42:02+0200
updated: 2026-06-23T17:18:00+0200
current-owner: claude-janitor-dev
parent-trdd: TRDD-324223a6
task-type: feature
release-via: publish
relevant-rules: []
test-requirements: [unit]
impacts: [public-api]
---

# Janitor control commands — the disarm/pause × local/global matrix + Wikimem record

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-21

User asked for a coherent **stop/pause** command surface plus a Wikimem-harvest
command. The model is a 2×2 matrix (severity × scope) + 1 harvest command + a
terminology change. **`/janitor-pause` (local pause) and `/janitor-disarm`
(local disarm) ALREADY EXIST and work** — so most of the matrix is already
there; the genuinely new pieces are the GLOBAL column and the global-pause
*mechanism*.

### The command matrix (severity × scope)

| | Local (this project) | Global (daemon + all instances) |
|---|---|---|
| **Disarm** = true stop / teardown | `/janitor-disarm` ↔ `/janitor-arm` ✅ exist | `/janitor-global-disarm` ↔ `/janitor-global-arm` 🆕 |
| **Pause** = suspend in place | `/janitor-pause` ✅ exists ↔ `/janitor-unpause` 🆕 (rename of `/janitor-resume`) | `/janitor-global-pause` ↔ `/janitor-global-unpause` 🆕 |

- **Disarm** tears down: local removes the cron (`CronDelete`); global sets the
  kill-switch → the daemon EXITS and removes its OS keepalive. Revive = re-arm.
- **Pause** stays installed but idles: local writes `.janitor/state/paused` (cron
  keeps firing, `dispatch.py` no-ops); global sets a NEW global-pause flag → the
  daemon stays ALIVE but skips all task workloads, AND every session's
  `dispatch.py` no-ops. Revive = unpause (instant, no re-spawn).

### Why rename `/janitor-resume` → `/janitor-unpause`

User: *"I won't use 'resume' because it can be misinterpreted as a command to
launch when the claude agent is stopped by some error."* The internal
`[janitor-resume]` heartbeat MARKER (rate-limit/compact resume) is a SEPARATE
mechanism and is **left untouched** — only the user-facing `/janitor-resume`
command is renamed.

### ✅ DONE (all phases shipped 2026-06-22, committed, NOT pushed)
- Phase 1+2 — `216d995`: global-pause flag (`global_state`), daemon idles on it,
  dispatch `_phase_global_paused()`, `kill_switch_cli`→`global_control_cli`
  (disarm/arm/pause/unpause/status). 13 tests.
- Phase 3 — `720b065`: skills — `janitor-global-{disarm,arm,pause,unpause}`,
  `janitor-stop`→`janitor-global-disarm`, `janitor-resume`→`janitor-unpause`,
  `janitor-memory-record-recent`, `/janitor-arm` revert. End-to-end CLI verified.
- Phase 4 — `1073626`: README control matrix + Wikimem terminology + CLAUDE.md.
- VERIFIED: 11,248 tests collect (no import break), 107 affected green, zero stale
  refs. **Open for the USER: publish to ship (release-via: publish).**

### Original NEXT ACTIONS (phase order) — all complete
1. **Phase 1 (code, done-by-me):** `global_state` global-pause flag
   (`set/clear/global_pause_present` + path); rename `kill_switch_cli.py` →
   `global_control_cli.py` with subcommands `disarm|arm|pause|unpause|status`;
   tests.
2. **Phase 2 (wiring):** `daemon.py` loop idles on `global_pause_present()` (stays
   alive, skips tasks); `dispatch.py` Phase-0 also no-ops on `global_pause_present()`;
   tests.
3. **Phase 3 (skills, parallel agents):** rename `janitor-stop`→`janitor-global-disarm`;
   create `janitor-global-arm`, `janitor-global-pause`, `janitor-global-unpause`;
   rename `janitor-resume`→`janitor-unpause` (update `/janitor-pause`'s reference);
   create `janitor-memory-record-recent`. REVERT the kill-switch-clear added to
   `/janitor-arm` (now `/janitor-global-arm`'s job) — local arm must NOT silently
   undo a deliberate global disarm; instead it WARNS if globally disarmed.
4. **Phase 4 (docs, agent):** "Wikimem" (capital W) as the official name in README +
   all docs; README commands table; CLAUDE.md skills list.
5. **Phase 5:** full test run + ruff + commit (NO push).

### Load-bearing facts
- `dispatch.py:_phase_paused()` (line ~328) is the local-pause check; Phase 0 in
  `main()` (line ~673) returns 0 when paused. Mirror for global-pause.
- `daemon.py` loop (line ~945): kill-switch check, then the `for task in tasks`
  loop. Insert the global-pause idle right after the kill-switch check.
- The kill-switch is the DISARM mechanism (daemon exits); global-pause is a
  SEPARATE flag (daemon idles). Distinct files, distinct semantics.

## /janitor-memory-record-recent

A USER-invoked skill that nudges the MAIN claude to harvest recent changes into
**Wikimem** NOW (the active counterpart of the `memorize-nudge` heartbeat
detector). It: recalls first (don't duplicate), inspects recent commits / session
edits, and for each substantive change either adds an atomic memory to an existing
Wikimem page, updates a page, or creates a new expand/reduce page — leaning on the
existing `/janitor-memory-write` / `-update` skills + the wikimem model. Motivation
(user): claude often makes many changes but forgets to update Wikimem.

## Terminology

"**Wikimem**" (capital W) is the official name of the markdown memory system from
now on — update README + all docs.

## Safety / invariants
- Disarm vs pause are DISTINCT flags — a pause never tears down; a disarm never
  merely idles.
- Global pause keeps the daemon ALIVE (heartbeat ticks) so it is not seen as
  wedged and unpause is instant.
- No backward-compat: `/janitor-resume` is RENAMED, not aliased.
- `/janitor-arm` no longer touches the global kill-switch (explicit
  `/janitor-global-arm` owns global revive).
