---
trdd-id: 6CRC9SQQ
title: Janitor-server delegation has no alignment contract — a server-claimed chore can wedge for days and neither side notices
column: todo
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T13:31:48+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# Janitor-server chore-delegation alignment contract (owner failure report 2026-08-06, item 7)

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
