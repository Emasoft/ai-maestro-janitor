---
trdd-id: 9PDH8G0W
title: iTerm alarm — the unconditional-negative discriminator (rescue warranted, exercised, failed)
column: complete
created: 2026-08-08T09:02:04+0200
updated: 2026-08-16T01:53:53+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
relevant-rules: []
npt: []
eht: []
---

# iTerm alarm — the unconditional-negative discriminator

## Why

Peer analysis on #92 (autonomous-agent, 2026-08-08, self-correcting its own earlier advice):
the `FIRED rearm → iterm` success line is a CONDITIONAL positive — it only fires when the
channel works AND some session actually needed rescuing. A quiet fleet produces byte-identical
silence, so the age of the last success cannot distinguish "channel dead" from "nothing to do".
The v2.8.1 downgrade handles this correctly on the positive side (recent success ⇒ downgrade;
absence ⇒ the full both-causes alarm stands, no conclusion drawn from absence) — but there is a
strictly stronger negative available that removes the confound instead of ageing around it:

> fleet scan diagnoses ≥1 instance `cron_dead` in an iTerm pane (a rescue was WARRANTED)
> AND osascript enumerated zero sessions in the same scan (the channel was EXERCISED and
> returned nothing) ⇒ the channel failed when needed — an UNCONDITIONAL negative, with no
> "quiet fleet" explanation available.

## What

- In the daemon's fleet scan (scripts/lib/fleet_scan.py / task_session_liveness): when the
  iterm-automation-blocked observation is recorded, also record whether the SAME scan carried
  a `cron_dead` diagnosis for an instance whose terminal resolution required iTerm.
- Extend the flag payload (`iterm_automation_payload`) with that fact (e.g.
  `rescue_warranted: true/false`), compare-and-write as today.
- In `_phase_iterm_automation_alarm`: when the payload carries `rescue_warranted`, state the
  unconditional negative explicitly ("a rescue was needed this scan and the channel returned
  nothing — this is a hard failure, not ambiguity") — this outranks the FIRED-rearm downgrade
  (a hard failure NOW beats a success hours ago; keep the honest-interval wording from #92:
  a success at T + failures after T exclude only a denial spanning T).
- Tests: payload round-trip; alarm precedence (unconditional negative > rearm downgrade >
  base both-causes text); absence of the field keeps current behavior byte-identical.

## Acceptance

- [x] Payload extension with compare-and-write stability (no ack churn from the new field)
- [x] Alarm precedence pinned by tests (hard-negative > downgrade > base)
- [x] The hard-negative text names both facts (warranted + zero enumeration) and drops the
      System-Settings remedy only if that remains honest (it does not — keep remedy, drop
      the "cannot tell you why" ambiguity clause instead)
- [x] #92 updated when it ships — comment `#issuecomment-5304813279`, 2026-08-16. Framed as an
      UPDATE and the issue left OPEN on purpose: this card removes the diagnostic ambiguity, it
      does not touch the macOS 26 grant-persistence defect #92 is actually about. Closing #92 on
      the strength of this work would have retired a live, unsolved problem on the evidence of a
      different one.

## Notes

Source: #92 comment 2026-08-08T06:22Z ("No action requested" — carded so the idea survives;
the peer's own memory holds the corrected interval semantics).
