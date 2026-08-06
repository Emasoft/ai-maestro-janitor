---
trdd-id: 6CRC9SQQ
title: Janitor-server delegation has no alignment contract — a server-claimed chore can wedge for days and neither side notices
column: dev
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T23:00:00+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# Janitor-server chore-delegation alignment contract (owner failure report 2026-08-06, item 7)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Log provenance RESOLVED — and the "contradiction" I recorded here is DISPROVED. There is no
contradiction: the daemon yields exactly as `claimed_chores()` says.** The whole thing was one
mistake — I grepped the wrong file. Item 1 is UNBLOCKED and its premise holds.

### ✔ WHICH LOG THE GLOBAL DAEMON WRITES (verified from the resolver, then from the file)

The global daemon does **not** log into any project's `.janitor/logs/`. `daemon.py:2169` runs
`os.environ.setdefault("JANITOR_LOG_DIR", str(gs.global_state_dir()))`, and `state.log_dir()`
(`state.py:166`) returns that override when present. So the daemon's log is:

```
~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log
```

Live, 9 979 lines, last written 22:51 today. It carries **9 `chore-coordination` lines**:

```
2026-08-05T20:43:07 [s:c9ae7481] yielding to active ai-maestro server: [all five]
2026-08-06T06:23:39 [s:c9ae7481] server no longer confirmed active — resuming singleton chores
2026-08-06T06:25:57 [s:c9ae7481] yielding to active ai-maestro server: [all five]
```

And since that 20:43 yield: **zero** `task '<any of the five>' starting` lines, while the chores
the daemon still owns (`fleet-stop`, `memory-guard`, `session-liveness`) run every minute. The
yield is real and it is honoured.

### ✔ `[s:...]` DOES NOT DISTINGUISH DAEMON FROM SHIM (the other wrong idea, retired)

`log_line` emits `[s:<id>]` whenever `CLAUDE_CODE_SESSION_ID` is set — and the detached daemon
INHERITS it from whichever session spawned it. `ps eww -p 30605` shows
`CLAUDE_CODE_SESSION_ID=c9ae7481…`, which is exactly the tag on its own lines. The tag means
"who spawned me", not "I am a session shim".

The 16:35:59 `version-update` line was therefore **not** the daemon: it lives in the *project*
log, tagged `[s:643908a6]` — a session id that appears **zero** times in the real daemon log. It
is the per-session shim `detectors/version-update.py`. Consistent with the daemon yielding.

### What this costs and what it buys

Everything under "the contradiction" was an artifact of one wrong path. `claimed_chores()` and
the daemon AGREE; the daemon never ran a yielded chore; no premise of this card is invalidated.

**Item 1 is UNBLOCKED and now well-motivated**: five chores are handed to the server *right now*
and nothing on our side verifies the server runs them — a watchdog would watch a NON-empty set,
which was the exact thing in doubt.

### Hypotheses eliminated (kept — all still true, none of them was the answer)

| hypothesis | result |
|---|---|
| version skew — daemon runs older code | **No.** Daemon runs `2.4.1/scripts/daemon.py` (pid 30605, up since Aug 5 20:43) |
| my probe measured different code than the daemon | **No.** `diff` of cache vs repo `harness_backend.py` → IDENTICAL, same five chores |
| stale in-memory module (imported before an update) | **No.** `harness_backend.py` mtime 19:06 predates the daemon's 20:43 start |
| memoized claim/liveness result | **No.** `server_runs_chores()` documents "No memo"; `server_capabilities()` re-reads per call |
| env override in the daemon's environment | **No.** `ps eww -p 30605` shows no `JANITOR_AIMAESTRO_*` override |
| daemon HOME / `_liveness_path()` divergence | **No.** `HOME=/Users/emanuelesabetta`, identical to the shell's |
| chore-name vs task-name mismatch | **No.** The daemon's own `_build_tasks()` + `_yielded_task_names()` return all five names exactly |

**Dead end — do not repeat:** `lsof -p <daemon-pid>` shows no log file held open, because
`state.log_line` opens/appends/closes per line. The method that worked was cheaper than any
runtime probe: **read the path RESOLVER** (`log_dir()` + its env override), not the conventional
path.

### SUPERSEDED — do NOT carry forward

- *"the yield has never handed over anything on this host"* — false; it has yielded five chores
  since Aug 5 20:43.
- *"zero `chore-coordination` lines in the daemon's whole lifetime"* — false; wrong file. The
  project-scoped `.janitor/logs/daemon.log` is written by per-session shims, not the daemon.
- *"the daemon ran `version-update` three hours after the server came up"* — false; that was the
  per-session shim `[s:643908a6]`.
- The transition-flag inference built on the zero-line count (`daemon.py:2281`) — sound reasoning,
  worthless input.

### NEXT ACTION (one step, runnable)

Build the item-1 janitor-side watchdog: for each name in `harness_backend.claimed_chores()`,
compare `global_state.read_last_run(<chore>)` against 3x that chore's cadence and raise a LOUD
finding when a CLAIMED chore's completion stamp is stale. The set is non-empty on this host today
(all five), so the guard is testable the moment it exists — freeze a stamp and watch it fire.

Two things to settle while writing it, both recorded in Acceptance below: whether the janitor may
UN-YIELD a demonstrably dead claim (needs hysteresis so a server restart cannot flap ownership),
and the replay argument against janitor#221's recorded timestamps.

### Item 2 is OUTWARD-FACING and cannot be closed here

The chore⇄token⇄stamp⇄bound table must be *agreed on the #126/#111 threads* — cross-repo
negotiation, owner's call to initiate. The janitor-side half (item 1) is buildable alone and is
no longer blocked.

## WHY (three incidents, one shape)

When the ai-maestro server CLAIMS a janitor-daemon chore, the janitor stops running it —
and today nothing verifies the server actually RUNS what it claimed:

- **janitor#221**: the server-absorbed rotator tick stopped COMPLETING for 3.7 days
  (wedged between two slot captures); rotation was OFF; the owner rotated by hand. The
  janitor's side had zero alarm — `daemon_watchdog` covers only the janitor's OWN tasks.
- **ai-maestro#111**: a merely-alive server suppressed chores it never claimed — six
  chores unowned for 10-14 days (fixed on our side by claim-aware yield d45a843a, but
  the fix only checks the CLAIM, not the EXECUTION).
- **Today (item 5's evidence)**: `user-plugins-update` + `version-update` yielded to the
  server under the claim; the janitor's own user-scope pin did not converge for a day.

The claim handshake answers "who owns this?" but not "is the owner doing it?" — and a
claimed-but-wedged chore is strictly worse than an unclaimed one, because the fallback
(our daemon) is suppressed exactly then.

## The task (both halves, RECEIVE-model only — never call in)

1. **Janitor half — watch the claim-holder's completion stamps.** For every chore the
   yield hands to the server, the janitor keeps a staleness watchdog on that chore's
   completion evidence (the `~/.claude/janitor-control/<task>.last-run.ts` stamps
   ai-maestro#111 asked the server to write, or the server's own status files it
   already deposits). Claimed + stale past 3x cadence ⇒ a LOUD finding (ledger +
   heartbeat), and — decision needed — whether the janitor may RESUME a chore whose
   claim has demonstrably gone dead (un-yield on proof, with hysteresis so a restart
   blip doesn't flap ownership).
2. **Contract half — pin the vocabulary with the server.** One documented table:
   chore name ⇄ capability token ⇄ completion-stamp path ⇄ staleness bound. Today the
   mapping is implicit in two codebases. Route through ai-maestro#126 item 1 (the
   chore-claim inventory ask, already filed) + #111; the janitor's ARCHITECTURE.md gets
   the table, the server repo mirrors it.
3. **Escalation shape**: claimed-and-stale findings must reach the human via the normal
   channel (findings ledger + notify), naming WHICH side owns the fix — the #221 wedge
   would then have surfaced in hours, not days.

## Acceptance

- [ ] the chore⇄token⇄stamp⇄bound table exists in ARCHITECTURE.md and is agreed on the
      #126/#111 threads
- [ ] watchdog fires on claimed-but-stale within 3x cadence (test: freeze a stamp)
- [ ] un-yield-on-dead-claim decision recorded (yes with hysteresis, or no with why)
- [ ] replay check: with this in place, the #221 wedge would have alarmed on our side
      — argued in the card, ideally demonstrated with the recorded timestamps

## Pointers

- Claim machinery: `lib/harness_backend.py` (`claimed_chores`, `server_owns_every_chore`,
  `orphaned_chores`), daemon yield (`_task_yielded_to_server`, d45a843a).
- Existing one-sided watchdog: `lib/daemon_watchdog.py` (per-session shims for OUR tasks).
- Incidents: janitor#221, ai-maestro#111, janitor#134; sync ask: ai-maestro#126 item 1.
- Memory: [[janitor-daemon-handover-unowned-chores]], [[janitor-two-runtime-backends]].
