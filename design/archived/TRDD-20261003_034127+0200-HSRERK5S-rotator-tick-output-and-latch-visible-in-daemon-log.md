---
trdd-id: HSRERK5S
title: Rotator tick output and latch visible in daemon log
column: complete
status: archived
created: 2026-10-03T03:41:27+0200
updated: 2026-10-07T04:17:16+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:27+0200
project-id: ai-maestro-janitor

parent-trdd: JSQSJ3PZ
derived: true
---

# Rotator tick output and latch visible in daemon log

- **R5**: log the tick's rc and stderr tail in `daemon.log`. No latch change: a hung `security` prompt also uses ~0 CPU, so "starved" cannot be told apart from it.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:27+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T09:31:50+0200 — column → dev. R5 in progress
- 2026-10-03T09:37:41+0200 — column → testing. code ready, field check after release: a failing tick's cause appears in daemon.log
- 2026-10-07T04:17:16+0200 — COMPLETE by main-agent@ai-maestro-janitor. live check proven 2026-10-07: two rc=1 rotator tick lines with stderr tail in daemon.log.1.

## STATE

2026-10-05 — FIELD CHECK, from a worker's read of the logs, not re-read by the main agent: Field check passed: since the 3.7.0 daemon start (2026-10-04T12:38) daemon.log carries 5 abnormal-tick lines (rc=0 with a non-empty stderr tail, keychain lookup timeouts, all on 2026-10-05); 0 before release. CORRECTED 2026-10-07: the claim that no tick with rc != 0 had occurred was wrong. The one unproven item, a rotator tick with rc != 0 showing its code and stderr tail in daemon.log, is PROVEN: global-state/daemon.log.1 in the janitor plugin data dir has two such lines, at 2026-10-05T14:41:58+0200 (line 6815) and 2026-10-05T15:56:37+0200 (line 7443): 'rotator tick rc=1 stderr: icate' followed by the traceback tail ending 'subprocess.TimeoutExpired: Command [ps, -eo, args=] timed out after 10 seconds'. Only scripts/daemon.py _log_rotator_tick_result (line 870 in 3.8.2) emits 'rotator tick rc='. The first stderr line is the fragment 'icate' because the tail is cut at 300 characters; the cause is still readable. NEXT ACTION: none - complete.
2026-10-05 — possibly related: TRDD-HVGU9OBL (the primary live credential was unreadable on every logged rotator tick); a hypothesis, not a finding.
2026-10-05 — the 'possibly related: TRDD-HVGU9OBL' line above is WITHDRAWN: that card turned out to describe designed behaviour (the headless daemon skips the primary read on purpose and uses the mirror copy), so it is not a cause of this card's symptom.

## Acceptance checklist

- [x] A rotator tick that exits abnormally shows its stderr tail in daemon.log. Evidence 2026-10-05: 5 lines with rc=0 and a non-empty stderr tail (keychain lookup timeouts) since the 3.7.0 daemon start, 0 before that release.
- [x] A rotator tick with rc != 0 shows its exit code and stderr tail in daemon.log. Evidence 2026-10-07: global-state/daemon.log.1 in the janitor plugin data dir, lines 6815 and 7443 (2026-10-05 14:41:58 and 15:56:37), 'rotator tick rc=1 stderr:' followed by the traceback tail of a ps timeout; only scripts/daemon.py _log_rotator_tick_result emits that line.
