---
trdd-id: L87BQ2Y9
title: Self-trigger hard interrupt must send TWO ESCs — one clears the tool, one ends the turn
column: dev
created: 2026-07-01T23:42:53+0200
updated: 2026-07-01T23:55:25+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: S
task-type: bugfix
parent-trdd: TRDD-87935f21
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
merge-strategy: squash
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: []
external-refs: []
---

# TRDD-L87BQ2Y9 — Self-trigger hard interrupt must send TWO ESCs

## Why

The janitor's self-trigger commands (`/compact`, `/reload-plugins`, `/reload-skills`)
and the daemon's fleet-recovery injector fire a **DETACHED, delayed** keystroke sender
that, on the HARD path (`esc_first=True`), sends **one** ESC then types the command. The
design assumes the agent has ENDED ITS TURN before the sender fires (~2 s later), so the
single ESC lands on an idle pane and the command runs.

But if the agent is still mid-turn when the ESC fires — e.g. it kept processing heartbeats
/ reading files instead of ending immediately — one ESC is **not enough** on this Claude
Code build: a single ESC only cancels the in-flight **TOOL** (e.g. a running Bash command),
leaving the **turn** alive. The typed `/compact` then merely **ENQUEUES** behind the live
turn and does not run until the turn happens to end.

USER-observed 2026-07-01 (verbatim): *"the compact command is still on the command queue.
you injected esc once, but that only exited a shell command, not the turn. you have to press
esc twice to get out of the turn and out of the shell command too."*

This is a P6 machinery bug of the memory-curation mission (TRDD-87935f21, priority 6 — the
background machinery must run error-free): the self-compact skill's own trigger couldn't
reliably fire `/compact`.

## Root cause

Every HARD-interrupt keystroke builder emitted exactly ONE ESC:
- `terminal_trigger.build_tmux_steps` / `build_wtype_steps` / `build_xdotool_steps`
- `compact_trigger._build_osascript`, `reload_trigger._build_osascript`,
  `reload_skills_trigger._build_osascript`, `fleet_inject.iterm_osascript`

On this CC build the interrupt hierarchy is two-level (running tool, then turn), so a hard
interrupt needs TWO ESCs with a settle between them.

## What changed

`scripts/lib/terminal_trigger.py` — ONE source of truth:
- `HARD_INTERRUPT_ESC_COUNT = 2` + `_ESC_SETTLE_S = "0.6"` (the per-ESC settle, hoisted).
- `iterm_esc_lines(indent)` — the shared AppleScript ESC block (N raw-ESC writes + settle),
  reused by all four iTerm osascript builders so the two-ESC rule lives in one place.
- `build_tmux_steps` / `build_wtype_steps` / `build_xdotool_steps` loop the ESC step
  `HARD_INTERRUPT_ESC_COUNT` times on the `esc_first` path.

The four iTerm builders (`compact_trigger`, `reload_trigger`, `reload_skills_trigger`,
`fleet_inject`) now build their ESC block from `terminal_trigger.iterm_esc_lines()`.

SOFT path (`esc_first=False`) is untouched — it sends NO ESC (enqueue), so nothing changes.
Both ESCs are harmless on an already-idle pane, so the double-press is safe whether or not a
tool is actually running (idle → both no-op; tool running → tool then turn; streaming → turn
then no-op). The fleet-recovery path (a FROZEN target) benefits most: two ESCs are more
likely to unstick tool+turn than one. The double-press is also belt-and-braces for the
agent's own discipline of ending its turn immediately after firing the trigger.[^1]

## Acceptance

- Every HARD builder emits `HARD_INTERRUPT_ESC_COUNT` (=2) ESCs before the command; SOFT
  emits zero. MET (pinned by tests).
- The single `HARD_INTERRUPT_ESC_COUNT` constant governs all 7 builders. MET.
- ruff/pyright clean; full `tests/` suite green. (verify before publish)

## Notes and lessons learned

[^1]: The deeper discipline half — the agent must END ITS TURN IMMEDIATELY after firing the
  trigger (the skills already say so) — is NOT a code fix; the double-ESC is the belt-and-
  braces for when the agent fails to end promptly. Recorded so a future session doesn't
  "fix" the discipline gap in code.
