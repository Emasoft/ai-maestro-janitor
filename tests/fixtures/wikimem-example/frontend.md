---
name: frontend
description: "what do we know about the frontend / where do frontend decisions live / overall frontend structure and rules"
ocd: 2026-06-10
lmd: 2026-06-10
metadata:
  node_type: memory
  type: project
  tier: hub
  functionality: frontend
  globs: ["src/frontend/**", "public/**"]
---
The frontend is a React SPA under `src/frontend/`. Big standing decisions:

- Library stack: React 19 + vanilla CSS tokens (no Tailwind — rejected for bundle size).
- All visual rules live in [[style-system]]; all dialog/interaction rules in
  [[dialog-forms]]. Components NEVER restate them — they link up.
- Routing is file-based under `src/frontend/pages/`; panels under
  `src/frontend/panels/`.

Parts map (the functionality's iceberg, tip → details):

## Applies to
- [[style-system]] — the shared visual rules (palette, spacing, fonts).
- [[dialog-forms]] — the shared dialog/interaction protocol.
- [[login-panel]] — the auth entry panel.
- [[settings-panel]] — the user settings panel.

## Notes and lessons learned
