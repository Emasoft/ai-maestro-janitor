---
trdd-id: G9Z8PXCM
title: Session beacon mirrors the live token so the daemon can probe usage
column: human_review
status: tasked
created: 2026-10-03T03:41:14+0200
updated: 2026-10-07T04:44:35+0200
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
implementation-commits: [415d1971]
---

# Session beacon mirrors the live token so the daemon can probe usage

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-03 remaining before complete: full uv run pytest after R4c lands; GATE before the first production write: an attribute-only look at the real -livebak keychain item's ACL (owner decision, no -w read); after release, a live-account usage line in daemon.log within one tick of an idle fire.

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
2026-10-05 — FIELD CHECK, from a worker's read of the logs, not re-read by the main agent: Not observable in daemon.log: no live-account usage line exists in the 2026-10-04T00:53 to 2026-10-05T11:07 log, and the owner ACL step on the mirror item is not recorded as done. The card stays in testing; the check could not be made: the owner ACL step is not done and the usage probes are not logged to the daemon log by a known pattern. OPEN FINDING, moved to its own card: TRDD-HVGU9OBL.
2026-10-05 — the open finding referred to above (TRDD-HVGU9OBL) is closed as explained: the headless daemon skips the primary read by design and uses the mirror copy. It is not a defect and does not bear on this card's event.
2026-10-06 FIELD CHECK NOT YET CHECKABLE: daemon.log has no usage, beacon or livebak line; rotator ticks still log 'identity untrusted, using the -livebak MIRROR'. The gate is the owner's attribute-only look at the -livebak item, not recorded as done. Source: reports/board/20261006_210400+0200-testing-field-check.md.
2026-10-07: owner decision still open; nothing changed today; no look at the -livebak item's access settings has been done, and none will be until the owner says so (the look is attribute-only and read-only).

## Approval log

- 2026-10-03T03:41:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T06:22:35+0200 — column → testing. code committed; only field acceptance after release remains
- 2026-10-06T21:08:32+0200 — column → human_review by main-agent@ai-maestro-janitor. field evidence in; waits on an owner decision or host step, see STATE

## Review notes

R2 review findings applied before commit: the beacon is trusted only when newer than last_switch_at; -livebak is written only when the primary fingerprint differs from the mirror's (no keychain write per turn); the write is update-only, may_prompt=False, 5 s timeout, session latch. Not yet verified: the real -livebak keychain item ACL (owner check pending).

## Release status

2026-10-04 — The release published today ships this card's code committed so far (415d1971). The card stays in testing because its STATE says a full uv run pytest after R4c, an attribute-only look at the real -livebak keychain item's ACL before the first production write, and a live-account usage line in daemon.log within one tick of an idle fire after release are still open.
