---
description: oauth rotator keychain path memory with a metadata-prefixed lesson
tags: [oauth, keychain]
---
# Rotator creds

The rotator creds live in the macOS keychain, not a slots dir.[^9]

## Notes & Lessons Learned

[^9]: [ocd:2026-06-01 lmd:2026-06-09 class:reference] earlier the plan assumed a
  `slots/` directory on disk; wrong — creds are in the OS keychain. Lesson: check
  where the secret actually lives before coding a file path.
