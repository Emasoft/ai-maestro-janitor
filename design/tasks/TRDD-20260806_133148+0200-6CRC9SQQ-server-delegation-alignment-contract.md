---
trdd-id: 6CRC9SQQ
title: Janitor-server delegation has no alignment contract — a server-claimed chore can wedge for days and neither side notices
column: dev
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T19:45:00+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# Janitor-server chore-delegation alignment contract (owner failure report 2026-08-06, item 7)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Started. A CONFIRMED CONTRADICTION was found before any code was written — and it invalidates
the premise of this card's item 1.** No fix yet, deliberately: the cause is not established and
I will not invent one (I already had to withdraw one guessed root cause today, on TRDD-50V256RH).

### The contradiction

Out-of-process, everything says the daemon SHOULD be yielding five chores right now:

```
server_runs_chores()  -> True          (server pid 19594, up since Aug 6 13:21)
claimed_chores()      -> ['marketplace-refresh','oauth-rotator-supervisor',
                          'oauth-rotator-tick','user-plugins-update','version-update']
_task_yielded_to_server(name, True) = True for all five
```

In-process, the daemon says it has **never yielded anything**:

- `grep -c "chore-coordination" .janitor/logs/daemon.log` → **0**. Not one line of EITHER kind
  (yield or resume), in a log spanning 2026-07-21 → now, i.e. the daemon's whole lifetime.
- The log is transition-only (`if bool(yielded) != chores_yielded_last_loop`) and the flag
  **initializes to `False`** (`daemon.py:2281`) — so zero transitions means `yielded` has been
  EMPTY on every loop, not "always yielding silently". This inference was checked, not assumed.
- The daemon **ran** `version-update` at 16:35:59 — three hours AFTER the server came up.

### Hypotheses ELIMINATED (do not re-test these)

| hypothesis | result |
|---|---|
| version skew — daemon runs older code | **No.** Daemon runs `2.4.1/scripts/daemon.py` (pid 30605, up since Aug 5 20:43) |
| my probe measured different code than the daemon | **No.** `diff` of cache vs repo `harness_backend.py` → IDENTICAL, and both compute the same five chores |
| stale in-memory module (imported before an update) | **No.** `harness_backend.py` mtime 19:06 predates the daemon's 20:43 start; only 2 `.py` files changed after, both venv internals |
| memoized claim/liveness result | **No.** `server_runs_chores()` documents "No memo"; `server_capabilities()` re-reads the probe file per call |
| env override in the daemon's inherited environment | **No.** `ps eww -p 30605` shows no `JANITOR_AIMAESTRO_*` override; my shell has none either |

### STRONGEST UNTESTED HYPOTHESIS (start here)

**The daemon's in-process `_liveness_path()` may not resolve to the file I read.** Everything
above is out-of-process reconstruction; I never observed the daemon's OWN evaluation. If its
`HOME`/cwd differs from my shell's, `server_capabilities()` returns `None` in-process ⇒ no claim
⇒ no yield ⇒ every observation above is consistent with no bug at all. Check the daemon's `HOME`
in `ps eww` output and compare against `_liveness_path()`'s resolution.

Second: whether the loop reaches `daemon.py:2346` on every iteration, and whether `tasks` there
contains those names.

### WHY THIS BLOCKS ITEM 1

Item 1 proposes a watchdog on "every chore the yield hands to the server". **On this host the
yield has never handed over anything**, so that watchdog would watch an empty set and report
healthy forever — a guard that cannot fire, which this project has now shipped twice
(`cold_cache_compact`, and nearly a third time in TRDD-PXP08ZQC). Establish whether the yield
path is exercised at all BEFORE building anything that assumes it is.

### Item 2 is OUTWARD-FACING and cannot be closed here

The chore⇄token⇄stamp⇄bound table must be *agreed on the #126/#111 threads* — cross-repo
negotiation, owner's call to initiate. The janitor-side half is buildable alone, but only after
the contradiction above is resolved.

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
