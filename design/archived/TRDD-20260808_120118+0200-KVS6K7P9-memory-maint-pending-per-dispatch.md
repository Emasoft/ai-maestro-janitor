---
trdd-id: KVS6K7P9
title: memory-maint-pending is a single slot — per-dispatch state plus a per-root in-flight gate
column: complete
created: 2026-08-08T12:01:18+0200
updated: 2026-08-16T01:38:34+0200
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

## ⏵ STATE — 2026-08-13 03:46: THE BLOCK BELOW IS STALE. Items 1, 4 and 5 ALREADY SHIPPED.

**Read this before the 02:30 block; that block's premise is false.** It concluded "Not started —
no code written today" and built a sequencing argument on item 1 being unbuilt. Verified against
the tree just now, item 1 had already shipped **seven hours before it was written**:

| item | state | evidence |
|---|---|---|
| 1 per-dispatch state | **SHIPPED** | `7e0b4115` (Aug 12 19:54); scheduler writes `memory-maint-pending-<dispatch_id>.json` (`memory-maintenance.py:184,195,231`); `scripts/memory_dispatch_claim.py` claims one atomically and renames it out of the pool |
| 4 record carries SCOPE + ROOT | **SHIPPED** | `memory-maintenance.py:499-502` writes `scope`, `root`, `dispatch_id` |
| 5 reword the agent contract | **SHIPPED IN REPO** | `rules/janitor-heartbeat-protocol.md:46` now says *"CLAIM your assignment — do not read a shared file for it"* and explicitly forbids the legacy slot |
| 3 stale reclamation | **composes** | TRDD-2112XCKO, closed 2026-08-13 |
| 2 per-root in-flight gate | **the only work left** | — and its stated blocker is gone (below) |

**Item 2 is now UNBLOCKED, and the 02:30 finding 1 that blocked it is obsolete.** That finding
said a root-aware gate is unimplementable because `pending_agents` cannot name the root. True of
the manifest, irrelevant now: the per-dispatch record itself carries `scope` and `root`, so the
gate reads THAT, not the manifest. Finding 2 (a TTL stamp, not a flock) and finding 3 (the gate
must be machine-global in `global_state`, because the USER root is shared across projects while
the scheduler is per-project) both STAND and are the real design constraints.

**LIVE RISK, and it is the exact half-migrated window this card's third acceptance box exists to
prevent — currently OPEN on this host.** The repo rule is migrated; the INSTALLED rule is not.
`~/.claude/rules/janitor-heartbeat-protocol.md:39` still tells a spawned memory agent to read
`memory-maint-pending.json` — the legacy single slot — because installed rules come from the
plugin CACHE and the fix has not been published. The scheduler still dual-writes that legacy
file (`PENDING_LEGACY_NAME`, `:183,199`), so agents do not crash; they silently get the OLD
single-slot semantics, i.e. **the janitor#242 clobber is still live on this machine**. Nothing
to fix in code — it closes when a release ships (a USER decision, already held). Do NOT hand-edit
the installed rule: that hides the publish gap instead of closing it, and the next install
overwrites it anyway.

**NEXT ACTION:** build item 2 only — a machine-global, per-root, TTL'd in-flight stamp in
`global_state`, keyed by root path, read by `memory-maintenance.py` before it emits a marker
(DEFER, do not clobber). Do not rebuild items 1/4/5.

## ⏵ STATE — 2026-08-13 02:30 (SUPERSEDED — its "not started" premise is FALSE, see above)

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

- [x] Clobber scenario replayed — covered by TWO tests, each scoped to one half deliberately:
      `test_inflight_gate_defers_and_leaves_intervention_still_due` (a live stamp on the picked
      root ⇒ silent fire, and it proves the cadence was NOT consumed by clearing the stamp and
      re-firing to see the marker appear), and
      `test_second_dispatch_does_not_clobber_the_first_dispatchs_own_file` (the first dispatch's
      per-dispatch file byte-identical after a second fire). Shipped `1051ed85`; falsified by
      sabotaging the defer path to call `mark_ran`, which fails exactly the first test.
- [x] Id-mismatch — **STRUCTURALLY IMPOSSIBLE NOW, so the test as specified is moot.** The box
      assumed the agent READS a shared file and must detect being re-pointed. Item 1's claim
      model removed that shape: `memory_dispatch_claim.claim_one` hands a dispatch to exactly ONE
      agent and RENAMES the record out of the pool, so there is no later writer to disagree with
      and nothing to re-read. A guard against a state that can no longer occur is dead weight.
      **The residual risk is NOT id mismatch — it is an agent that never claims at all**, which
      is the next box.
- [x] Heartbeat-protocol rule + memory skills on the per-dispatch contract, with **no
      half-migrated window** — the window that was OPEN on 2026-08-13 is now CLOSED, and it closed
      exactly the predicted way: by a publish, not a hand-edit. Verified first-hand 2026-08-16:
      `diff rules/janitor-heartbeat-protocol.md ~/.claude/rules/janitor-heartbeat-protocol.md`
      differs by ONE line, the installer's `<!-- ai-maestro-janitor:rule-stamp -->` comment — the
      rule TEXT is byte-identical, and the installed copy's marker row orders the claim step and
      says *"do NOT read the legacy `memory-maint-pending.json` slot"*. All 7 chore skills name
      `memory_dispatch_claim` and ban the legacy slot in the same breath.
      Test-enforced, not merely present: `tests/test_memory_chore_claim_step.py` asserts the ban
      per skill and `tests/test_heartbeat_protocol_rule.py:215` asserts the rule row's exact
      wording — 44 passed with `test_memory_dispatch_claim.py`.
      **What this does NOT prove:** it is one host. A machine still running a pre-3.3.0 install
      reads the old rule text; nothing here can observe that, and nothing should — the mirror is
      what covers it, and it is self-retiring (below).
- [x] #242 answered when it ships — CLOSED 2026-08-14T22:10Z with a verification comment naming
      `memory_dispatch_claim.claim_one` and the atomic `os.rename`, posted by the AUTONOMOUS peer
      agent under the shared owner auth. #140 and #238 are likewise CLOSED. Confirmed by reading
      the issues, not from the card's own claim.

## ⏵ CLOSING NOTE 2026-08-16 — the legacy mirror is deliberate, and its removal is NOT residual work

The obvious last step looks like deleting the dual-write at
`scripts/detectors/memory-maintenance.py:254` — the standing "no backward-compatibility code" rule
points straight at it. **Do not.** Read `memory_dispatch_claim._retire_legacy_mirror` (`:99-132`)
first: the mirror is not an un-swept leftover, it is a record with a defined lifecycle that the
claimer deletes **iff the mirror describes the dispatch just claimed** — so it disappears on
consumption rather than accumulating, and `claim_one` refuses to treat it as a fallback
(`:155-160` explicitly: *"The legacy single slot is NOT a fallback"*). Its remaining job is the one
this host cannot see: an agent on an older install whose rule text still names the fixed path.
Deleting the write would strand that agent with no assignment at all, converting a covered case
into a silent no-op, and `tests/test_heartbeat_protocol_rule.py:78` would go red.

## Approval log

- 2026-08-16T01:38:34+0200 — COMPLETED by janitor-main-session (tier 0, own scope). Both remaining
  boxes were already satisfied by work that had shipped; nothing new was built. This card was
  **shipped-but-not-closed** — it sat at `column: todo` asserting open work while its last blocker
  (a publish) had landed two days earlier. That is the failure the kanban drain rule names: an
  untrue column hides a finished card as effectively as it hides a stalled one. Found by
  re-verifying the card's premise against the tree before picking it up, which is the only step
  that distinguishes the two.
