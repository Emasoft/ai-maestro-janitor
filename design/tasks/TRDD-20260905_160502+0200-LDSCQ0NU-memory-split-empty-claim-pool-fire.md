---
trdd-id: LDSCQ0NU
title: janitor-memory-split marker fires against an empty claim pool costing a full agent spawn to abstain
column: backburner
created: 2026-09-05T16:05:02+0200
updated: 2026-09-05T16:05:02+0200
current-owner: main-session
task-type: bugfix
priority: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [janitor-heartbeat, memory-dispatch, cost]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [janitor#300]
---

# janitor-memory-split marker fires against an empty claim pool costing a full agent spawn to abstain

## Why

`[janitor-memory-split]` fired on two consecutive heartbeats against an
empty claim pool. Fire 1 (~18:58 local) dispatched
`janitor-memory-subconscious-agent` per the heartbeat protocol; the claim
step returned exit 2 ("no claimable memory-maintenance dispatch") and the
agent abstained correctly, mutating nothing — but the spawn cost 326664
subagent tokens, 4 tool calls, 27s. Fire 2 (~19:04 local) was the same bare
marker against the same empty pool (a read-only check found no unclaimed
dispatch record).

The scheduler's content precheck (which gates the marker) and the claim pool
(which gates the agent's only legal action) are two independent conditions.
When the precheck says "content-due" but the claim pool is empty (e.g. a
peer session claimed the dispatch first), every session receiving the marker
pays a full agent spawn just to learn it lost the race — the marker carries
no way to distinguish "nothing due" from "someone else already took it".

Secondary, lower-confidence observation: fire 1's agent reported its chore
as `consolidate` while the marker said `[janitor-memory-split]` — a possible
chore-name default when the claim returns nothing rather than a
mismatch-with-real-work case (janitor#273/#275/#280 already fixed the known
mismatch class).

## What

Either direction removes the cost (issue reporter expressed no preference):
- Gate the marker itself on the claim pool, not only on the content
  precheck — do not emit `[janitor-memory-split]` when nothing is claimable.
- Make the abstain cheap: let the dispatcher stub attempt the claim itself
  and emit nothing on exit 2, so the marker is only ever emitted to a
  session that actually has claimable work. Keeps the "CLAIM, never read a
  shared file" invariant intact since the stub claims on the agent's behalf
  within the same fire.

## Acceptance criteria

- [ ] A heartbeat fire against an empty claim pool no longer spawns a full
      `janitor-memory-subconscious-agent` (either the marker is suppressed,
      or the stub's own cheap claim attempt short-circuits before spawning).
- [ ] A heartbeat fire against a non-empty claim pool is unaffected — the
      agent still spawns and claims normally.
- [ ] If a chore-name mismatch (marker says one chore, agent reports another)
      recurs WITH a claimable dispatch present, it is called out separately
      rather than folded into this fix (per the issue, that is the case
      worth escalating, not the empty-pool case this TRDD covers).

## Notes and lessons learned
