---
trdd-id: EZ3PMQYX
title: iTerm alarm must branch on the daemon's launch context — launchd-spawned means the grant remedy cannot succeed
column: todo
created: 2026-08-08T10:36:31+0200
updated: 2026-08-14T17:45:10+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#92, janitor#233, janitor#235, janitor#236, janitor#237, TRDD-88ZVEQY7]
---

# iTerm alarm — distinguish error from timeout at the call site; never recommend a remedy against live success evidence

## ⏵ 2026-08-14 17:45 — THE `dispatch.py` SURFACING GAP IS PARTIALLY CLOSED (stays `todo`)

Did the narrow, well-defined half of the NEXT ACTION the 2026-08-13 entry named: `dispatch.py`'s
`_phase_iterm_automation_alarm` now reads `probe_outcome` from the flag (already plumbed by
`a0dfb901`) and, when it is `"timeout"`, prints a THIRD branch — names the timeout + system load
as the likely mechanism, and drops the Automation-grant remedy (a timeout is not a denial) —
instead of falling into the base two-cause hedge. `probe_outcome == "error"` (or empty/unset)
still falls through to the unchanged base alarm, matching "only `probe_outcome: error` … ⇒ the
grant advice" from the What section below (the base alarm already IS that grant advice; no new
branch was needed for it). Precedence, low to high: base < timeout-branch < rearm-downgrade <
TRDD-9PDH8G0W's rescue-warranted hard-negative (implemented alongside this in the same session,
sharing the same `fleet_scan` import block). Tests:
`tests/test_dispatch_phases.py::test_iterm_alarm_names_the_timeout_and_drops_the_remedy`,
`test_iterm_alarm_rescue_warranted_outranks_the_timeout_branch`,
`test_iterm_alarm_error_probe_outcome_keeps_the_base_alarm`.

**What is NOT done, and why the card stays `todo`:** the **host-type surfacing** acceptance box
(#240 ask 2 + #235 — naming how many currently-scanned claude instances are iTerm-hosted, and the
"run under tmux" operational guidance) is a SEPARATE, larger ask: `dispatch.py`'s alarm only ever
reads the flag file, it has no access to the current scan's `fleet` list, so surfacing a live count
needs new plumbing (the flag would have to carry it, written from `gather_fleet` the same way
`rescue_warranted` now is) that was out of scope for this pass — implementing it without that
design would have been exactly the "half-implement, redesign later" outcome the dispatch
instructions for this session warned against. Also not done: the `#233 #235 #236 #237` / `#92` /
`#240` GitHub replies (outside this session's scope — no `gh` calls were made). NEXT ACTION for
whoever picks this up: design the host-iTerm-count field on the flag (written from
`gather_fleet`, alongside `rescue_warranted`), then wire it into a fourth `dispatch.py` branch.

## ⏵ 2026-08-13 15:1x — THE LOAD HYPOTHESIS GAINS A MEASUREMENT, AND IT EXPLAINS THE PEERS' NULLS

janitor#92 has peer agents eliminating candidates for a `probe-failed:timeout` by measurement:
invocation shape (tty / stdin / detached — all `rc=0`, 0.37–0.46 s), self-contention (6
concurrent, 0.65 s worst), and — read from `fleet_scan.py:707-729` — the fact that the osascript
and the CLI probe are strictly SERIAL, so neither can block the other.

**Every one of those was measured on an idle machine, which is why they all come back null.**
The CHIEF-OF-STAFF says so of their own experiment: *"my experiment structurally cannot reach
the failing state."*

Measured on THIS host just now, while the fleet is busy:

```
loadavg  34.63 / 29.00 / 19.21      # severe for this machine
probe-failed events in the entire daemon log:  0
```

Two things follow. First, a 0.4 s command can plainly exceed a 15 s bound at load 34 — so the
load-correlation reading this card already recorded (the 2026-08-08 retraction, "intermittent
osascript hangs/timeouts, plausibly load-correlated — host loadavg hit 195") remains the best
surviving explanation, and it is the one candidate the peers' method cannot test, because
reproducing it requires the machine to be under load at the moment of measurement.

Second — and this is the caveat on my own datum — **this host has logged ZERO `probe-failed`
events ever**, so the timeout under discussion in #92 is not from this log. I am contributing a
mechanism that FITS, not a reproduction of their incident. Do not let it harden into "the cause
is load" on this evidence: it is an untested hypothesis that survives while the tested ones died,
which is weaker than it sounds and is exactly the distinction this card was re-written once
already for blurring.

**The falsifiable prediction, for whoever takes it:** timeouts should cluster with high loadavg
and be absent at low load. Nothing samples load at probe time today, so the correlation cannot be
checked after the fact — capturing loadavg alongside `probe_outcome` would make the next
occurrence self-diagnosing, and that is a natural extension of the plumbing below.

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
