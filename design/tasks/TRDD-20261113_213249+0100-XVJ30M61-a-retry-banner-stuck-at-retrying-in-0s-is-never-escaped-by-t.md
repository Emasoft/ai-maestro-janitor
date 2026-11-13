---
trdd-id: XVJ30M61
title: A retry banner stuck at Retrying in 0s is never escaped by the fast lane
column: todo
status: tasked
created: 2026-11-13T21:32:49+0100
updated: 2026-11-13T22:15:06+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-13T21:32:49+0100
parent-trdd: RJJGXPIK
derived: true
---

# A retry banner stuck at Retrying in 0s is never escaped by the fast lane

Child of TRDD-RJJGXPIK (EHT). Blocks RJJGXPIK reaching complete: the owner's reported freeze may be this shape.

## Facts

- Real frame tests/fixtures/pane_frames/real-wedged-rate-limit-429.txt shows '429 Rate limited · Retrying in 0s · attempt 5/300'.
- scripts/lib/session_liveness.py _SECOND_SCALE_RE (line 187) rejects all-zero values. The exclusion (comment at lines 183-184, 'a hung request shows Retrying in 0s forever, a different failure') was added by an agent in ee837c54, not by the owner.
- For 0s the 3 s recheck proves nothing (0s == 0s). The only on-screen discriminator is the attempt number. A static attempt at 0s is a request in flight, indistinguishable from a slow request until Claude Code's own API request timeout.
- Any bar must come from that timeout as configured on this machine (settings env API_TIMEOUT_MS, docs, or memory page claude-code-continuity-settings), not a remembered default.

## To establish

- Does a static 0s + static attempt ever get ESC today? Trace diagnose_instance past the wedge branch (scripts/lib/session_liveness.py) and the stale-lane recovery. Suspected: only the rotation pass (daemon.py _rotation_esc_pass) ESCs it.

## Approval log

- 2026-11-13T21:32:49+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Implementation notes

2026-11-13 investigation (reports_dev/sonnet-worker/20261113_221409+0100-xvj30m61-0s-investigation.md): a static `0s` + static attempt is never wedge-confirmed; neither the fast lane nor the stale lane sends ESC. The only ESC is daemon.py _rotation_esc_pass, within 600 s of an OAuth rotation.
A live 0s retry loop advances the attempt (ARCHITECTURE.md:392); the uncovered shape is 0s with a STATIC attempt, i.e. a request in flight or hung, indistinguishable on screen from a slow request.
API_TIMEOUT_MS on this machine is 19000000 ms (5 h 17 min). A bar tied to it fires after about 5 h 21 min. A bar of about 540 s needs proof that Claude Code's 5-min stream idle watchdog aborts and bumps the attempt of a no-first-byte request (unverified, needs a captured frame).
Countdown text is not logged today, so past 0s episodes cannot be counted. Cheap prerequisite: log `retry_wedge@<attempt>[<retry_in>]` on each pane read.
OWNER DECISION NEEDED: (a) safe bar from API_TIMEOUT_MS (~5.3 h here), (b) verify the stream idle watchdog first and use ~540 s, or (c) accept the risk of ESCing a slow request with a short bar.
