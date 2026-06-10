---
name: login-panel
description: "login panel behavior / forgot password flow / where does auth UI live"
ocd: 2026-06-10
lmd: 2026-06-10
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: frontend
---
The auth entry panel (`src/frontend/panels/Login.tsx`). ONLY what is specific to
this element — visuals and dialog behavior come from its governors below:

- "Forgot password" routes to `/reset`, which emails a one-time link (no Q&A).
- Failed logins show the SAME message for wrong-user and wrong-password
  (anti-enumeration).
- Reads/writes the user record described in [[user-model]].

## Governed by
- [[frontend]] — the hub (stack, routing conventions).
- [[style-system]] — palette/spacing/fonts.
- [[dialog-forms]] — the dialog + form-error protocol.

## See also
- [[user-model]] — the backend record this panel authenticates against.

## Notes and lessons learned
