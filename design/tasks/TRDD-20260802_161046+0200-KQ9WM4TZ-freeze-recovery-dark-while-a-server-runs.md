---
trdd-id: KQ9WM4TZ
title: Standalone sessions have no freeze recovery while an ai-maestro server runs
column: human_review
pre-block-column: testing
created: 2026-08-02T16:10:46+0200
updated: 2026-08-06T08:40:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
parent-trdd: 5ZVS1DDP
blocked-by: []
relevant-rules: []
implementation-commits: [ac419694]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

### 2026-08-06 08:40 — ai_review PASSED → `human_review` (the user's queue; awaiting their verdict)

Reviewed against the recorded focus, adversarially, on fresh read of the shipped code:
- **1h dedupe vs 600s pacing — correct as designed.** Steady healthy state: every session
  records `daemon-owns-it`, dedupe holds, ~1 write/hour machine-wide. Dark window: outcomes
  genuinely alternate across sessions (`paced` ↔ `no-peers`/`ran`/`lock-held`), each flip
  rewrites — MORE granularity exactly when it matters, bounded by heartbeat cadence.
- **`no-peers` log line — rejected.** The breadcrumb already records `no-peers` with its
  epoch in the ONE machine-wide place an investigator will look; a per-project log line
  would duplicate the fact into whichever project happened to win the flock.
- **Cross-session read-then-write race — safe by construction.** `atomic_write` per writer,
  last-writer-wins on a single short line; worst case is one redundant write. Clock skew
  (now < prev_ts) degrades to dedupe-holds, never a crash (int/ValueError caught).

USER: to close this card, bless the breadcrumb design (or ask for changes) — everything
else on it is done and committed (`ac419694`).

### 2026-08-06 08:25 — decision taken: breadcrumb SHIPPED, evidence accepted, `testing → ai_review`

The NEXT ACTION below offered accept-as-is vs add-a-quiet-gate-trace; both are now done.
`record_outcome` in the detector (commit `ac419694`) writes `<epoch> <outcome>` to
`global-state/peer-recovery.outcome` on EVERY beat — quiet gates included — deduped to one
small write per hour machine-wide (change-or-stale-only rewrite, the ZNN0UK5K sensitivity),
flipping instantly when a dark window opens. 11/11 detector tests pass. Testing evidence =
the one proven gate-clean dark-window beat (stamp 2026-08-05 18:33:45, below) + the gate-order
code review + the new trace for any future window. Review focus for `ai_review`: the dedupe
window (1h) vs the 600 s beat pacing, and whether `no-peers` after a stamped beat deserves
its own log line.

### 2026-08-06 morning — the observation LANDED, one gate-clean dark-window beat PROVEN; plus an observability caveat the criterion missed

Measured (not inferred) this morning:
- `global-state/peer-recovery.last-run.ts` content = `1785947625` → **2026-08-05 18:33:45+0200 —
  exactly inside yesterday's daemon eviction-loop dark window** (TRDD-DB1P25S4: the daemon was
  being SIGTERM'd every ~60-75 s, so daemon-dark + server-alive held repeatedly). The stamp sits
  AFTER the daemon-alive, server-alive, pacing and flock gates in `run_once`, so its existence is
  proof of ONE fully gate-clean beat that also won the cross-session lock.
- No `peer-freeze-recovery.log` exists in any scanned project. That is CONSISTENT, not missing
  data: after the stamp, the only SILENT outcome is `no-peers` — every louder outcome
  (`ran`/`scan-failed`/`beat-failed`) logs. So the beat ran, scanned, and found no recoverable
  peer (plausible: mid-ping-pong, panes were healthy; only the daemon was flapping).
- **Observability caveat the 300s-window criterion missed:** the quiet gates (`daemon-owns-it`,
  `paced`, `lock-held`, `no-server`) return with NO artifact — no stamp advance, no log line. With
  the daemon healthy again (TRDD-DB1P25S4 fix `75332ba0` ended the eviction loop), every beat now
  exits `daemon-owns-it` invisibly BY DESIGN. "Observe beats across a few 300 s windows" is
  therefore only satisfiable DURING a genuine dark window, and those are now rare precisely
  because the daemon was fixed. NEXT ACTION: accept the single proven gate-clean beat + the
  gate-order code review as the testing evidence, OR (better, small) add a heartbeat-log line /
  counter for the quiet-gate outcomes so a future dark window leaves a countable trace — decide,
  then move `testing → ai_review`. Do NOT wait for more dark windows; that is waiting for an
  event the daemon fix now prevents.

### 2026-08-05 evening — UNBLOCKED: the publish landed and the stopgap has now RUN. `blocked → testing`.

Every fact the block rested on flipped today, each re-verified rather than assumed:
- v2.4.0 + v2.4.1 published; the cache holds 2.4.1, which SHIPS
  `scripts/detectors/peer-freeze-recovery.py` (checked in the cache dir, not inferred).
- `last-run-peer-freeze-recovery.ts` EXISTS — the exact stamp whose absence this card used as
  proof the roster never reached it. The auto-rolling stub is resolving 2.4.1.
- Independently, the daemon now stays up beside a live server covering the unclaimed chores
  including `session-liveness` (88e6f45a, verified live — see TRDD-5ZVS1DDP), so freeze recovery
  has BOTH a per-session and a daemon path where it briefly had neither.

REMAINS before `complete` (why this is `testing`, not closed): observe the detector actually
RECOVER something, or at minimum fire its gated beat cleanly across a few 300 s windows
(`.janitor/logs/peer-freeze-recovery.log` is still absent — stamp proves reached, not exercised).

### The blocked entry (kept; superseded above)

### 🚫 2026-08-05 — BLOCKED, and the old NEXT ACTION was UNACHIEVABLE

**The stopgap has never executed once, and it cannot until a publish lands. Measured today:**

- `.janitor/logs/peer-freeze-recovery.log` — **does not exist**. No `last-run-peer-freeze-recovery.ts`
  stamp either, and `_run_detector` stamps unconditionally, so the roster has never reached it.
- The dark window it exists for has been live for days (server alive, `daemon_pid()` → None).
  It should have fired every 300 s.
- **Cause:** the heartbeat runs the *cached* plugin (the auto-rolling stub resolves the newest
  cached version), and **NO cached version ships this detector** — checked all 19, `0.41.0`
  through `2.3.0`: zero have `scripts/detectors/peer-freeze-recovery.py`, zero have the roster
  entry. The code exists only in the working tree.
- **HEAD is 193 commits ahead of the `v2.3.0` tag.** The publish is blocked (TRDD-AWXK0RFT), so
  every fix in those 193 commits is inert on this machine — including this one.

**So the previous NEXT ACTION — "observe ONE real dark-window firing on this host" — could
never have been satisfied, no matter how long the card waited in `testing`.** It was not
waiting for an event; it was waiting for an event that nothing could produce. That is the
distinction between `testing` and `blocked`, and this card was in the wrong one for 3 days.

**`blocked-by: [AWXK0RFT]`** (the CPV false-positive that blocks publish), `pre-block-column:
testing` — restore to `testing` the moment a release ships, then take the observation.

**The gap this card names is therefore STILL 100% OPEN**, not mitigated. The body below
describes a stopgap that is written but not running anywhere.

### 2026-08-05 — the gap is WIDER than this card assumed

This card says the daemon owned "freeze recovery (`session-liveness` / `fleet-stop`) — the ONE
chore that structurally cannot move to a per-repo cron". True of the structural argument, but
the *inventory* was incomplete. The daemon owns **eleven** chores; the server absorbs **five**;
**six** are unowned while a server runs — `session-liveness` and `fleet-stop` are only two of
them. The other four (`memory-guard`, `cache-prune`, `rules-cleanup`, `github-config-audit`)
have no stopgap at all and are not in this card's scope.

Measured on this host: all eleven stamps 10-14 days stale. Filed upstream as
**Emasoft/ai-maestro#111** (absorb all eleven and write the
`~/.claude/janitor-control/<task>.last-run.ts` stamps, or narrow the daemon suppression to what
is actually claimed) — the janitor cannot close that from its side. A `global-chore-blackout`
detector now alarms on the condition (commit `95f26646`) — and is itself inert until publish,
for the same reason as above.

---

**STOPGAP IMPLEMENTED 2026-08-02 (branch 3 of the NEXT ACTION — #79 silent for 12 days;
the last comment on the thread is our own measurement, no owner/server reply).**
**SUPERSEDED — do NOT carry forward:** the line that read *"Column `testing` — awaiting one
real dark-window firing"*. See the 2026-08-05 block above: the column is now `blocked` and the
firing was impossible.

### What shipped

`scripts/detectors/peer-freeze-recovery.py` + roster entry (300s) + `_NON_HARNESS_DETECTORS` +
3 plugin.json knobs (`peer_recovery_enabled`/`_interval`/`_interval_s`). Design:

- **Reuses the daemon's beat VERBATIM** — `daemon.task_session_liveness(fleet=peers)` (the
  parameter existed for tests; now it is the handoff surface). Diagnosis ladder, typing gate,
  per-instance cooldowns, identity-stamped budgets, F3 audit, crash-loop alert: all unchanged,
  and the budgets live in the SAME global-state recovery dir, so a respawned daemon later
  CONTINUES the counters.
- **Runs ONLY in the dark window**: daemon dead AND server alive. Daemon alive → its beat owns
  it. Server dead → `ensure_daemon_running` on the ordinary path is the remedy (its crash-loop
  breaker must not be bypassed here).
- **Not a second daemon**: nothing resident — a bounded one-shot under a machine-wide
  non-blocking flock + a stamp-FIRST last-run (even a crashing scan paces the fleet).
- **Never recovers its own session** (`project_root == self` filtered): self-typing mid-turn is
  the splice hazard TRDD-0BVF4K7E closed, and this cron is provably alive — it just fired.
- notify.py's DAEMON-ONLY rule: honored in spirit — inside the flock there is exactly one
  writer and no daemon; the crash-loop alert would otherwise be dark with the rest.

8 behavior tests (gates, peer filtering, machine-wide pacing incl. stamp-first, roster +
deny-list). **NEXT ACTION:** observe ONE real dark-window firing on this host (server up,
daemon down): `.janitor/logs/peer-freeze-recovery.log` shows `ran the dark-window recovery
beat`, and the F3 recovery audit gains records. Then `complete` — and 5ZVS1DDP's EHT clears.
If #79 later confirms server-side takeover, this detector self-neutralizes (its gate sees the
server, but recovery competes nowhere — the beat only touches sessions the server does NOT
own, which `fleet_scan` already marks server_owned ⇒ HANDS OFF).

**The gap is LIVE on this host as of 2026-08-02 16:10.** Not a hypothetical.

### What is dark, and why

TRDD-5ZVS1DDP made the janitor daemon EXIT while an ai-maestro server is running (one daemon
per host — the owner's unconditional ruling: two daemons "will conflict and write at the same
time in the same files, corrupting them"). That is correct and verified in production.

But the daemon owned **freeze recovery** (`session-liveness` / `fleet-stop`) — the ONE chore
that **structurally cannot** move to a per-repo cron, because a frozen session's own cron is
exactly what has stopped. A session cannot recover itself. So while a server runs:

- the daemon is gone (verified: **0 janitor daemons**, `daemon_pid()` → None, heartbeat 36.5 h
  stale), and
- standalone `#N` sessions have **no freeze recovery at all** — silently.

Measured now: server pid **95175** (`~/ai-maestro/node_modules/tsx`), up **3 days**, liveness
probe 24.8 s fresh. So this machine has been without standalone freeze recovery for ~3 days.

**Why it is HIGH and not medium:** the failure is invisible from every surface. A frozen
session looks identical to a busy one, the daemon's absence is the *correct* documented
behaviour, and no detector reports "the recovery chore has no owner". It is the silent-disable
shape this project treats as a defect class — the same shape as the 14-day `keep-going-off`
sentinel and the `USER_PRESENT` cancel.

### The ask that is outstanding

ai-maestro **#79 item 1** — asked 2026-07-21, no confirmation recorded since. The question:
does the SERVER take over freeze recovery for standalone sessions while it runs?

### NEXT ACTION

1. **Check #79 for a reply first** (`gh issue view 79 --repo <ai-maestro>`). Do not re-ask; a
   duplicate ask is how this sat 12 days.
2. If they **confirm** → verify the server actually does it (do not take the claim on trust —
   freeze a scratch session and observe), then close this EHT.
3. If they **decline or stay silent** → build the stopgap here, per 5ZVS1DDP's own instruction:
   *"If they decline, keep a stopgap here rather than let it dark."* Shape to decide then; the
   constraint is that it must NOT resurrect a second daemon (that is the corruption 5ZVS1DDP
   exists to prevent). A per-repo cron cannot do it for its OWN session, but it CAN do it for a
   PEER session — mutual recovery across sessions is the obvious candidate and needs its own
   design pass.

**Do NOT "fix" this by making the daemon stay alive.** That reverts 5ZVS1DDP and reintroduces
the two-daemon corruption the owner ruled out unconditionally.

## Provenance

Split out of TRDD-5ZVS1DDP on 2026-08-02 while closing that card's soak condition. I had moved
5ZVS1DDP to `complete` on the strength of the soak alone and reverted it in the same session —
the soak was condition 1 of 3, and this was condition 2, eight lines below it. Filed as its own
card because it is a distinct atomic task with a different owner and a different trigger, and
because leaving it as a bullet inside a card being closed is precisely how it would have gone
dark permanently.
