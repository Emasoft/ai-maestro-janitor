---
trdd-id: A2JLFIQ5
title: the rotator's automatic tick does not say why the primary credential was not read
column: todo
status: tasked
created: 2026-10-05T15:21:19+0200
updated: 2026-10-05T15:21:53+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T15:21:19+0200
parent-trdd: QQ7QCS3T
---

# the rotator's automatic tick does not say why the primary credential was not read

The headless daemon skips the read of the primary live credential on purpose and works from the mirror copy (default-off behaviour shipped in 2b18348f; the owner question on that default is TRDD-QQ7QCS3T). The line the automatic tick logs when it uses the mirror carries no reason, so that line reads the same whether the read was skipped by policy, failed, or the mirror itself was hard to read. The capture path does name its reason.

Consequence seen on 2026-10-05: a reader of the log took the designed skip for a defect, opened TRDD-HVGU9OBL, and withdrew it after reading the code.

Wanted: the automatic tick's line names the reason the primary was not read, in the same words the capture path uses, so a skip by policy, a failed read and a degraded mirror read can be told apart from the log alone. A log-text change only; no change to what is read or to any keychain call.

## Approval log

- 2026-10-05T15:21:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Acceptance

- [ ] A test shows the automatic tick's line contains the policy-skip reason when the headless setting is on.
- [ ] A test shows a different, distinguishable reason when the primary read is attempted and fails.

## STATE

2026-10-05 — Column todo. Nothing built. The change touches the rotator's logging only; because the rotator is credential code, a review must confirm no read, write or prompt is added.
2026-10-05 — OPEN OBSERVATION, unexplained and on no other card: on 2026-10-05 the heartbeat printed slot reads from the credential store timing out at their five-second limit while the machine's load was very high. Whether those timeouts were load alone was not determined, and it was not checked that the mirror read itself succeeded on the ticks that used it. Working from the mirror is by design a reduced-trust state (the identity is treated as untrusted).
