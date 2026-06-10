---
name: user-model
description: "user record shape / what fields does a user have / email uniqueness"
ocd: 2026-06-10
lmd: 2026-06-10
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: backend
---
The backend user record (`src/backend/models/user.py`). Element-specific
decisions:

- `email` is unique-indexed and case-folded on write.
- Passwords are argon2id; the hash column is `pw_hash`, never `password`.
- Soft-delete only (`deleted_at`), so auth history survives account deletion.

## See also
- [[login-panel]] — the frontend panel that authenticates against this record.

## Notes and lessons learned
