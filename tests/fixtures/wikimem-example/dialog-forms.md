---
name: dialog-forms
description: "how should dialogs ask the user / confirm destructive action / form and dialog interaction rules"
ocd: 2026-06-10
lmd: 2026-06-10
metadata:
  node_type: memory
  type: project
  tier: aspect
  functionality: frontend
---
The shared dialog/interaction protocol (written ONCE here):

- Every dialog asks ONE question; multi-step flows are wizards, never stacked
  dialogs.
- Destructive actions: primary button is Cancel; the destructive verb is the
  SECONDARY button in `--warn` (visual half in [[style-system]]).[^1]
- Form errors render inline under the field, never as toasts.

## Applies to
- [[login-panel]]
- [[settings-panel]]

## Governed by
- [[frontend]] — the hub framing these interaction rules.

## See also
- [[style-system]] — the visual tokens this protocol's buttons use.

## Notes and lessons learned
[^1]: [ocd:2026-06-10 lmd:2026-06-10] this rule originally made the destructive
  verb the PRIMARY button ("fewer clicks"). Superseded: usability testing showed
  muscle-memory Enter presses triggered deletions — the error was optimizing for
  click count over the cost of a mistaken default. Lesson: the DEFAULT action
  must always be the safe one; speed never justifies a destructive default.
