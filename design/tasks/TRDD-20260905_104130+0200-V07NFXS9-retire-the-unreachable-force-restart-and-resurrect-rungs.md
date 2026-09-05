---
trdd-id: V07NFXS9
title: retire the unreachable force_restart and resurrect rungs and their tests
column: todo
created: 2026-09-05T10:41:30+0200
updated: 2026-09-05T10:41:30+0200
current-owner: main-session
task-type: refactor
priority: low
severity: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, fleet-restart, dead-code]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-56d24c02, TRDD-L32WC0H7, TRDD-FB84YUGT]
---

# Retire the unreachable hard-restart rungs

## Why

TRDD-56d24c02 closed 2026-09-05 with the decision RETIRE (option 2), reversed from an initial
"leave as-is" by adversarial review: rungs 6/7 — `build_force_restart` and `build_resurrect`
in `scripts/lib/fleet_restart.py` — have been UNREACHABLE since TRDD-L32WC0H7 F1 capped
`action_for("frozen")` at `esc_nudge`. That card traced the single call chain and found no
alias via `git grep`. This repo's own directive is no dead code; a capability nothing can reach
is dead code with a safety story attached, which is the most misleading kind.

The decision is 56d24c02's; this card is only the execution, split out because it touches the
daemon's recovery path and deserves its own gates rather than a closing edit on a closed card.

## What

- Remove `build_force_restart`, `build_resurrect`, the `janitor-resurrect-<pid>` tmux-window
  plumbing, and every rung-6/7 branch in `daemon.py`'s recovery ladder, plus their tests.
- Re-verify BEFORE deleting that nothing reaches them: `tldr impact build_force_restart
  scripts/` and `tldr impact build_resurrect scripts/` (fallback: `grep -rn` across scripts/,
  tests/, skills/, hooks/, commands/, docs — prose that names a deleted thing still fails at
  runtime).
- The safety invariants 56d24c02 named must survive the deletion unchanged: the default-off
  hard-restart flag, `is_killable`, the crash-loop cap. If any of them exists ONLY to guard the
  deleted rungs, delete it with them and say so.
- The `frozen` diagnosis stays capped at `esc_nudge`; the docstring at `fleet_restart.py:10-12`
  that describes rungs 6/7 is rewritten to say they were retired and why (TRDD-56d24c02).

## Acceptance criteria

- [ ] No symbol, string, or prose reference to `force_restart` / `resurrect` remains outside
      git history and the two cards that record the decision.
- [ ] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright`, and the fleet_restart/daemon test modules all green.
- [ ] A recovery-ladder test asserts that `frozen` still resolves to `esc_nudge` and that no
      rung beyond it exists.

## Notes and lessons learned

- **"Lowest cost" is the reason the no-dead-code rule exists to override.** 56d24c02 was
  first closed as "leave the rungs in place, exhaustion alerts a human" — cheaper today, and a
  permanent invitation to the next reader to believe a recovery path exists that does not.
