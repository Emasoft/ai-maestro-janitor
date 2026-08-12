---
trdd-id: KVS6K7P9
title: memory-maint-pending is a single slot — per-dispatch state plus a per-root in-flight gate
column: todo
created: 2026-08-08T12:01:18+0200
updated: 2026-08-13T02:30:00+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#242, janitor#238, janitor#140]
---

# memory-maint-pending: per-dispatch state + per-root in-flight gate

## Why (janitor#242, webdesign peer — measured)

`.janitor/state/memory-maint-pending.json` is the AUTHORITY a spawned memory agent must read
(heartbeat-protocol rule), but it is a single slot the next `[janitor-memory-*]` marker
overwrites unconditionally. Measured: a repair dispatch was clobbered by a consolidate marker
367 s later, SAME root, while `pending-agents.json` still listed the repair agent live and the
root still had 10 ERROR-level lint findings. Two live failure modes: (1) an in-flight agent
that re-reads its authority sees a DIFFERENT chore and can abandon half-finished work; (2) two
markers on one root put two editors on one knowledge store (the peer prevented both by hand —
nothing in the protocol asks for that).

## ⏵ STATE — 2026-08-13: item 2 is NOT standalone, and the gate cannot live where item 2 says

Picked this up to ship item 2 alone (the safety win without the protocol churn). It does not
decompose that way. Three findings, read from code:

1. **The manifest cannot name the root.** Item 2 says "check whether a live dispatch already
   holds that root". `pending_agents` stores `agent_id`, `description`, `ts`, `transcript`, and
   `is_janitor_agent` matches on the **agent TYPE** substring in `description`
   (`_JANITOR_AGENT_SIGNATURES`) — the assignment (chore, scope, root) is nowhere in the entry.
   So a root-aware gate is unimplementable from the manifest: **item 2 depends on item 1**, and
   the card's ordering hides that.

2. **A lock is the wrong primitive; the gate must be a TTL STAMP.** The natural reflex is a
   flock beside `ticket_dispatch_lock` / `settings_ensurer_lock`. It cannot work: those are held
   by a process for the length of a critical section, but this gate must span the AGENT's run
   (minutes), and the scheduler process exits the moment it emits the marker. The holder is not
   the scheduler. So the in-flight record has to be a stamp with a liveness window — which IS
   item 1's per-dispatch file. The two items are one mechanism seen from two ends.

3. **The scheduler is PER-PROJECT, but the USER root is MACHINE-GLOBAL — the gate as specified
   misses the corpus most at risk.** `memory-maintenance.py` runs from each project's heartbeat
   and reads that project's `.janitor/state`. Two different projects can therefore dispatch
   against the SAME USER memory root and neither sees the other's pending file. That is not
   hypothetical: the 2026-08-11 reproduction in item 4 involved a `consolidate/USER` dispatch.
   A gate that is per-project protects LOCAL and PROJECT roots and silently does nothing for
   USER. The in-flight stamp for a root must live in the janitor's machine-global control
   plane (`global_state`), keyed by the root path — not in per-project state.

**Consequence for sequencing:** the shippable unit is items 1+2 TOGETHER as one machine-global,
per-root, TTL'd dispatch record, with item 5's rule reword in the same release (the rule is what
tells a conscientious agent to re-read the file, so shipping the mechanism without the wording
leaves the mid-flight-adoption failure live). Item 3 then falls out for free, and TRDD-2112XCKO
consumes the same stamp.

**Not started** — no code written today. Recorded so the next pass does not re-derive this, and
does not ship a per-project gate believing the USER corpus is covered.

## What (the peer's shape, adjusted to what already exists)

1. **Per-dispatch state**: `memory-maint-pending-<dispatchId>.json` (or a list file); the
   marker's PAYLOAD carries the dispatch id; the agent verifies id ↔ state and STOPS on
   mismatch (never switches chore mid-flight). The single-slot path is retired — heartbeat
   rule text updated in the same release.
2. **Per-root in-flight gate in the SCHEDULER** (`memory-maintenance.py`): before stamping a
   new pending for a root, check whether a live dispatch (pending-agents manifest entry that
   is a janitor memory agent + unexpired) already holds that root — if so DEFER (no marker
   this fire) rather than clobber. This is the missing scheduler-side half; the EXISTING
   `memory_txn.commit_lock` already serializes commits per scope root, so mode 2's
   lost-update is bounded at the txn layer today — the gate removes the wasted double
   pass-planning and the semantic interleave above the txn layer.
3. Stale-dispatch reclamation: a per-dispatch file older than the agent-liveness window is
   the ORPHANED case — TRDD-2112XCKO's detector consumes it (these two cards compose: 2112XCKO
   detects the never-consumed file; this card guarantees the file it reads is per-dispatch and
   trustworthy).
4. **The per-dispatch state carries SCOPE and ROOT, not just the chore** — added after a
   SECOND live reproduction on the janitor's own host (2026-08-11, 515 s apart): a
   `consolidate/USER` dispatch was clobbered by a `conflict/LOCAL` marker while the first
   agent was still running, so the clobber changed the CORPUS as well as the verb. Mode 2 did
   not bite only because the two roots differed — luck, not design.
5. **Reword the agent-facing contract**: the heartbeat-protocol rule currently says the
   pending file IS the authority, which is exactly what makes a conscientious agent RE-READ it
   mid-run and adopt a foreign assignment. It must say: *your (intervention, scope, root) were
   fixed at launch; the pending file is not a live authority to poll* — with the dispatch-id
   check (item 1) as the only sanctioned re-read, and STOP-on-mismatch as the only response.

## Acceptance

- [ ] Clobber scenario replayed: second marker on a held root DEFERS, first agent's authority
      file untouched
- [ ] Id-mismatch test: agent reading a state whose dispatch id differs STOPS with a report
- [ ] Heartbeat-protocol rule + memory skills updated to the per-dispatch contract in the
      same release (no half-migrated window)
- [ ] #242 answered when it ships (#140 noted — the deferred dispatch also prevents the
      third ~189k abstain recurrence pattern)
