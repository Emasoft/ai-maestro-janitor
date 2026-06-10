---
name: settings-panel
description: "settings panel behavior / account deletion flow / where do user preferences live in the UI"
ocd: 2026-06-10
lmd: 2026-06-10
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: frontend
---
The user settings panel (`src/frontend/panels/Settings.tsx`). Element-specific
decisions only:

- Sections: Profile, Notifications, Danger Zone — in that fixed order.
- Account deletion uses the destructive-dialog protocol from its governor (the
  verb is "Delete account", typed-confirmation required on top of the standard
  protocol — that EXTRA step is this panel's own rule).

## Governed by
- [[frontend]] — the hub.
- [[style-system]] — visual tokens.
- [[dialog-forms]] — dialog protocol (the typed-confirmation is added on top).

## Notes and lessons learned
