---
trdd-id: G9Z8PXCM
title: Session beacon mirrors the live token so the daemon can probe usage
column: todo
status: tasked
created: 2026-10-03T03:41:14+0200
updated: 2026-10-03T03:44:29+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:14+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
derived: true
---

# Session beacon mirrors the live token so the daemon can probe usage

### R2 — the beacon mirrors the live token (`rotator.py` HEAD `refresh_beacon_if_stale` ~1097, `_live_backup_write` ~926)
1. After a successful primary read in the session context, write the same blob to `-livebak`. The daemon's existing `b_fp == mirror_fp` branch then probes `/api/oauth/usage` (read-only) with the real live token.
2. Call it from the Stop hook too (`hooks/on-stop-token-meter.py`, mtime-gated by the existing staleness check). Today it runs only from the 300 s detector on idle heartbeat fires, so a busy session leaves the daemon blind.
3. **Before the first production write**:
   - Inspect the real `-livebak` item's ACL with an attribute-only lookup (no `-w`).
   - Make the first write with `may_prompt=False` and stop after one failure.
   - The update path emits no ACL flag (measure-verify 8a). V5RXQ4NB and ATOM-HDUR-IWRS are the known prompt risks.
- **Test** (isolated real-keychain fixture, no mocks):
  1. Seed the primary with L1 and `-livebak` with L0.
  2. Run `refresh_beacon_if_stale()` with HEADLESS unset; assert `-livebak` holds L1's fingerprint.
  3. With `HEADLESS=1`, assert `_resolve_untrusted_live` returns L1 and the isolated `rotator.log` has no "no usable slot twin". Fails before.
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
