---
trdd-id: MF10XF87
title: The janitor-reload marker fires on __pycache__ churn and never clears after a manual reload
column: backburner
created: 2026-08-26T05:58:43+0200
updated: 2026-08-26T05:58:43+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [heartbeat, markers, plugin-cache, noise]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# `[janitor-reload]` fires when nothing reloadable changed

## What was observed (reported by the CORE session, 2026-08-25/26)

- **8 `[janitor-reload]` fires** where the only files newer than the stored ack
  were `__pycache__/*.pyc` — compiled bytecode, which no reload consumes. The
  marker is emitted, the session runs `/reload-plugins --force`, the prompt-cache
  prefix is destroyed and the whole window is re-billed (see TRDD-VHPYSN56 for why
  that cost is not academic), and nothing was actually reloaded.
- **A MANUAL `/reload-plugins` advances no ack.** The slash command fires no hook,
  so the detector's "you have reloaded, stand down" signal is never written. A
  session the user reloaded by hand therefore keeps receiving the marker forever.

## Root cause (hypothesis — NOT yet traced in code)

Change detection is keyed on **file mtimes under the plugin cache**, so any write
into that tree — including a Python interpreter writing `.pyc` files as a side
effect of merely *importing* janitor code — looks like "a plugin changed".

## The fix

Key the detector on the **cached VERSION SET** (the set of
`<plugin>@<marketplace> -> version` currently resolved) rather than on file
mtimes. A reload is warranted exactly when that set differs from the set the
session last loaded; bytecode churn cannot change it, and a manual reload
converges because the loaded set catches up on its own.

Derived consequence to handle in the same change: with a version-set key, the
"ack" stops being a timestamp and becomes the set itself, so the manual-reload
gap closes without needing a hook on the slash command.

## Relates to

- janitor#101 (same detector family)
- TRDD-VHPYSN56 — why a needless `/reload-plugins` is expensive, not merely noisy

## Notes

Carried out of the 2026-08-26 session handoff, where it was listed as an
uncarded defect. Reported second-hand by the CORE session; the 8-fire count and
the `__pycache__`-only delta are **their** measurement, not one I reproduced —
reproduce before fixing.
