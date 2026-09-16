---
trdd-id: 3JBPW12E
title: A rewrite that drops a script's executable bit cannot be committed
column: dev
created: 2026-09-16T11:11:33+0200
updated: 2026-09-16T11:11:33+0200
current-owner: session
created-by: session
task-type: infra
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T11:11:33+0200
---

# A rewrite that drops a script's executable bit cannot be committed

Symptom: four times today a worker rewrite recreated a tracked script without its executable bit: commits c1bcf97a and dde5acff (hooks), fd8d7d34 (scripts/detectors/orphaned-memory-maint.py), c3e01599 (scripts/dispatch.py); plus 8173c2fc yesterday. Each was caught later and dearer: CI red on 3.5.1, a local full-suite run, then the publish gate red at tests. Cause: file rewrites by fastedit or the Write tool recreate the file with mode 644; git ls-files -s read before git add reports the stale 755 from the index, masking the loss until git actually re-stats the working tree. tests/test_detector_executable_bits.py (3 tests, 0.2 s) already detects every case from the git INDEX, but nothing runs it at commit time. Fix: add a pre-commit hook in the repo's managed hooks directory that runs tests/test_detector_executable_bits.py and refuses the commit when it fails. Acceptance: (1) with a tracked .py under scripts/ chmod 644 and staged, git commit is refused with the test's failure message; (2) with all bits correct, commit proceeds normally; (3) the hook is installed by the same path publish.py --install-hook uses for the pre-push hook, so a fresh clone gets both hooks from one install step; (4) the guard adds under 1 second to a normal commit.

## Approval log

- 2026-09-16T11:11:33+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
