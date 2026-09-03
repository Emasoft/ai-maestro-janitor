---
trdd-id: NACCL0CB
title: the typing gate defers the ESC that unblocks a rate-limited pane for as long as the human is watching it
column: testing
created: 2026-09-02T20:49:27+0200
updated: 2026-09-03T23:12:50+0200
current-owner: janitor-main-session
task-type: bugfix
priority: critical
severity: critical
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: user
labels: [continuity, session-liveness, typing-gate, retry-wedge, oauth-rotator, esc]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: [625d7809]
supersedes-directive: 2026-07-18 typing gate (TRDD-6Q0OYYYH) for the retry-wedge ESC class only
---

# The typing gate defers the ESC that unblocks a rate-limited pane for as long as the human is watching it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:09:13+0200

**Board reconciliation (2026-09-03 11:09):** boxes 1, 3, 4 ticked (live evidence + tests
re-verified this pass). Box 2 stays open — no test covers the `WEDGED … deferred` pending-list
log line at `daemon.py:1548-1554`; write one before closing this card.

## ⏵ PRIOR STATE — 2026-09-02 21:12

- **USER ruled 2026-09-02 ~21:00** (verbatim intent): the HID gate cannot tell typing in
  another session from typing in the blocked one, so "remove the typing gate entirely, or
  make an exception injecting the ESC key anyway … or even better, the very moment you
  switch/rotate the account, inject ESC to all claude code instances with the red error."
  The owner was NOT at the blocked session's keyboard; the machine-wide HID reading came from
  another Claude Code session.
- **Review-fork finding (settled, changed the design):** the typing gate was NOT the only
  thing between the panes and an ESC. `fleet` is built before the gate, so diagnoses ran
  every beat — and the daemon has produced **0 `retry_wedged` diagnoses in its whole logged
  history**, because `retry_wedge_state_update` confirms only when the attempt number
  ADVANCES across polls, and a weekly-window wall reads `Retrying in 5h … attempt 1/5` for
  five hours. Plus the diagnosis needs a transcript stale ≥ 15 min. Splitting the gate alone
  would have shipped a no-op. Claim 1 of the incident section is therefore "never logged or
  acted on", not "would have been diagnosed".
- **Shipped in `625d7809` (76 tests green, incl. 10 new in `tests/test_daemon_rotation_esc.py`):**
  `daemon._rotation_esc_pass` runs BEFORE the typing gate: within `_ROTATION_WAKE_WINDOW_S`
  (600 s) of `rotation-success.ts` it reads each live pane NOW, keys on the wedge signature
  in the frame's bottom 12 rows (`session_liveness.retry_wedge_attempt_at_tail`, no
  attempt-advance, no stale-transcript precondition), writes `rate-limited.flag` and fires
  ONE ESC per pane per rotation epoch (`daemon-rotation-esc.ts`). unarmed/server_owned/dead
  and awaiting-user panes stay hands-off. The typing-gate deferral line now names the
  non-healthy diagnoses it defers.
- **Deliberately NOT done here (own cards):** (a) the beat-path `retry_wedged` confirmation
  for long backoffs (attempt never advances) — without a rotation the ESC would only make
  Claude Code re-hit the same wall; (b) the no-headroom fallback the USER added at 21:05:
  multiple ESC until the queue is clean, then `/model opus` + Enter — TRDD-3T9HQEQ6.
- **Guard shape after two review passes (`fb4ae704`, + glyph rule):** the wedge counts only as
  Claude Code's OWN status row — inside the 8 rows above the input box's upper border AND
  starting with a spinner glyph (`✻✽✶✢✳·`). Measured on five real frames: an indented
  assistant quote and a column-0 past-prompt echo (`❯ …`, the owner typed the red line
  tonight) are both rejected; the session-limit and 429 variants share the row and pass.
- **Without a rotation, a wedged `cron_dead` pane now declines its rearm every beat**
  (`retry_wedge_on_screen`), and `_decline` spends an attempt, so the 4-attempt budget walks
  to GIVING UP + one human page in ~8 min. Deliberate: with no rotation there is no
  headroom to resume onto, so a human (or TRDD-3T9HQEQ6's `/model opus` flush) IS the
  next step — the page names the pane instead of the daemon typing into it.
- **21:40 — SHIPPED AND LIVE IN THE DAEMON.** v3.4.12 (`2f5883f2`) CI green on all five runs;
  installed at user scope; the daemon restaged itself at 21:28:04 (`os-keepalive: newer
  version staged → exit for respawn`, `version-update: certified last-good=3.4.12`) and the
  DATA copy carries `_rotation_esc_pass` and `retry_wedge_attempt_at_tail`. Two follow-up
  commits await the next patch: `4a4b857f` (join a wrapped status row) and `d3dde9f9` (`·` is
  not a join-stopper) — both only matter on panes narrower than ~72 columns; every pane on
  this host is 204 wide.
- **NEXT ACTION:** the live box — the next rotation on this host must log
  `rotation-esc: FIRED ESC` within one beat of `rotation-success.ts`; then `published`.

## Incident (2026-09-02, 20:38 to 20:47, this host)

Every Claude Code session on the machine sat on the red line
`✻ Fable limit reached · Retrying in 5h (Sep 8 at 5pm) · attempt 1/5` until the owner rotated
by hand and logged into an account with Fable headroom. The owner's verdict: "the reason of
existence of the janitor is to ensure continuity, and yet it fails every time".

Verified in the artifacts, in this order:

1. `session_liveness._RETRY_WEDGE_RE` (`scripts/lib/session_liveness.py:42`) MATCHES that exact
   line (tested). Detection is not the gap.
2. The rotator rotated twice: 20:38:45 ipazia→fmuaddib (5h burn), 20:39:50 fmuaddib→emanuele
   (`SCOPED[7d/Fable=100%]`). `global-state/rotation-success.ts` was stamped 20:39:50. Rotation
   is not the gap.
3. `daemon.py:1394-1401` (the TYPING GATE, owner directive 2026-07-18 via TRDD-6Q0OYYYH,
   `USER_PRESENT_IDLE_S = 20`): any HID event in the last 20 s makes the WHOLE session-liveness
   beat `return` BEFORE the per-session loop. From 20:33 to 20:45 every beat logged
   `session-liveness: user typing (HID idle Ns) — recovery injections deferred this beat`. The
   human was at the keyboard precisely because they were staring at the wall. No pane was
   diagnosed, so no ESC could fire, and Claude Code's own retry was 5 h away.
4. Day tally across `daemon.log` + `daemon.log.1`: 170 deferrals, 0 `retry_wedged` diagnoses,
   0 ESC fires. The only recovery this daemon has ever fired is `rearm` for a dead cron.
   TRDD-UA4FAX67 (post-rotation ESC) has sat `blocked: [awaiting-live-429-observation]` since
   2026-08-13; tonight WAS that observation, and the gate made it invisible.

## Root cause (architectural, not a regex)

Every recovery injection is gated on "human absent". By construction the janitor never acts
while the owner watches, and the owner only ever judges it while watching. The 2026-08-11
directive ("no session may sit blocked — any blocking error or askuser prompt is answered with
the default option or escaped", quoted at `daemon.py:1576`) contradicts the 2026-07-18 gate,
and the 07-18 gate wins in code because it runs first and returns.

The 07-18 concern was real: a human watching a pane get TYPED INTO while they work is a
disturbance, and typing `/janitor-arm` into an approval dialog (2026-07-17) answered for the
human. Neither concern applies to an ESC into a RETRY-WEDGED pane: that pane's input is
blocked by Claude Code's retry watchdog (`fleet_recovery.py:53`), so the ESC cannot land under
anyone's fingers and cannot choose anything; it can only release the retry.

## Proposal (needs USER ruling: it narrows the 2026-07-18 directive)

1. **Split the typing gate by injection class.** Compute each session's diagnosis BEFORE the
   gate. The gate keeps deferring typed commands (`rearm`, `/reload-plugins`, stop) and the
   stale-prompt dismiss ESC (that one CAN discard a pending human decision). It does NOT defer
   the `retry_wedged` ESC: input is blocked there, so presence is irrelevant.
2. **Log the diagnosis every beat, deferred or not.** A deferred wedge must be visible as
   `WEDGED (deferred: user typing)`, never silent. Tonight's 12 minutes left no trace of the
   thing that mattered.
3. **Rotation-triggered ESC.** `rotation-success.ts` younger than the rotation window plus any
   `retry_wedged` pane ⇒ ESC now, regardless of the gate (this is UA4FAX67's mechanism, finally
   unblocked by a live observation).
4. Optional, larger: gate per FOCUSED iTerm session (iTerm API) instead of machine-wide HID
   idle, so a human typing in a shell does not freeze recovery of every other pane.

## Acceptance

- [x] A unit test feeds a `retry_wedged` fleet entry with HID idle 0 s and asserts the ESC plan
      is built; a `cron_dead` entry under the same reading is deferred.
      — proven by tests/test_daemon_rotation_esc.py::test_a_fresh_rotation_escs_the_wedged_pane_even_while_the_owner_types
      + tests/test_daemon_rotation_esc.py::test_a_soft_command_is_never_typed_into_a_pane_showing_the_retry_line (2026-09-03)
- [x] A unit test asserts the beat logs `WEDGED … deferred` when gated (no silent return). —
      PROVEN by `tests/test_daemon_rotation_esc.py::test_the_typing_gate_defers_the_whole_beat_and_logs_who_it_deferred`,
      which drives the real `daemon.task_session_liveness()` with `hid_idle=0.0` and asserts BOTH
      `fired == []` and the `user typing (HID idle` line with its `; deferred: proj:cron_dead` tail.
      The tail is the load-bearing half: without it a silent return and a logged deferral are
      indistinguishable. The line lives at `daemon.py:1578-1579` — the box's original `1548-1554`
      citation had drifted, and the first attempt at this box pinned the WRONG line
      (`daemon.py:1866`'s `WEDGED (n queued …)`, the wedge deferral, not the typing gate). That
      other line was genuinely untested too, so its test was kept as
      `::test_a_wedged_target_with_queued_commands_is_deferred_not_typed_into` (TRDD-8DR0X08A F2)
      asserts this line/the `pending` list — a genuine missing test (write one asserting the log
      line names a non-healthy diagnosis while HID idle ≤ 20s).
- [x] Live: the next model-scoped wall on this host ends with an ESC in `daemon.log` within one
      beat of `rotation-success.ts`, no human keystroke. — proven twice, no human keystroke:
      `daemon.log.1:9518-9522` (2026-09-02T22:17:55, ai-maestro-janitor + 4 more panes) and
      `daemon.log:695-698` (2026-09-03T04:10:24, AgentlensPro), both paired with an
      `oauth-rotator-tick`/`rotator.log` rotation in the same second-window (2026-09-03).
- [x] TRDD-UA4FAX67 unblocked and cross-linked. — UA4FAX67 was unblocked on this card's box-3
      evidence (its `pre-block-column: testing`, box 1) and is now `blocked-by: [TRDD-N954KWUC]`
      for its own box 3 (needs N954KWUC's closed-loop ESC adapter to log the post-ESC pane
      frame) — cross-linked, not still stuck on this card (2026-09-03).

## Approval log

- 2026-09-02T21:12:00+0200 — APPROVED by USER (min-approval-requirement: user), in-session
  ruling on the incident report: exempt the ESC from the typing gate and, better, ESC every
  pane showing the red line the moment the account rotates. Promoted proposal → tasks;
  implemented the same session (`625d7809`), so it enters at `testing`, gated on the 3.4.12
  release + one live rotation.
