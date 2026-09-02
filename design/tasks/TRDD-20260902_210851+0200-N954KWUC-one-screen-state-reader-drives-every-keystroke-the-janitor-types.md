---
trdd-id: N954KWUC
title: one screen-state reader drives every keystroke the janitor types — read the pane, classify it, act on the transition, verify by re-reading
column: design
created: 2026-09-02T21:08:51+0200
updated: 2026-09-02T21:08:51+0200
current-owner: janitor-main-session
task-type: refactor
priority: critical
severity: critical
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: user
labels: [continuity, architecture, session-liveness, fleet-inject, pane-state, esc, oauth-rotator]
relevant-rules: []
blocked-by: []
npt: []
eht: [NACCL0CB, 3T9HQEQ6]
implementation-commits: []
created-by: USER directive 2026-09-02 21:07
---

# One screen-state reader drives every keystroke the janitor types

## Directive (USER, 2026-09-02 21:07, verbatim)

"Ideally the janitor script to give commands should be much smarter and should be able to
read and understand the status of the Claude Code prompt terminal and give the right command
at the right time. A janitor is supposed to control Claude Code to ensure continuity, but
without a smart script that understands the content of the screen there is no hope of a
clean and guaranteed janitor management of Claude Code."

## What the 2026-09-02 incident proved about the current shape

The daemon types into panes from **14 call sites** (`daemon.py` 11, `fleet_restart.py` 2,
`fleet_scan.py` 1), and each decides from a different PROXY for what the pane shows:

| actuator | what it reads | what it missed tonight |
|---|---|---|
| session-liveness rungs (`rearm`/`reload`/`relaunch`/ESC) | transcript staleness, `rate-limited.flag`, process table; pane text only under a stale transcript + attempt-advance | typed `/janitor-arm` behind a `Retrying in 5h` line (the queue the owner had to ESC through) |
| `_resume_wake_pass` | `rate-limited.flag` + `healthy` diagnosis | the retry wedge writes no flag, so it never saw the blocked panes |
| `_rotation_esc_pass` (new, NACCL0CB) | pane frame, anchored on the input-box chrome | — first actuator that reads the screen first |
| `model-fallback` detector | rotator verdict + one ESC + type + confirm | does not flush a queue (3T9HQEQ6) |
| stale-prompt ESC, fleet-stop | HID idle, transcript tail | — |

The transcript is a record of what the model did; the flag is a record of what a hook saw;
neither is what the human sees. The screen is. Every failure the owner reported this month
is the same shape: a proxy said one thing, the pane showed another, and the keystroke went
to the wrong state.

## Proposal

1. **`pane_state.py` — one parser, one structured state.** `read(terminal) -> PaneState | None`
   captures the frame and parses Claude Code's chrome into:
   `input_field` (empty / text / queued commands, with count), `status` ∈
   {`idle`, `working(spinner)`, `retry_wedge(attempt, total, retry_in, resets_at, scope)`,
   `awaiting_user(kind: permission | ask-user menu | model-confirm)`, `api_error`,
   `session_limit`, `compacting`, `reloading`, `unknown`}, `agents_running`, `model`,
   `context_pct`, `bypass_on`. Anchored on the chrome (input-box borders, column-0 status
   rows, the `◯`/`⏺` agent list) the way `retry_wedge_attempt_at_tail` already is. Pure,
   tested against a corpus of REAL frames captured on this host and anonymized (paths and
   account names scrubbed — PROJECT scope is pushed).
2. **One policy table, `(PaneState, event) → plan`.** Events: rotation landed, no-headroom
   verdict, cron dead, plugin staged, stop flag, stale prompt. The table is the only place
   that decides a keystroke; the 14 sites become callers of it. Rows the incident dictates:
   `retry_wedge` + rotation → ESC × (1 + queued), then resume; `retry_wedge` + no headroom →
   ESC × (1 + queued), `/model opus`, Enter, confirm; `awaiting_user` → never type;
   `working` → nothing; `idle` + cron dead → `/janitor-arm`.
3. **Closed loop: act on a transition, verify by re-reading.** After each keystroke re-read
   the pane and require the expected next state (wedge gone, field empty, menu shown) before
   the next keystroke; bounded retries; log the observed state at every step. "Fired" means
   "the screen changed the way we expected", never "osascript spawned".
4. **Presence gate moves into the policy.** Machine-wide HID idle defers only rows that
   type text into a pane whose state could be disturbed (`idle`, `working`); it never defers
   an ESC into `retry_wedge`, which has a blocked input line.
5. **Capture budget.** One osascript per pane per beat is affordable (5 panes read in ~3 s
   tonight); read every beat for panes with an open event, every N beats otherwise.

## Acceptance

- [ ] `pane_state.read` classifies every frame in the fixture corpus (incl. the 5 captured
      2026-09-02 21:03) into the intended status, with the queued-command count.
- [ ] Every `fleet_inject.fire` call site in `daemon.py` / `fleet_restart.py` goes through the
      policy table; grep shows no direct actuator that does not first read `PaneState`.
- [ ] Each policy row has a test that feeds a frame + event and asserts the exact keystroke
      sequence, and a test that a wrong post-state stops the sequence.
- [ ] Live: a rotation and a no-headroom fallback each end with the pane back at `idle` or
      `working` with no human keystroke, logged step by step.

## Approval log

## Notes and lessons learned
