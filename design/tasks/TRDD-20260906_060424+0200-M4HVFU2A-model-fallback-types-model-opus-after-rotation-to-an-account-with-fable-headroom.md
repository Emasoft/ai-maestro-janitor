---
trdd-id: M4HVFU2A
title: The model-fallback detector keeps typing /model opus into every session after a rotation onto an account whose Fable window is not enforced
column: dev
created: 2026-09-06T06:04:24+0200
updated: 2026-09-06T06:04:24+0200
current-owner: janitor-main-session
task-type: bugfix
priority: critical
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
relevant-rules: []
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-06

Reported 06:05 by the ai-maestro hub session (peer message) and confirmed by the USER
("i see the command to switch to opus still sent to all claude instances"; "fix and update those
damn blind scripts that does not realize that we have already switched to an account with fable
headroom"). Measured first-hand with the detector's own gather (`rotator_usage.accounts_usage()`):
live account fresh (172 s), 5h 18 % / 7d 69 %, Fable **97 %** — above the detector's
`_SCOPED_HIGH = 90`, so by its threshold the verdict is "spent" and it is not reading a stale
or wrong account. The peer's diagnosis (b) is wrong on that point; the real defects are:

1. **Wrong bar.** 90 % used is the rotator's EARLY-rotation trigger; for a model switch the
   only honest bar is the API's own enforcement flag (`limits[].is_active`, or 100 %). The
   probe entry for the live account is `severity: warning`, `is_active: false`.
2. **No rotation-first check.** USER ruling: rotation comes BEFORE any model change, because a
   model change invalidates the prompt cache of every agent. The detector never asks whether a
   sibling slot still has Fable.
3. **No backoff after a human cancel.** An unconfirmed switch is "retryable" by design, so a
   cancelled dialog is re-typed every 5-minute heartbeat, in every session. This is the loop.
4. Doc drift: `dispatch.py:487` says the detector ships dark; `model_fallback.enabled()`
   defaults ON by design.

Fix in flight (lean-worker): `require_active` on `model_fallback_verdict` (detector passes
True; the rotator's cmd_auto keeps 90 for early rotation), a rotate-first stand-down line
naming the slot to rotate onto, a `model-fallback-declined.ts` stamp with a 3600 s backoff,
and the comment fix. Immediate mitigation for running sessions (which use the cached 3.4.14,
not this tree): the last-switch cooldown stamp written into every project that fired a
heartbeat in the last hour, so no pane is typed into until the fix is published and updated.
NEXT ACTION: verify the worker's gate first-hand, commit, publish (`publish.py --patch`),
`claude plugin update`, reply to the peer with what changed.

## Acceptance

- [ ] a 97 % / not-active Fable window produces NO verdict on the detector path
- [ ] with any non-live slot holding Fable headroom the detector types nothing and names it
- [ ] a cancelled/unconfirmed switch is not re-typed for 3600 s
- [ ] existing rotator early-trigger behaviour (90 %) unchanged and its tests green
- [ ] published and installed on this host; the peer session confirms the retyping stopped
