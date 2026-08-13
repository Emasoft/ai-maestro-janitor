---
trdd-id: EZ3PMQYX
title: iTerm alarm must branch on the daemon's launch context — launchd-spawned means the grant remedy cannot succeed
column: todo
created: 2026-08-08T10:36:31+0200
updated: 2026-08-13T12:56:00+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#92, janitor#233, janitor#235, janitor#236, janitor#237, TRDD-88ZVEQY7]
---

# iTerm alarm — distinguish error from timeout at the call site; never recommend a remedy against live success evidence

## ⏵ 2026-08-13 12:5x — THE PLUMBING LANDED; THE SURFACING DID NOT (stays `todo`)

`a0dfb901` shipped the **recording** half only: `fleet_scan` now carries `probe_outcome` and a
rearm-evidence AGE, so an `iterm-automation-blocked` observation records WHY it was reached and
how old its evidence is — the exact discriminator the revision below says the alarm is missing.
58 tests pass; ruff + mypy green.

**What is NOT done, and why the card is not closer to done than that:** the alarm TEXT still
reads the old way, because the wiring lives in `dispatch.py`, which was out of scope for that
pass. So the richer fields are written and **nobody reads them yet** — the same
recorded-but-inert shape this corpus keeps producing. Do not read `a0dfb901` as "the alarm now
distinguishes error from timeout"; it does not. NEXT ACTION: consume `probe_outcome` +
evidence-age in `dispatch.py`'s alarm line, and drop the System Settings remedy whenever recent
success evidence exists.

## ⚠ REVISED 2026-08-08 ~16:20 — the launch-context CAUSE claim is RETRACTED

The original Why below asserted a confirmed structural cause ("launchd-parented daemon cannot
receive Apple Events"). **Refuted the same day by the daemon's own log**: the launchd daemon
(pid 61025, parent 1, up since 05:03) fired MULTIPLE successful `FIRED rearm → iterm` today
(13:12, 13:14, 13:40+; 99 all-time). A systematic context barrier cannot produce those. The
webdesign peer retracted the same over-generalization on #233 first; this card repeats the
correction rather than hiding it. The honest reading: **intermittent osascript hangs/timeouts**
(plausibly load-correlated — host loadavg hit 195 today), against a grant that demonstrably
works. The 0/254-vs-56 datum (TRDD-VQ4LX7ND) described an EARLIER regime, not today's daemon.
Lesson (same one, both of us): parentage + timing correlation were correct measurements
published as a stronger conclusion than they supported.

## Why (revised)

- The alarm names two causes it cannot distinguish (denied grant vs hung osascript), and the
  reader cannot tell which they have. The v2.8.1 rearm-evidence downgrade resolves it by
  CORRELATION (a recent success), which works but is indirect and windowed.
- With success evidence on the SAME day, the System Settings remedy is wrong to recommend —
  a grant that works intermittently is not a missing grant (this part of the original card
  SURVIVES, on different grounds: the discriminator is success evidence, not parentage).

## What (revised)

1. **The primary fix — the #233 peer's call-site log line**: where the fleet scan invokes
   osascript for iTerm enumeration, log DISTINGUISHABLY "Apple Event returned an error: <err>"
   vs "call exceeded timeout (<N>s)" vs "returned empty". The flag payload carries that
   outcome (`probe_outcome: error|timeout|empty`), so the alarm can say WHICH failure this
   scan actually had instead of naming two causes it cannot tell apart — making the rearm
   correlation a corroborator instead of the only signal.
2. **Alarm text weighs evidence, not parentage**: recent success (any daemon context) ⇒ the
   v2.8.1 transient downgrade; `probe_outcome: timeout` ⇒ name the timeout + system load as
   the likely mechanism, no remedy trip; only `probe_outcome: error` with a TCC-shaped error
   AND no recent success ⇒ the grant advice. Parentage may be RECORDED as context but must
   not gate any branch (it discriminates nothing on this host).
3. **Flag carries evidence age** (#237's ask): at write time, include the age of the newest
   `FIRED rearm → iterm` line so the flag is self-contained for other consumers (the alarm's
   own 6h-window parse, shipped v2.8.1, stays authoritative).
4. Notes folded in: #235's uv-path grant-anchor fragility becomes second-order under cause (c)
   (keep the existing warning only in the `session` branch); #236's blast-radius prediction is
   PARTIALLY disconfirmed — session-side self-triggers (compact/reload typing) run
   terminal-parented in the SESSION's own context, the population #233 measured working; only
   daemon-side rescue is context-bound.

## Acceptance

- [ ] Payload round-trip + branch tests (launchd text has NO System Settings trip; session
      text unchanged)
- [ ] Flag includes rearm-evidence age; absent evidence → field absent, not 0
- [ ] The 0/254-vs-56 provenance stays cited in code comment or docstring
- [ ] **Host-type surfacing (#240 ask 2 + #235):** the alarm names how many currently-scanned
      claude instances are iTerm-hosted (the unprotected set) — fleet_scan already resolves
      per-instance terminal identity, so "unreadable" and "healthy" stop looking identical to
      a fleet-continuity reader; the launchd branch states the operational guidance plainly
      (run fleet agents under tmux — rescued with no grant, moots #92 for them, #240 ask 3)
- [ ] #233 #235 #236 #237 answered when it ships (#92 updated, #240 noted)
