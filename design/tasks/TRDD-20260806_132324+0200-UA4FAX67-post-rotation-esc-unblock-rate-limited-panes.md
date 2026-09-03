---
trdd-id: UA4FAX67
title: A successful account rotation leaves the rate-limited pane BLOCKED — nobody types the ESC that lets it continue
column: todo
blocked-by: []
created: 2026-08-06T13:23:24+0200
updated: 2026-09-03T10:05:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: [f3f664de, 624c63a4]
---

# Post-rotation ESC unblock (owner failure report 2026-08-06, item 4)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

### 2026-08-12 — THE TRIGGER IS BLACKED OUT ON A SERVER-OWNED HOST. `testing → todo`

The mechanism below is correctly built and correctly tested, and **on this machine it can
never fire**. Verified in this order, each step from the artifact rather than by inference:

1. `global-state/rotation-success.ts` is **absent** — from BOTH the canonical
   `plugins/data/.../global-state/` and the legacy `~/.claude/janitor-global-state/`.
2. That absence is proof it was never written, not that it aged out: `_ROTATION_SUCCESS_NAME`
   appears in exactly three places in the whole tree — the constant, one WRITE (`global_state.py:977`)
   and one READ (`:990`). **Nothing deletes it.** The "evidence expires" design in this STATE
   block is a staleness comparison in the CONSUMER, not a file deletion.
3. The only writer of the stamp is `rotator._switch_blob` (`rotator.py:1516`) — OUR rotator's
   switch path.
4. A rotation demonstrably happened (2026-08-11 10:00:13, 3 accounts — recorded and verified
   on TRDD-G4BCRUP7).
5. On this host `harness_backend.server_is_alive() == True`, `server_runs_chores() == True`,
   and `claimed_chores()` includes **`oauth-rotator-tick`**.

So the ai-maestro server performed that rotation, and the server does not write our
breadcrumb. **The causal link is dead exactly where rotation actually happens.** A perfect
rotation still ends with a human pressing a key — the precise failure this card exists to fix.

**This is the same blackout shape as TRDD-G4BCRUP7's R3** (fleet-plugins-update has no owner
on a server host): a feature whose trigger the janitor owns, on a host where the janitor no
longer performs the triggering act. Worth naming as a class, because it will recur for every
chore the server claims — **the daemon standing down transfers the ACT but not the
BREADCRUMB, and nothing notices, because the breadcrumb's absence looks exactly like "no
rotation happened".**

### 2026-08-13 — (a) IS DONE, and reviewing it found a fail-OPEN hole in its own gate

**Option (a) shipped and is in the tree**, at the one place that already computes the signal:
`rotator.refresh_beacon_if_stale` compares the live-identity beacon before/after a re-stamp, and
on a real change now calls `gs.record_rotation_success(...)` — the same breadcrumb the daemon
already consumes. No new evidence type, no new consumer, no cross-repo dependency, and it fires
whoever rotated, which is the whole point on a server-owned host. Verified live on this machine:
the beacon exists, carries an email + fp, and is 0.2 h old (the 300 s `oauth-beacon-refresh`
detector maintains it, and it IS in the roster and enabled).

**Reviewing it found a real defect (fixed, `624c63a4`).** The gate read `old != new`, and BOTH
sides can be None without meaning "changed":
  - `read_live_identity_beacon` returns None when the beacon has never been written AND when it
    is older than the 24 h window — so `old` is None on a machine's first stamp and on the first
    stamp after an idle day, and `None != "a@x"` is true. **Reproduced**: the log line reads
    `beacon: live account changed (unknown) -> a@x` and the rotation stamp lands, so the daemon
    would type into panes with no rotation behind it.
  - `new` is None when the email ladder ends at an unreachable `/roles` — a degraded READ.
Both sides must now be KNOWN. The comment above the gate had claimed it "cannot fire without an
observed change of live account"; the claim was the give-away, since an absent observation is not
an observation.

**NEXT ACTION:** the remaining acceptance box is one LIVE observation (429 → rotate → the pane
continues with no human keystroke). That cannot be manufactured honestly — it needs a real rate
limit — so this card waits for one rather than being closed on the strength of its tests, which
is what its own STATE block already warned against.

**(b) remains open and remains optional:** asking ai-maestro to stamp the breadcrumb is still
correct in principle, but (a) removed the dependency, so it is no longer on this card's path.

**Do NOT close this card on the strength of its tests.** They pass, they are falsified, and
they prove the wiring — between two ends that are not connected on the host that matters.

### 2026-08-13 — `todo → blocked`. The card was claiming workable and is not.

Both remaining boxes are outside anyone's effort right now: box 1 needs a REAL 429 (the STATE
above already refuses to manufacture one), and box 2 is an upstream filing sitting in the
user's GitHub-reply gate. Nothing here can be pulled and worked, so leaving it in `todo` made
the board overstate its available work — the failure `the-kanban-is-a-pipeline-that-must-drain`
names: a column that asserts activity nobody is providing.

`blocked-by: [awaiting-live-429-observation]` is deliberately an EVENT, not a card id. The rule
wants a blocker that is true and greppable; inventing a placeholder card so the field could
name one would be ceremony, and would hide that the blocker is the physical world rather than
another task. `pre-block-column: todo` restores it the moment the observation lands.

**This is a park, not an abandonment.** The code is shipped (`f3f664de`, `624c63a4`) and live;
what remains is confirmation. If a 429 occurs and the pane continues untouched, box 1 closes on
the spot.

---

## Superseded STATE (2026-08-06) — the build, still accurate as a description of the code

**Tasks 1 and 2 are DONE (`f3f664de`); task 3 is preserved and pinned by a test; task 4 is
not ours. `todo → testing` — what remains is one live observation.**

**The link (task 1).** `rotator._switch_blob` stamps `global-state/rotation-success.ts`;
`daemon.task_session_liveness` consumes it. A breadcrumb rather than a direct call, so the
rotator stays free of fleet-scan/injection machinery and the trigger works whoever rotated —
the daemon bulk lane, a manual `rotator.py switch`, or a future caller.

**The default decision (task 2), which was the real question on this card.** The PERIODIC
wake pass stays **default-OFF**; a rotation **overrides** it inside a 600s window.

The two are not the same kind of thing. The periodic sweep fires on a timer with *no*
evidence the limit has lifted, so most of its injects would be typed at a wall that is still
standing — that is why it shipped dormant and why it stays dormant. A rotation is positive,
causal, freshly-timestamped evidence that the specific thing blocking those panes was just
removed. Defaulting the whole sweep ON to catch that case would have bought the reported
failure a fix at the price of a machine-wide timer typing into panes; this buys the same fix
with a trigger that cannot fire without a cause.

Evidence is **fail-CLOSED** (absent / unreadable / future-dated ⇒ no wake) because the gate
types into the user's pane, and it **expires**, because a stamp that never went stale would
quietly convert the default-OFF pass into always-on for the daemon's life.

**Task 3 (P7WU40G9) survives, and is pinned:** frozen panes stay ESC-only esc_nudge — a typed
command buffers on a frozen input line and floods — and a test asserts the new trigger is not
a back door around it.

**NEXT ACTION:** the live observation — a real 429 → rotate → pane continues with no
keystroke. Needs a genuine rate-limit window, so it cannot be manufactured; the wiring is
proven by tests + falsification, not by that event.

**NOT OURS:** the harness half. The aimaestro CLI channel has no raw-ESC primitive
(write-only `session command`), filed as ai-maestro#110. Harness panes are `server_owned` and
this daemon never touches them (janitor#100 split). Do NOT build a call-in.

## WHY

The rotator can swap the live credential perfectly and the blocked session STILL sits at
the rate-limit UI — the account is fixed, the pane is not. The owner's requirement: after
a successful rotation, type ESC (python/osascript for iTerm, the server-side script path
for ai-maestro harness agents) into the affected pane(s) so work continues unattended.

## What EXISTS vs what fails (verified 2026-08-06)

- `fleet_inject.build_esc_plan` (esc_nudge, TRDD-P7WU40G9) — the flood-safe ESC-only
  injection — exists and is the recovery for `frozen` (stale + rate-limited.flag).
- BUT the daemon's rate-limit WAKE pass ships DORMANT:
  `daemon.py::_phase (task_session_liveness MF1 wake)` gates on
  `_RATELIMIT_WAKE_ENABLED_ENV` with default **False** — so by default nothing wakes a
  rate-limited pane even when the daemon is healthy.
- AND there is no rotation→unblock LINK: the rotator (daemon bulk lane) does not, on a
  successful switch, trigger the esc_nudge/wake sweep for panes holding
  `rate-limited.flag`. The two mechanisms never talk.
- AND yesterday's daemon eviction ping-pong (fixed 75332ba0, UNPUBLISHED) kept the only
  actuator dead during the exact windows rotations happened.
- Harness agents: the aimaestro CLI channel has NO raw-ESC primitive (write-only
  `session command`) — filed upstream as ai-maestro#110; until it lands, harness panes
  are the server's to unblock (janitor#100 split).

## The task

1. Wire rotation-success → immediate targeted wake: after `cmd_switch`/`cmd_auto`
   lands a new live credential, run the esc_nudge sweep over instances holding a fresh
   `rate-limited.flag` (standalone panes only; server_owned stays hands-off).
2. Decide the `_RATELIMIT_WAKE_ENABLED_ENV` default (ships dormant today — the owner's
   report is an argument for default-ON with the existing MF1 disjointness guards).
3. Keep the P7WU40G9 rule: ESC-only into frozen panes, never a typed command.
4. Harness half: track ai-maestro#110; when the server exposes an interrupt, ask for
   rotation-triggered invocation (RECEIVE-model shape) — do NOT build a call-in.

## Acceptance

- [x] rotation success observably followed (≤1 beat) by a wake on rate-limited panes —
      `f3f664de`. Linked by breadcrumb (`rotation-success.ts`), not a call, so it fires for
      the daemon lane, a manual `rotator.py switch`, or any future caller.
- [x] wake-pass default decided + recorded — the periodic sweep STAYS dormant, a rotation
      OVERRIDES it. See the STATE block for the reasoning; it is written into the code too.
- [x] one live observation: 429 → rotate → pane continues with no human keystroke — proven
      twice on NACCL0CB's evidence: `daemon.log.1:9518-9522` (2026-09-02T22:17:55-58 rotation,
      22:18:01 `rotation-esc: FIRED ESC → iterm for ai-maestro-janitor`) and `daemon.log:695-698`
      (2026-09-03T04:10:24-29, matching `rotator.log.1:1172` account switch) — no human keystroke
      visible in either log
- [ ] harness gap explicitly delegated upstream (#110 cross-referenced)

## Pointers

- Today's incident: rotator state `last_switch_reason: live fmuaddib 5h=35% 7d=59%
  Fable=97% -> rotate` at 13:53; user still had to /login manually (dead fmuaddib slot
  = RENEW leg, TRDD-32acd15f / TRDD-dfc0959a capture loop — separate cards).
- Code: `scripts/lib/fleet_inject.py` (build_esc_plan), `scripts/daemon.py` (MF1 wake
  pass + `_RATELIMIT_WAKE_ENABLED_ENV`), `scripts/oauth_rotator/rotator.py`
  (cmd_auto/cmd_switch), `scripts/detectors/peer-freeze-recovery.py` (daemon-dark path).

## Approval log

- 2026-09-03T10:05:00+0200 — UNBLOCK (blocked → todo) by janitor-main-session acting for USER
  (delegation 2026-09-03 09:58). NACCL0CB's live ESC evidence (`daemon.log.1:9518-9522`,
  `daemon.log:695-698`) IS the live-429-observation this card was waiting on; box 1 closed on
  that proof. Box 2 (#110 upstream) remains open.
