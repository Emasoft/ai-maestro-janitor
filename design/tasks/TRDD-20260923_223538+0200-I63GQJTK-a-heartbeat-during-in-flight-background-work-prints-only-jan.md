---
trdd-id: I63GQJTK
title: A heartbeat during in-flight background work prints only janitor heartbeat, so a working session looks stalled to the owner
column: todo
created: 2026-09-23T22:35:38+0200
updated: 2026-09-23T22:35:38+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-23T22:35:38+0200
---

# A heartbeat during in-flight background work prints only janitor heartbeat, so a working session looks stalled to the owner

Owner, 2026-09-23 22:35 (verbatim): "you stopped again? and the janitor is the one supposedly tasked with guarantee continuity... and it fails in its very plugin repo..". Observed: for about 35 minutes (21:58-22:33) a background worker was implementing and running real-transcript acceptance tests, while every heartbeat fire returned [janitor-quiet] and the session replied only "janitor heartbeat", per the heartbeat protocol's output contract (owner directive 2026-08-12). From the owner's seat that is indistinguishable from a stalled session. The dispatcher already lists pending background agents for [janitor-resume] (dispatch._pending_agent_directive_lines), but a quiet fire prints nothing about them. Fix direction: when background agents or background shells launched by this session are still running, a quiet fire emits ONE progress line (count of running workers and the age of the newest activity, e.g. from the subagent transcript mtimes), and the session relays it; when a worker has shown no activity for longer than a threshold, emit a stall finding instead. Keep the zero-noise contract for truly idle sessions. Acceptance: a session with a running worker shows one progress line per fire; an idle session still prints only janitor heartbeat; a worker silent past the threshold raises a finding.

## Approval log

- 2026-09-23T22:35:38+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
