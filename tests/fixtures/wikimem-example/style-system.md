---
name: style-system
description: "which colors fonts spacing to use / why does this component look off-brand / frontend visual rules"
ocd: 2026-06-10
lmd: 2026-06-10
metadata:
  node_type: memory
  type: project
  tier: aspect
  functionality: frontend
---
The shared visual rules every frontend element obeys (written ONCE here — never
restated in a component):

- Palette: 6 tokens — `--ink`, `--paper`, `--accent`, `--accent-2`, `--warn`,
  `--ok`. No raw hex in components.
- Spacing: 4px grid (`--s1`=4 … `--s6`=32). Fonts: Inter for UI, JetBrains Mono
  for code.
- Destructive affordances always use `--warn` on the SECONDARY button (see
  [[dialog-forms]] for the interaction half of that rule).

## Applies to
- [[login-panel]]
- [[settings-panel]]

## Governed by
- [[frontend]] — the hub whose general decisions (stack, no-Tailwind) frame these rules.

## See also
- [[dialog-forms]] — the interaction protocol that pairs with these visuals.

## Notes and lessons learned
