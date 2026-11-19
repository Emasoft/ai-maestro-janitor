---
trdd-id: OCGPATUK
title: The rotator slot-capture child is never waited and stays a zombie until the next capture
column: proposal
status: proposed
created: 2026-11-19T23:30:32+0100
updated: 2026-11-19T23:30:32+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: user
scope: project
project-id: ai-maestro-janitor
approved: false
---

# The rotator slot-capture child is never waited and stays a zombie until the next capture

rotator.py _invoke_slot_capture starts slot_capture_browser.py with subprocess.Popen (line ~3311) and never waits on it (ubs python.lifecycle.popen_handle). CPython reaps it only at the next Popen via subprocess._cleanup, so each finished capture leaves one zombie process until another capture starts. Fix: reap in a daemon thread (proc.wait) — this does not change which account rotates or when. Held only because the owner froze the rotator code to lint-only edits (2026-11-05); needs owner approval. Found by TRDD-Z691NW1P.

## Approval log
